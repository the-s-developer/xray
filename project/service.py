# project/service.py

from project.models import Project
from project.utils import nanoid, drop_mongo_id, drop_mongo_ids, now_iso
from typing import List

from pw_simulator.pw_runner.runner import execute_python_code
from project.utils import nanoid, now_iso, drop_mongo_id
import json
from project.models import Prompt

# --- PROJECTS ---

async def create_project(db, data):
    project_id = nanoid()
    prompts = [Prompt(**p).dict() for p in data.get("prompts", [])]
    project = Project(
        projectId=project_id,
        projectName=data.get("projectName", ""),
        projectDescription=data.get("projectDescription", ""),
        projectStatus=data.get("projectStatus", "active"),
        scraperDomain=data.get("scraperDomain", ""),
        createdAt=now_iso(),
        updatedAt=now_iso(),
        prompts=prompts,
        executionConfig=data.get("executionConfig", {}),
    )
    await db.projects.insert_one(project.dict())
    return drop_mongo_id(project.dict())


async def list_projects(db) -> List[dict]:
    docs = await db.projects.find({}).to_list(length=100)
    return drop_mongo_ids(docs)

async def get_project(db, project_id):
    doc = await db.projects.find_one({"projectId": project_id})
    return drop_mongo_id(doc) if doc else None

async def update_project(db, project_id, updates):
    updates["updatedAt"] = now_iso()
    updated = await db.projects.find_one_and_update(
        {"projectId": project_id},
        {"$set": updates},
        return_document=True
    )
    return drop_mongo_id(updated) if updated else None

async def delete_project(db, project_id):
    # Tüm bağlı script ve execution’ları da sil
    await db.scripts.delete_many({"projectId": project_id})
    await db.executions.delete_many({"projectId": project_id})
    result = await db.projects.delete_one({"projectId": project_id})
    return result.deleted_count > 0

# --- PROMPTS ---

async def update_prompts(db, project_id, prompts):
    validated_prompts = []
    for p in prompts:
        prompt = Prompt(**p).dict() 
        if prompt["role"] == "tool" and prompt.get("content") and len(prompt["content"]) > 5000:
            prompt["content"] = prompt["content"][:1000] + "... [Truncated]"
        validated_prompts.append(prompt)
    updated = await db.projects.find_one_and_update(
        {"projectId": project_id},
        {"$set": {"prompts": validated_prompts, "updatedAt": now_iso()}},
        return_document=True
    )
    return drop_mongo_id(updated) if updated else None

async def get_prompts(db, project_id):
    doc = await db.projects.find_one({"projectId": project_id}, {"_id": 0, "prompts": 1})
    return doc.get("prompts", []) if doc else []

# --- SCRIPTS ---

async def find_script(db, project_id, script_version=None):
    if script_version is not None:
        script = await db.scripts.find_one({
            "projectId": project_id,
            "version": int(script_version)
        })
        return drop_mongo_id(script) if script else None
    scripts = await db.scripts.find({"projectId": project_id}).sort("version", -1).to_list(1)
    return drop_mongo_id(scripts[0]) if scripts else None

async def save_script(db, project_id, code, created_by="unknown", generated_by_llm=False, notes=""):
    latest = await db.scripts.find({"projectId": project_id}).sort("version", -1).to_list(1)
    version = (latest[0]["version"] if latest else 0) + 1
    script_id = nanoid(14)
    script = {
        "scriptId": script_id,
        "projectId": project_id,
        "version": version,
        "code": code,
        "createdAt": now_iso(),
        "createdBy": created_by,
        "generatedByLLM": generated_by_llm,
        "notes": notes
    }
    await db.scripts.insert_one(script)
    return drop_mongo_id(script)

async def delete_script(db, script_id):
    result = await db.scripts.delete_one({"scriptId": script_id})
    return result.deleted_count > 0

async def update_script(db, script_id, code=None, notes=None):
    update_fields = {}
    if code is not None:
        update_fields["code"] = code
    if notes is not None:
        update_fields["notes"] = notes
    if not update_fields:
        raise ValueError("No fields to update.")
    update_fields["updatedAt"] = now_iso()
    updated = await db.scripts.find_one_and_update(
        {"scriptId": script_id},
        {"$set": update_fields},
        return_document=True
    )
    return drop_mongo_id(updated) if updated else None

async def list_scripts(db, project_id, limit=100):
    scripts = await db.scripts.find({"projectId": project_id}).sort("version", -1).to_list(length=limit)
    return drop_mongo_ids(scripts)

# --- EXECUTIONS ---

async def save_execution(db, project_id, data):
    from project.utils import nanoid
    execution_id = nanoid(14)
    now = now_iso()
    # result alanı dict olmalı
    result = data.get("result", {})
    if not isinstance(result, dict):
        result = {}
    execution = {
        "executionId": execution_id,
        "projectId": project_id,
        "scriptId": data.get("scriptId"),
        "scriptVersion": int(data.get("scriptVersion", 0)),
        "status": data.get("status", "pending"),
        "startTime": now,
        "endTime": data.get("endTime"),
        "duration": data.get("duration", 0),
        "resultCount": data.get("resultCount", 0),
        "output": data.get("output", ""),
        "errorMessage": data.get("errorMessage", ""),
        "result": result,
    }
    await db.executions.insert_one(execution)
    return drop_mongo_id(execution)

async def list_executions(db, project_id, page=1, page_size=20, script_id=None, status=None):
    query = {"projectId": project_id}
    if script_id:
        query["scriptId"] = script_id
    if status:
        query["status"] = status
    total = await db.executions.count_documents(query)
    executions = (
        await db.executions
        .find(query)
        .sort("startTime", -1)
        .skip((page - 1) * page_size)
        .limit(page_size)
        .to_list(length=page_size)
    )
    return executions, total


# --- CURRENT PROJECT STATE (Context) ---

async def set_current_project(request, db, project_id):
    project = await db.projects.find_one({"projectId": project_id})
    if not project:
        return None
    request.app.state.current_project = project
    return {"ok": True, "current_project": drop_mongo_id(project)}

def get_current_project_by_state(request):
    project = getattr(request.app.state, "current_project", None)
    return drop_mongo_id(project) if project else None


async def find_script_by_id(db, script_id):
    script = await db.scripts.find_one({"scriptId": script_id})
    return drop_mongo_id(script) if script else None

async def run_script_for_project(db, project_id, script_id=None, max_count=3):
    # Script bulma mantığı (script_id öncelikli)
    script = None
    if script_id:
        script = await db.scripts.find_one({"projectId": project_id, "scriptId": script_id})
    if not script:
        # ScriptId yoksa en son versiyonu getir
        scripts = await db.scripts.find({"projectId": project_id}).sort("version", -1).to_list(1)
        if scripts:
            script = scripts[0]
    if not script:
        raise ValueError(f"Script not found (project_id={project_id}, script_id={script_id})")

    result = await execute_python_code(
        script["code"],
        no_prints=False,
        max_count=max_count
    )
    output_json = result.get("result")
    logs = result.get("logs", "")
    error = ""
    if output_json and isinstance(output_json, dict):
        error = output_json.get("error", "")
    if not error and logs and "traceback" in logs.lower():
        error = logs

    execution_id = nanoid(14)
    now = now_iso()
    execution = {
        "executionId": execution_id,
        "projectId": project_id,
        "scriptId": script["scriptId"],
        "scriptVersion": script["version"],
        "status": "error" if error else "success",
        "startTime": now,
        "endTime": now,
        "duration": 1,
        "resultCount": len(output_json.get("data", [])) if output_json and isinstance(output_json, dict) and "data" in output_json else 0,
        "output": json.dumps(output_json, ensure_ascii=False) if output_json else "",     # BURASI
        "logs": logs if logs else "",                                                    # BURASI
        "errorMessage": error or "",                                                     # BURASI
        "result": output_json if isinstance(output_json, dict) else {},
    }
    await db.executions.insert_one(execution)
    return drop_mongo_id(execution)

