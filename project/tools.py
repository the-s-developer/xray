from tool_local_client import ToolLocalClient
from datetime import datetime
from project.utils import nanoid
import asyncio
from bson import ObjectId

tool_client = ToolLocalClient(server_id="project")

def serialize_mongo(obj):
    # ObjectId ve dict'leri otomatik stringe çevirir
    if isinstance(obj, list):
        return [serialize_mongo(item) for item in obj]
    elif isinstance(obj, dict):
        return {k: serialize_mongo(v) for k, v in obj.items()}
    elif isinstance(obj, ObjectId):
        return str(obj)
    return obj

def register_all_tools(app, projectId: str = None):
    async def save_script_tool(code: str) -> dict:
        db = app.state.db if app else None
        if db is None:
            raise Exception("DB bağlantısı gerekli")
        
        # Prefer passed-in projectId, fallback to global context
        effective_project_id = projectId
        if not effective_project_id:
            current_project = getattr(app.state, "current_project", None)
            if not current_project:
                raise Exception("No current project selected and no projectId given")
            effective_project_id = current_project["projectId"]
        
        latest = await db.scripts.find({"projectId": effective_project_id}).sort("version", -1).to_list(1)
        version = (latest[0]["version"] if latest else 0) + 1
        script_id = nanoid(14)
        now = datetime.utcnow().isoformat()
        script = {
            "scriptId": script_id,
            "projectId": effective_project_id,
            "version": version,
            "code": code,
            "createdAt": now,
        }
        result = await db.scripts.insert_one(script)
        script["_id"] = str(result.inserted_id)
        return serialize_mongo(script)  # Hatasız döner!

    tool_client.register_tool_auto(save_script_tool, description="Saves a script to the current project.")
