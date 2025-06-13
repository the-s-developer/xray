from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager
import os, asyncio, logging, traceback, uuid, json

from dotenv import load_dotenv
load_dotenv()

#---
os.environ["LOG_LEVEL"] = "error"
os.environ["UVICORN_LOG_LEVEL"] = "error"
#---

from xray_config import load_xray_config, get_model_config, build_tool_from_config, get_db_config
from openai_agent import OpenAIAgent
from context_memory import ContextMemory
from temporal_memory import TemporalMemory
from tool_router import ToolRouter
from tool_websocket_client import ToolWebSocketClient

from project.init import setup_all
from project.db import get_db

logger = logging.getLogger("xray")
logging.basicConfig(level=logging.INFO)

ws_clients = set()
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

async def setup_app_state(app):
    config = load_xray_config()
    mongo_uri, db_name = get_db_config(config)
    app.state.db = get_db(mongo_uri, db_name)
    models = config.get("models", [])
    tools = config.get("tools", [])
    tool_clients = [build_tool_from_config(t) for t in tools]

    #app.state.memory = ContextMemory(system_prompt="You are a helpful assistant.")
    app.state.memory = ContextMemory(system_prompt="You are a helpful assistant.")
    app.state.temporal=TemporalMemory(app.state.memory)
    tool_clients.append(app.state.temporal.create_tool_client())

    app.state.xray_models = models
    app.state.xray_tools = tools

    setup_all(app, tool_clients=tool_clients)

    app.state.memory.add_observer(lambda memory: asyncio.create_task(
        broadcast_ws_event({"event": "memory_update", "data": {"messages": memory.refine(with_id=False)}})
    ))

    app.state.ui_tool_client = ToolWebSocketClient("ui", ws_clients)
    app.state.router = ToolRouter([*tool_clients, app.state.ui_tool_client])
    await app.state.router.__aenter__()

async def cleanup_app_state(app):
    if hasattr(app.state, 'memory'):
        if hasattr(app.state.memory, "_observers"):
            app.state.memory._observers.clear()
    if hasattr(app.state, "router"):
        try:
            await app.state.router.__aexit__(None, None, None)
        except RuntimeError as exc:
            if "cancel scope" in str(exc):
                logger.warning("Router cancel scope hatası, atlanıyor: %r", exc)
            else:
                raise
    if hasattr(app.state, "db"):
        db = app.state.db
        if hasattr(db, "close") and callable(db.close):
            try:
                await db.close()
            except Exception:
                pass

@asynccontextmanager
async def lifespan(app: FastAPI):
    await setup_app_state(app)
    try:
        yield
    finally:
        await cleanup_app_state(app)

app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.websocket("/ws/bridge")
async def ws_bridge(ws: WebSocket):
    await ws.accept()
    ws_clients.add(ws)
    try:
        if hasattr(app.state, "memory"):
            await ws.send_json({"event": "memory_update",
                                "data": {"messages": app.state.memory.refine(with_id=False)}})
        while True:
            raw = await ws.receive_text()
            msg = json.loads(raw)
            if msg.get("event") == "tool_call":
                await broadcast_ws_event(msg)
            elif msg.get("event") == "tool_result":
                await app.state.ui_tool_client.receive_tool_result(msg["call_id"], msg["result"])
    except WebSocketDisconnect:
        ws_clients.discard(ws)

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
    await broadcast_ws_event({
        "event": "tools_updated",
        "tool_name": name,
    })
    return {"status": "ok", "tool": name}

@app.get("/api/models")
async def list_models():
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


@app.patch("/api/chat/{msg_id}")
async def update_message(msg_id: str, request: Request):
    data = await request.json()
    content = data.get("content", "")
    if not isinstance(content, str):
        return {"error": "content must be string"}

    updated = app.state.memory.update_content(msg_id, content)
    if updated:
        return {"status": "ok", "message": "Updated.", "id": msg_id}
    return {"error": "message not found"}


@app.post("/api/chat/insert_after")
async def insert_after_message(request: Request):
    data = await request.json()
    after_id = data.get("after_id")
    role = data.get("role", "user")
    content = data.get("content", "")

    new_id = app.state.memory.insert_after(after_id, role, content)
    if new_id is None:
        return {"error": "Mesaj bulunamadı"}
    return {"status": "ok", "id": new_id}


@app.delete("/api/chat/{msg_id}")
async def delete_message(msg_id: str):
    deleted = app.state.memory.delete([msg_id])
    if deleted:
        return {"status": "ok"}
    return {"error": "Mesaj bulunamadı"}


@app.post("/api/chat/delete_after/{msg_id}")
async def delete_after_message(msg_id: str):
    success = app.state.memory.delete_after(msg_id)
    if not success:
        return {"error": "System prompt silinemez veya mesaj bulunamadı"}
    return {"status": "ok"}

@app.post("/api/chat/replay")
async def replay_chat(request: Request):
    if backend_status["state"] == "running":
        return JSONResponse({"error": "Başka bir iş zaten çalışıyor."}, status_code=409)
    await set_status_and_notify("running")
    try:
        data = await request.json()
        model = data.get("model")
        memory = app.state.memory
        router = app.state.router
        models = getattr(app.state, "xray_models", [])
        model_cfg = get_model_config(model, models)
        # refine ile al, sadece system ve user mesajları
        base_msgs = [m for m in memory.refine(with_id=False) if m["role"] in ("system", "user")]
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
                    context_memory=memory,
                    on_status_update=agent_status_notify,
                ) as agent:
                    await agent.ask(
                        msg["content"],
                        stream=False
                    )
        memory.notify_observers()
        return {"status": "ok"}
    except Exception as exc:
        logger.exception("Replay sırasında hata oluştu: %s", exc)
        await set_status_and_notify("idle")
        return JSONResponse({"error": str(exc)}, status_code=500)
    finally:
        await set_status_and_notify("idle")
        
@app.post("/api/chat/replay_until/{until_id}")
async def replay_until_message(until_id: str, request: Request):
    memory = app.state.memory
    data = await request.json()
    model = data.get("model")
    router = app.state.router
    models = getattr(app.state, "xray_models", [])
    model_cfg = get_model_config(model, models)

    # Mesajları refine ile al, with_id=False ile temiz içerik
    original_msgs = [m for m in memory.refine(with_id=False)]

    # until_id'ye sahip user mesajının indexi
    idx = next((i for i, m in enumerate(original_msgs) if m["meta"]["id"] == until_id and m["role"] == "user"), None)
    if idx is None:
        return {"error": "Böyle bir user mesajı yok"}

    # until_id öncesindeki mesajlar
    before_msgs = original_msgs[:idx]

    # Memory temizle ve önceki mesajları ekle
    memory.clear()
    for msg in before_msgs:
        memory.add_message(msg)

    async def gen():
        async with OpenAIAgent(
            api_key=model_cfg["api_key"],
            base_url=model_cfg["base_url"],
            model_id=model,
            tool_client=router,
            context_memory=memory,
            on_status_update=agent_status_notify,
        ) as agent:
            # until_id mesajını stream ile yeniden çalıştır
            agent_stream = await agent.ask(original_msgs[idx]["content"], stream=True)
            async for sse in agent_stream:
                yield sse if sse.startswith("data:") else f"data: {sse}\n\n"

        # until_id'den sonraki assistant/tool mesajlarını ekle
        j = idx + 1
        while j < len(original_msgs) and original_msgs[j]["role"] in ("assistant", "tool"):
            j += 1
        for m in original_msgs[j:]:
            memory.add_message(m)
        memory.notify_observers()

    return StreamingResponse(gen(), media_type="text/event-stream")


@app.post("/api/chat/bulk_delete")
async def bulk_delete(request: Request):
    data = await request.json()
    ids_to_delete = set(data.get("ids", []))
    deleted_count = app.state.memory.delete(list(ids_to_delete))
    return {"status": "ok", "deleted": deleted_count}

@app.post("/api/chat/restart")
async def restart_backend():
    try:
        job_id = backend_status.get("job_id")
        task = active_job.get(job_id)
        if task:
            task.cancel()
            active_job.pop(job_id, None)
    except:
        pass

    await set_status_and_notify("idle", 0, None)

    # Only clear memory, do NOT re-enter or exit context managers!
    app.state.memory.clear()
    await broadcast_ws_event({
        "event": "memory_update",
        "data": {"messages": app.state.memory.snapshot()}
    })
    await broadcast_ws_event({"event": "backend_reset"})
    return {"status": "ok", "message": "Backend resetlendi."}

@app.get("/api/chat/prompts")
async def get_chat_prompts():
    return app.state.memory.snapshot()

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
        return result 
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
        context_memory=app.state.memory,
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
                context_memory=app.state.memory,
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

@app.get("/api/chat/raw_messages")
async def get_raw_messages():
    return {"messages": app.state.memory.snapshot()}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("xray-api:app", host="0.0.0.0", port=8000, reload=True, log_level="error")
