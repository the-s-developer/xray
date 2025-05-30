from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware

from openai_agent import OpenAIAgent
from context_memory import ContextMemoryManager
from tool_router import ToolRouter
from tool_stdio_client import ToolStdioClient
from tool_websocket_client import ToolWebSocketClient

from project.api import router as project_router
from project.init import setup_all


import os
import asyncio
import logging
from contextlib import asynccontextmanager
import traceback
import json
import uuid

logger = logging.getLogger("xray")
logging.basicConfig(level=logging.INFO)

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")

ws_clients = set()  # Aktif frontend websocket bağlantıları

# --- FastAPI Initialization & Lifespan ---

@asynccontextmanager
async def lifespan(app: FastAPI):
    tool_clients = []
    setup_all(app, tool_clients=tool_clients)

    MCP_REMOTE_CLIENTS = [
        ToolStdioClient(server_id="investigator", command="npx", args=["-y", "@playwright/mcp@latest"]),
        ToolStdioClient(server_id="simulator", command="python", args=["pw_simulator/main.py"]),
    ]
    # Tek bir WebSocketClient, memory ve tool events için
    app.state.ui_tool_client = ToolWebSocketClient("ui", ws_clients)
    app.state.router = ToolRouter([
        *MCP_REMOTE_CLIENTS,
        *tool_clients,
        app.state.ui_tool_client
    ])
    await app.state.router.__aenter__()
    app.state.memory = ContextMemoryManager(
        system="You are a helpful assistant.",
        max_big_content=2,
        big_content_threshold=2000
    )
    app.state.memory.add_observer(memory_observer_callback)
    app.state.agent = OpenAIAgent(api_key=OPENAI_API_KEY)
    await app.state.agent.__aenter__()
    yield
    await app.state.agent.__aexit__(None, None, None)
    await app.state.router.__aexit__(None, None, None)

app = FastAPI(lifespan=lifespan)


app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- WebSocket endpoint ---
@app.websocket("/ws/bridge")
async def ws_tools(websocket: WebSocket):
    await websocket.accept()
    ws_clients.add(websocket)
    try:
        # İlk bağlantıda memory snapshot'ı gönder (isteğe bağlı)
        if hasattr(app.state, "memory"):
            snapshot = app.state.memory.get_memory_snapshot()
            await websocket.send_json({"event": "memory_update", "data": snapshot})
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            # 1. Tool çağrısı: backend, frontend'e yönlendirir
            if msg.get("event") == "tool_call":
                # Burada frontend bir tool'a cevap dönecekse bekleyebilirsin (ya da iletirsin)
                # Eğer backend de tool handler ise burada çalıştırıp cevapla!
                print(f"WS tool_call: {msg}")
                # İstersen event'i diğer websocketlere broadcast edebilirsin
                await broadcast_ws_event(msg)
            # 2. Tool sonucu: tool çağrısını başlatan backend/agent future'ına sonucu döndür
            elif msg.get("event") == "tool_result":
                call_id = msg.get("call_id")
                result = msg.get("result")
                # ToolWebSocketClient future çözümü:
                await app.state.ui_tool_client.receive_tool_result(call_id, result)
            # 3. İsteğe bağlı: başka event'ler (memory_update vs)
    except WebSocketDisconnect:
        ws_clients.remove(websocket)

# --- WebSocket Broadcast Helper ---
async def broadcast_ws_event(event_data):
    closed_clients = set()
    for ws in ws_clients:
        try:
            await ws.send_json(event_data)
        except Exception:
            closed_clients.add(ws)
    ws_clients.difference_update(closed_clients)

# --- Memory Observer: memory değişince tüm WS clientlara bildir ---
def memory_observer_callback(snapshot):
    asyncio.create_task(
        broadcast_ws_event({"event": "memory_update", "data": snapshot})
    )

@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("API genel hata: %s", exc)
    return JSONResponse(
        status_code=500,
        content={
            "error": str(exc),
            "trace": traceback.format_exc()
        }
    )

@app.post("/api/ui_tools/add")
async def add_ui_tool(request: Request):
    data = await request.json()
    name = data.get("name")
    description = data.get("description")
    parameters = data.get("parameters")
    app.state.ui_tool_client.register_tool(name, description, parameters)

    # Tüm frontendlere tools_updated event'i gönder
    await broadcast_ws_event({
        "event": "tools_updated",
        "tool_name": name,
    })

    return {"status": "ok", "tool": name}


from uuid import uuid4

@app.get("/api/models")
async def list_models():
    try:
        models = await app.state.agent.client.models.list()
        model_list = []
        for model in models.data:
            if is_chat_model(model.id):
                model_list.append({
                    "value": model.id,
                    "label": model.id.replace("-", " ").upper()
                })
        return {"models": model_list}
    except Exception as e:
        return {"models": [], "error": str(e)}

def is_chat_model(model_id):
    ok = (
        model_id.startswith("gpt-3.5-turbo") or
        model_id.startswith("gpt-4o") or
        model_id.startswith("gpt-4.1") or
        model_id.startswith("gpt-4-") or
        model_id.startswith("gpt-4.5")
    )
    not_ok = any(x in model_id for x in [
        "audio", "search", "preview", "image", "tts", "transcribe", "vision", "instruct"
    ])
    return ok and not not_ok

@app.patch("/api/chat/{msg_id}")
async def update_message(msg_id: str, request: Request):
    data = await request.json()
    content = data.get("content", "")
    if not isinstance(content, str):
        return {"error": "content must be string"}
    messages = app.state.memory._messages
    for msg in messages:
        if msg.get("id") == msg_id:
            msg["content"] = content
            # Eğer mesajda id yoksa, yeni id ekle
            if not msg.get("id"):
                msg["id"] = app.state.memory._new_id()
            app.state.memory._notify_observers()
            return {"status": "ok", "message": "Updated.", "id": msg["id"]}
    return {"error": "message not found"}


@app.post("/api/chat/insert_after")
async def insert_after_message(request: Request):
    data = await request.json()
    after_id = data.get("after_id")
    role = data.get("role", "user")
    content = data.get("content", "")
    messages = app.state.memory._messages
    index = next((i for i, m in enumerate(messages) if m.get("id") == after_id), None)
    if index is None:
        return {"error": "Mesaj bulunamadı"}
    new_id = app.state.memory._new_id()
    new_msg = {"id": new_id, "role": role, "content": content}
    messages.insert(index + 1, new_msg)
    app.state.memory._notify_observers()
    return {"status": "ok", "id": new_id}

@app.delete("/api/chat/{msg_id}")
async def delete_message(msg_id: str):
    messages = app.state.memory._messages
    found = False
    for i, msg in enumerate(messages):
        if msg.get("id") == msg_id:
            del messages[i]
            found = True
            break
    if found:
        app.state.memory._notify_observers()
        return {"status": "ok"}
    return {"error": "Mesaj bulunamadı"}

@app.post("/api/chat/ask")
async def ask(request: Request):
    data = await request.json()
    user_message = data["message"]
    model = data.get("model", "gpt-4.1-nano")
    reply = await app.state.agent.ask(
        tool_client=app.state.router,
        prompt=user_message,
        memory_manager=app.state.memory,
        model=model,
    )
    return {"reply": reply}

@app.post("/api/chat/replay")
async def replay_chat(request: Request):
    memory = app.state.memory
    base_msgs = [m.copy() for m in memory.get_all_messages() if m["role"] in ("system", "user")]
    memory.clear()
    for msg in base_msgs:
        if msg["role"] == "system":
            memory.add_message(msg)
        elif msg["role"] == "user":
            await app.state.agent.ask(
                tool_client=app.state.router,
                prompt=msg["content"],
                memory_manager=memory,
                model="gpt-4.1-nano"
            )
    memory._notify_observers()
    return {"status": "ok"}

@app.post("/api/chat/replay_until/{until_id}")
async def replay_until_message(until_id: str, request: Request):
    memory = app.state.memory
    data = await request.json()
    model = data.get("model", "gpt-4.1-nano")
    original_msgs = [m.copy() for m in memory.get_all_messages()]
    idx = next((i for i, m in enumerate(original_msgs) if m["id"] == until_id and m["role"] == "user"), None)
    if idx is None:
        return {"error": "Böyle bir user mesajı yok"}
    before = []
    i = 0
    while i < idx:
        before.append(original_msgs[i])
        i += 1
    memory.clear()
    memory.add_message(before[0])
    for m in before[1:]:
        memory.add_message(m)
    await app.state.agent.ask(
        tool_client=app.state.router,
        prompt=original_msgs[idx]["content"],
        memory_manager=memory,
        model=model,
    )
    j = idx + 1
    while j < len(original_msgs) and original_msgs[j]["role"] in ("assistant", "tool"):
        j += 1
    for m in original_msgs[j:]:
        memory.add_message(m)
    memory._notify_observers()
    return {"status": "ok"}

@app.post("/api/chat/bulk_delete")
async def bulk_delete(request: Request):
    memory = app.state.memory
    data = await request.json()
    ids_to_delete = set(data.get("ids", []))
    msgs = memory._messages
    protected_ids = [m["id"] for m in msgs if m["role"] == "system"]
    ids_to_delete -= set(protected_ids)
    new_msgs = []
    i = 0
    while i < len(msgs):
        m = msgs[i]
        if m["id"] in ids_to_delete:
            if m["role"] == "user":
                i += 1
                while i < len(msgs) and msgs[i]["role"] in ("assistant", "tool"):
                    i += 1
                continue
            else:
                i += 1
                continue
        else:
            new_msgs.append(m)
            i += 1
    memory._messages = new_msgs
    memory._notify_observers()
    return {"status": "ok"}

@app.post("/api/chat/reset")
async def reset_state():
    old_observers = list(getattr(app.state.memory, "_observers", []))
    app.state.memory = ContextMemoryManager(
        system="You are a helpful assistant.",
        max_big_content=2,
        big_content_threshold=2000
    )
    for cb in old_observers:
        app.state.memory.add_observer(cb)
    app.state.memory._notify_observers()
    return {"status": "ok", "message": "Context/memory resetlendi."}

@app.get("/api/chat/prompts")
async def get_chat_prompts():
    # Tüm mesajları, olduğu gibi (tüm roller dahil) döndür
    return app.state.memory.get_all_messages()


@app.post("/api/chat/prompts")
async def set_chat_prompts(request: Request):
    data = await request.json()
    prompts = data.get("prompts", [])
    memory = app.state.memory
    memory.clear()
    for prm in prompts:
        if prm["role"] in ("system", "user"):
            memory.add_message({"role": prm["role"], "content": prm["content"]})
    memory._notify_observers()
    return {"status": "ok"}


@app.get("/api/tools")
async def list_tools():
    tools = await app.state.router.list_tools()
    return {"tools": tools}

@app.post("/api/tools/run")
async def run_tool(request: Request):
    data = await request.json()
    tool_name = data.get("tool_name")
    params = data.get("params", {})
    call_id = data.get("call_id") or str(uuid.uuid4())
    try:
        result = await app.state.router.call_tool(call_id, tool_name, params)
        return {"output": result}
    except Exception as e:
        return {"error": str(e)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("xray-api:app", host="0.0.0.0", port=8000, reload=True, log_level="trace")