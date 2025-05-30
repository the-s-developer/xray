# project/init.py
from .api import router
from fastapi import FastAPI

def setup_all(app: FastAPI, tool_clients=None):
    from .db import get_db
    app.state.db = get_db()
    app.include_router(router)

    # Tool registration: tool_clients parametresi ToolRouter’a aktarılacak
    from .tools import tool_client, register_all_tools
    register_all_tools(app)
    if tool_clients is not None:
        tool_clients.append(tool_client)
