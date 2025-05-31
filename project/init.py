# project/init.py
from fastapi import FastAPI
from .api import router

def setup_all(app: FastAPI, db=None, tool_clients=None):
    """
    Tüm project altı setup işlemlerini merkezi olarak yapar.
    Args:
        app: FastAPI app instance.
        db: Opsiyonel olarak dışarıdan db instance verilebilir.
        tool_clients: Tool clientlar listesini referans olarak alır.
    """
    # Eğer db dışarıdan verilirse onu kullan, yoksa otomatik get_db ile kur (ama genelde lifespan ile atanacak)
    if db is not None:
        app.state.db = db

    app.include_router(router)

    # Tool registration: tool_clients parametresi ToolRouter’a aktarılacak
    from .tools import tool_client, register_all_tools
    register_all_tools(app)
    if tool_clients is not None:
        tool_clients.append(tool_client)
