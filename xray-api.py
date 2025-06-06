# xray-api.py

from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os, asyncio, logging, traceback, uuid, json

from dotenv import load_dotenv
load_dotenv()

from xray_config import load_xray_config, get_model_config, build_tool_from_config
from openai_agent import OpenAIAgent
from context_memory import ContextMemoryManager
from tool_router import ToolRouter
from tool_websocket_client import ToolWebSocketClient

from project.init import setup_all
from xray_config import load_xray_config, get_db_config
from project.db import get_db

logger = logging.getLogger("xray")
logging.basicConfig(level=logging.INFO)

ws_clients = set()  # Aktif frontend websocket bağlantıları
active_job: dict[str, asyncio.Task] = {}
backend_status = {"state": "idle", "tps": 0.0, "job_id": None}

def _update_status(state: str, tps: float = 0.0, job_id: str | None = None):
    backend_status.update({"state": state, "tps": round(tps, 2), "job_id": job_id})

async def agent_status_notify(status):
    await broadcast_ws_event({"event": "agent_status", "data": status})

async def set_status_and_notify(state: str, tps: float = 0.0, job_id: str | None = None):
    _update_status(state, tps, job_id)
    await agent_status_notify(backend_status)


async def broadcast_ws_event(event_data):
    closed = set()
    for ws in ws_clients:
        try:
            await ws.send_json(event_data)
        except Exception:
            closed.add(ws)
    ws_clients.difference_update(closed)

@asynccontextmanager
async def lifespan(app: FastAPI):
    config = load_xray_config()
    mongo_uri, db_name = get_db_config(config)
    app.state.db = get_db(mongo_uri, db_name)     
    models = config.get("models", [])
    tools = config.get("tools", [])
    tool_clients = [build_tool_from_config(t) for t in tools]
    app.state.xray_models = models
    app.state.xray_tools = tools
    setup_all(app, tool_clients=tool_clients)
    
    app.state.memory = ContextMemoryManager(system="You are a helpful assistant.")
    app.state.memory.add_observer(lambda snap: asyncio.create_task(
        broadcast_ws_event({"event": "memory_update", "data": snap})
    ))   
    app.state.ui_tool_client = ToolWebSocketClient("ui", ws_clients)
    app.state.router = ToolRouter([*tool_clients, app.state.ui_tool_client])
    await app.state.router.__aenter__()

    yield
    await app.state.router.__aexit__(None, None, None)

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ----------------- WebSocket -----------------
@app.websocket("/ws/bridge")
async def ws_bridge(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        if hasattr(app.state, "memory"):
            await ws.send_json({"event": "memory_update",
                                "data": app.state.memory.get_memory_snapshot()})
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)

            if msg.get("event") == "tool_call":
                await broadcast_ws_event(msg)                           # diğer clientlara ilet
            elif msg.get("event") == "tool_result":
                await app.state.ui_tool_client.receive_tool_result(msg["call_id"], msg["result"])
    except WebSocketDisconnect:
        ws_clients.discard(ws)


# --- Memory Observer: memory değişince tüm WS clientlara bildir ---
def memory_observer_callback(snapshot):
    print("--------------------------->DEBUG: memory_observer_callback triggered")
    asyncio.create_task(
        broadcast_ws_event({"event": "memory_update", "data": snapshot})
    )
@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    logger.exception("API genel hata: %s", exc)
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "trace": traceback.format_exc()}
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
    # Direkt konfigden oku, OpenAI ile canlı sorgulama yok!
    models = getattr(app.state, "xray_models", [])
    model_list = []
    for m in models:
        model_id = m.get("id") or m.get("model_id") or m.get("name")
        model_name = model_id or str(m)
        label = m.get("label") or model_name.replace("-", " ").upper()
        model_list.append({
            "value": model_name,
            "label": label,
        })
    return {"models": model_list}

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
        print(msg)
        if msg["meta"]["id"] == msg_id:
            msg["content"] = content
            # Eğer mesajda id yoksa, yeni id ekle
            if not msg["meta"]["id"]:
                msg["meta"]["id"] = app.state.memory._new_id()
            app.state.memory._notify_observers()
            return {"status": "ok", "message": "Updated.", "id": msg["meta"]["id"]}
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
        if msg["meta"]["id"] == msg_id:
            del messages[i]
            found = True
            break
    if found:
        app.state.memory._notify_observers()
        return {"status": "ok"}
    return {"error": "Mesaj bulunamadı"}

@app.post("/api/chat/delete_after/{msg_id}")
async def delete_after_message(msg_id: str):
    memory = app.state.memory
    msgs = memory._messages
    index = next((i for i, m in enumerate(msgs) if m.get("meta", {}).get("id") == msg_id), None)
    if index is None:
        return {"error": "Mesaj bulunamadı"}
    # System prompt’u asla silme!
    protected_ids = [m["meta"]["id"] for m in msgs if m["role"] == "system"]
    del_msgs = msgs[index:]  # kendisi dahil, sonrakilerle birlikte
    keep_msgs = msgs[:index]  # kendisine kadar (hariç)
    # System prompt’u silmeye kalkarsa engelle!
    if any(m["meta"]["id"] in protected_ids for m in del_msgs):
        return {"error": "System prompt silinemez"}
    memory._messages = keep_msgs
    memory._notify_observers()
    return {"status": "ok"}



@app.post("/api/chat/replay")
async def replay_chat(request: Request):
    # Single job kontrolü: başka bir iş varsa 409 döndür
    if backend_status["state"] == "running":
        return JSONResponse({"error": "Başka bir iş zaten çalışıyor."}, status_code=409)
    
    # Status "running" yapılır
    await set_status_and_notify("running")
    try:
        data = await request.json()
        model = data.get("model")
        memory = app.state.memory
        router = app.state.router
        models = getattr(app.state, "xray_models", [])
        model_cfg = get_model_config(model, models)

        # Sadece "system" ve "user" mesajlarını alıp memory'yi sıfırla
        base_msgs = [m.copy() for m in memory.get_all_messages() if m["role"] in ("system", "user")]
        memory.clear()
        for msg in base_msgs:
            if msg["role"] == "system":
                memory.add_message(msg)
            elif msg["role"] == "user":
                async with OpenAIAgent(
                    api_key=model_cfg["api_key"],
                    base_url=model_cfg["base_url"],
                    model_id=model,
                    tool_client=router,
                    memory_manager=memory,
                    on_status_update=agent_status_notify,
                ) as agent:
                    await agent.ask(
                        msg["content"],
                        stream=False
                    )
        memory._notify_observers()
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("Replay sırasında hata oluştu: %s", exc)
        # Hata durumunda status sıfırla
        await set_status_and_notify("idle")
        return JSONResponse({"error": str(exc)}, status_code=500)
    finally:
        # Ne olursa olsun status idle'a çek
        await set_status_and_notify("idle")




@app.post("/api/chat/replay_until/{until_id}")
async def replay_until_message(until_id: str, request: Request):
    memory = app.state.memory
    data = await request.json()
    model = data.get("model")
    router = app.state.router
    models = getattr(app.state, "xray_models", [])
    model_cfg = get_model_config(model, models)
    original_msgs = [m.copy() for m in memory.get_all_messages()]
    idx = next((i for i, m in enumerate(original_msgs) if m["meta"]["id"] == until_id and m["role"] == "user"), None)
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
    async with OpenAIAgent(
        api_key=model_cfg["api_key"],
        base_url=model_cfg["base_url"],
        model_id=model,
        tool_client=router,
        memory_manager=memory,
        on_status_update=agent_status_notify,
    ) as agent:
        await agent.ask(
            original_msgs[idx]["content"],
            stream=False
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
    protected_ids = [m["meta"]["id"] for m in msgs if m["role"] == "system"]
    ids_to_delete -= set(protected_ids)
    new_msgs = []
    i = 0
    while i < len(msgs):
        m = msgs[i]
        if m["meta"]["id"] in ids_to_delete:
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
    app.state.memory = ContextMemoryManager(system="You are a helpful assistant.")
    for cb in old_observers:
        app.state.memory.add_observer(cb)
    app.state.memory._notify_observers()
    return {"status": "ok", "message": "Context/memory resetlendi."}

@app.post("/api/chat/restart")
async def restart_backend():
    # Aktif job varsa iptal et
    job_id = backend_status.get("job_id")
    task = active_job.get(job_id)
    if task:
        task.cancel()
        active_job.pop(job_id, None)

    # Memory sıfırla
    old_observers = list(getattr(app.state.memory, "_observers", []))
    app.state.memory = ContextMemoryManager(system="You are a helpful assistant.")
    for cb in old_observers:
        app.state.memory.add_observer(cb)
    app.state.memory._notify_observers()
    # --- Ek olarak: Manuel ws memory update event'i gönder ---
    await broadcast_ws_event({
        "event": "memory_update",
        "data": app.state.memory.get_memory_snapshot()
    })

    # Backend status sıfırla
    await set_status_and_notify("idle", 0, None)

    # Gerekirse frontend'e reset event'i yayınla
    await broadcast_ws_event({"event": "backend_reset"})

    return {"status": "ok", "message": "Backend resetlendi."}



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
        memory.add_message(prm)

    memory._notify_observers()
    return {"status": "ok"}


@app.get("/api/tools")
async def list_tools():
    return {"tools": await app.state.router.list_tools()}

@app.post("/api/tools/run")
async def run_tool(request: Request):
    data = await request.json()
    call_id = data.get("call_id") or str(uuid.uuid4())
    try:
        result = await app.state.router.call_tool(call_id,
                                                  data["tool_name"],
                                                  data.get("params", {}))
        return {"output": result}
    except Exception as exc:
        return {"error": str(exc)}


@app.post("/api/chat/ask")
async def ask(request: Request):
    data = await request.json()
    model_id = data.get("model")
    models = getattr(app.state, "xray_models", [])
    model_cfg = get_model_config(model_id, models)
    async with OpenAIAgent(
        api_key=model_cfg["api_key"],
        base_url=model_cfg["base_url"],
        model_id=model_id,
        tool_client=app.state.router,
        memory_manager=app.state.memory,
        on_status_update=agent_status_notify,
    ) as agent:
        reply = await agent.ask(
            data["message"],
            stream=False
        )
    return {"reply": reply}

@app.post("/api/chat/ask_stream")
async def ask_stream(request: Request):
    if backend_status["state"] == "running":
        return JSONResponse({"error": "Başka bir iş zaten çalışıyor."}, status_code=409)
    data = await request.json()
    prompt = data["message"]
    model_id = data.get("model")
    job_id = str(uuid.uuid4())
    await set_status_and_notify("running", job_id=job_id)
    models = getattr(app.state, "xray_models", [])
    model_cfg = get_model_config(model_id, models)

    async def gen():
        task = asyncio.current_task()
        active_job[job_id] = task

        try:
            async with OpenAIAgent(
                api_key=model_cfg["api_key"],
                base_url=model_cfg["base_url"],
                model_id=model_id,
                tool_client=app.state.router,
                memory_manager=app.state.memory,
                on_status_update=agent_status_notify,
            ) as agent:
                agent_stream = await agent.ask(prompt, stream=True)
                async for sse in agent_stream:
                    try:
                        payload = json.loads(sse.removeprefix("data: ").strip())
                        if payload.get("type") == "end":
                            await set_status_and_notify("idle", payload.get("tps", 0), None)
                    except Exception:
                        pass
                    yield sse if sse.startswith("data:") else f"data: {sse}\n\n"
        except asyncio.CancelledError:
            yield "data: " + json.dumps({"type": "stopped"}) + "\n\n"
        finally:
            active_job.pop(job_id, None)
            if backend_status["job_id"] == job_id:
                await set_status_and_notify("idle", 0, None)

    return StreamingResponse(gen(), media_type="text/event-stream")

@app.post("/api/chat/stop")
async def stop_job():
    task = active_job.get(backend_status.get("job_id"))
    if task:
        task.cancel()
        return {"status": "cancelling"}
    return {"status": "idle"}



@app.get("/api/chat/status")
async def get_status():
    return backend_status


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("xray-api:app", host="0.0.0.0", port=8000, reload=True, log_level="trace")