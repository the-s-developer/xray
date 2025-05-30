# project/api.py
from fastapi import APIRouter, Request, HTTPException, Body
from typing import List
from datetime import datetime
from project.models import Project, ScriptVersion, Execution
from project.utils import nanoid, drop_mongo_id
import json
from project.utils import nanoid, strip_mongo_ids

router = APIRouter()

def now_iso():
    return datetime.utcnow().isoformat()

# -- PROJECT ENDPOINTS --

@router.post("/api/projects", response_model=Project)
async def create_project(request: Request):
    db = request.app.state.db
    body = await request.json()
    project_id = nanoid()
    project = Project(
        projectId=project_id,
        projectName=body.get("projectName", ""),
        projectDescription=body.get("projectDescription", ""),
        projectStatus=body.get("projectStatus", "active"),
        scraperDomain=body.get("scraperDomain", ""),
        createdAt=now_iso(),
        updatedAt=now_iso(),
        prompts=body.get("prompts", []),
        executionConfig=body.get("executionConfig", {}),
    )
    await db.projects.insert_one(project.dict())
    return project

@router.get("/api/projects", response_model=List[Project])
async def list_projects(request: Request):
    db = request.app.state.db
    docs = await db.projects.find({}).to_list(length=100)
    return [drop_mongo_id(doc) for doc in docs]

@router.get("/api/projects/{project_id}", response_model=Project)
async def get_project(project_id: str, request: Request):
    db = request.app.state.db
    doc = await db.projects.find_one({"projectId": project_id})
    if not doc:
        raise HTTPException(404, "Project not found")
    return drop_mongo_id(doc)

# -- SCRIPT ENDPOINTS --

@router.post("/api/scripts", response_model=ScriptVersion)
async def add_script(request: Request):
    db = request.app.state.db
    body = await request.json()

    # En son versiyonu bul (descending sort)
    latest = await db.scripts.find({"projectId": body["projectId"]}).sort("version", -1).to_list(1)
    version = (latest[0]["version"] if latest else 0) + 1

    script_id = nanoid(14)
    script = ScriptVersion(
        scriptId=script_id,
        projectId=body["projectId"],
        version=version,  # Oto-arttırılan versiyon!
        code=body["code"],
        createdAt=now_iso(),
        createdBy=body.get("createdBy", "unknown"),
        generatedByLLM=body.get("generatedByLLM", False),
        notes=body.get("notes", "")
    )
    await db.scripts.insert_one(script.dict())
    return script


@router.get("/api/projects/{project_id}/scripts", response_model=List[ScriptVersion])
async def get_project_scripts(project_id: str, request: Request):
    db = request.app.state.db
    scripts = await db.scripts.find({"projectId": project_id}).sort("version", -1).to_list(100)
    return [drop_mongo_id(s) for s in scripts]

# -- SCRIPT SİLME ENDPOINTİ --
@router.delete("/api/scripts/{script_id}")
async def delete_script(script_id: str, request: Request):
    db = request.app.state.db
    result = await db.scripts.delete_one({"scriptId": script_id})
    if result.deleted_count == 0:
        raise HTTPException(404, "Script not found")
    return {"ok": True}
# project/api.py

@router.put("/api/scripts/{script_id}", response_model=ScriptVersion)
async def update_script(script_id: str, request: Request):
    db = request.app.state.db
    body = await request.json()
    updated = await db.scripts.find_one_and_update(
        {"scriptId": script_id},
        {"$set": {
            "code": body.get("code"),
            "notes": body.get("notes", ""),
            "updatedAt": now_iso(),
        }},
        return_document=True
    )
    if not updated:
        raise HTTPException(404, "Script not found")
    return drop_mongo_id(updated)

# -- EXECUTION ENDPOINTS --

@router.post("/api/executions", response_model=Execution)
async def add_execution(request: Request):
    db = request.app.state.db
    body = await request.json()
    execution_id = nanoid(14)

    # result alanı dict olmalı, string ise boş dict'e çevir
    result = body.get("result", {})
    if not isinstance(result, dict):
        result = {}

    execution = Execution(
        executionId=execution_id,
        projectId=body["projectId"],
        scriptId=body["scriptId"],
        scriptVersion=int(body["scriptVersion"]),
        status=body.get("status", "pending"),
        startTime=now_iso(),
        endTime=body.get("endTime"),
        duration=body.get("duration", 0),
        resultCount=body.get("resultCount", 0),
        output=body.get("output", ""),
        errorMessage=body.get("errorMessage", ""),
        result=result
    )
    try:
        await db.executions.insert_one(execution.dict())
    except Exception as e:
        print("[ERROR] Execution insert failed:", e)
        raise HTTPException(500, "Failed to insert execution")
    return execution


@router.get("/api/projects/{project_id}/executions", response_model=List[Execution])
async def get_project_executions(project_id: str, request: Request):
    db = request.app.state.db
    executions = await db.executions.find({"projectId": project_id}).sort("startTime", -1).to_list()
    return [drop_mongo_id(e) for e in executions]

# PROMPT SYNC
@router.post("/api/projects/{project_id}/prompts", response_model=Project)
async def set_project_prompts(project_id: str, request: Request, prompts: List[dict] = Body(...)):
    db = request.app.state.db
    updated = await db.projects.find_one_and_update(
        {"projectId": project_id},
        {"$set": {
            "prompts": prompts,
            "updatedAt": now_iso()
        }},
        return_document=True
    )
    if not updated:
        raise HTTPException(404, "Project not found")
    return drop_mongo_id(updated)

@router.get("/api/projects/{project_id}/prompts")
async def get_project_prompts(project_id: str, request: Request):
    db = request.app.state.db
    doc = await db.projects.find_one({"projectId": project_id}, {"_id": 0, "prompts": 1})
    if not doc:
        raise HTTPException(404, "Project not found")
    return doc.get("prompts", [])

# -- SCRIPT ÇALIŞTIR (RUN-LATEST) --
from pw_simulator.pw_runner.runner import execute_python_code

@router.post("/api/projects/{project_id}/run")
async def run_script(
    project_id: str,
    request: Request,
    max_count: int = 3
):
    print(f"project run: {project_id}, max_count: {max_count}")
    db = request.app.state.db
    body = await request.json()
    script_id = body.get("scriptId")

    if script_id:
        script = await db.scripts.find_one({"projectId": project_id, "scriptId": script_id})
        if not script:
            raise HTTPException(404, "Script not found")
    else:
        # fallback: latest
        script = await db.scripts.find({"projectId": project_id}).sort("version", -1).to_list(1)
        if not script:
            raise HTTPException(404, "No script found for project")
        script = script[0]

    # Kod çalıştırma aynı
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
    if not error and "traceback" in logs.lower():
        error = logs

    execution_id = nanoid(14)
    now = now_iso()
    # Burada result alanı için dict kontrolü yapıldı!
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
        "output": json.dumps(output_json) if output_json else "",
        "logs": logs,
        "errorMessage": error or "",
        "result": output_json if isinstance(output_json, dict) else {},
    }
    try:
        insert_result = await db.executions.insert_one(execution)
        print("[DEBUG] Inserted executionId:", insert_result.inserted_id)
    except Exception as e:
        print("[ERROR] Execution insert failed:", e)

    project = await db.projects.find_one({"projectId": project_id})
    return strip_mongo_ids({
        "project": project,
        "script": script,
        "execution": execution,
        "raw_result": result,
    })

@router.post("/api/project/current")
async def set_current_project(request: Request):
    """
    Seçili projeyi global context'e kaydeder.
    Body: { "projectId": "PRJ123..." }
    """
    db = request.app.state.db
    body = await request.json()
    project_id = body.get("projectId")
    if not project_id:
        raise HTTPException(400, "projectId is required")

    project = await db.projects.find_one({"projectId": project_id})
    if not project:
        raise HTTPException(404, "Project not found")

    # Context'e kaydet (thread-safe)
    request.app.state.current_project = project
    return {"ok": True, "current_project": drop_mongo_id(project)}

@router.get("/api/project/current")
async def get_current_project(request: Request):
    """
    O anda seçili olan projeyi döndürür.
    """
    project = getattr(request.app.state, "current_project", None)
    if not project:
        raise HTTPException(404, "No current project set")
    return drop_mongo_id(project)
