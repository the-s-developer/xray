# project/api.py
from fastapi import APIRouter, Request, HTTPException, Body, Query
from typing import List, Dict, Any
from project.service import (
    create_project, list_projects, get_project, update_project, delete_project,
    save_script, list_scripts, find_script, update_script, delete_script,
    save_execution, list_executions, update_prompts, get_prompts,
    set_current_project, get_current_project_by_state,run_script_for_project

)

from project.utils import drop_mongo_id, drop_mongo_ids

router = APIRouter()

# -- PROJECT ENDPOINTS --

@router.post("/api/project", response_model=dict)
async def create_project_ep(request: Request):
    db = request.app.state.db
    body = await request.json()
    proj = await create_project(db, body)
    return drop_mongo_id(proj)

@router.get("/api/project", response_model=List[dict])
async def list_projects_ep(request: Request):
    db = request.app.state.db
    return await list_projects(db)

@router.get("/api/project/{project_id}", response_model=dict)
async def get_project_ep(project_id: str, request: Request):
    db = request.app.state.db
    proj = await get_project(db, project_id)
    if not proj:
        raise HTTPException(404, "Project not found")
    return drop_mongo_id(proj)

@router.put("/api/project/{project_id}", response_model=dict)
async def update_project_ep(project_id: str, request: Request):
    db = request.app.state.db
    body = await request.json()
    proj = await update_project(db, project_id, body)
    if not proj:
        raise HTTPException(404, "Project not found")
    return drop_mongo_id(proj)

@router.delete("/api/project/{project_id}", response_model=dict)
async def delete_project_ep(project_id: str, request: Request):
    db = request.app.state.db
    ok = await delete_project(db, project_id)
    if not ok:
        raise HTTPException(404, "Project not found")
    return {"ok": True}

# -- SCRIPT ENDPOINTS --

@router.post("/api/project/{project_id}/script", response_model=dict)
async def add_script_ep(project_id: str, request: Request):
    db = request.app.state.db
    body = await request.json()
    script = await save_script(
        db,
        project_id=project_id,
        code=body["code"],
        created_by=body.get("createdBy", "unknown"),
        generated_by_llm=body.get("generatedByLLM", False),
        notes=body.get("notes", "")
    )
    return drop_mongo_id(script)

@router.get("/api/project/{project_id}/script", response_model=List[dict])
async def get_project_scripts_ep(project_id: str, request: Request):
    db = request.app.state.db
    scripts = await list_scripts(db, project_id)
    return [drop_mongo_id(s) for s in scripts]

@router.get("/api/project/{project_id}/script/{script_version}", response_model=dict)
async def get_script_by_version_ep(project_id: str, script_version: int, request: Request):
    db = request.app.state.db
    script = await find_script(db, project_id, script_version)
    if not script:
        raise HTTPException(404, "Script version not found")
    return drop_mongo_id(script)

@router.put("/api/project/{project_id}/script/{script_id}", response_model=dict)
async def update_script_ep(project_id: str, script_id: str, request: Request):
    db = request.app.state.db
    body = await request.json()
    script = await update_script(db, script_id, code=body.get("code"), notes=body.get("notes"))
    if not script:
        raise HTTPException(404, "Script not found")
    return drop_mongo_id(script)

@router.delete("/api/project/{project_id}/script/{script_id}", response_model=dict)
async def delete_script_ep(project_id: str, script_id: str, request: Request):
    db = request.app.state.db
    ok = await delete_script(db, script_id)
    if not ok:
        raise HTTPException(404, "Script not found")
    return {"ok": True}

# -- EXECUTION ENDPOINTS --

@router.post("/api/project/{project_id}/execution", response_model=dict)
async def add_execution_ep(project_id: str, request: Request):
    db = request.app.state.db
    body = await request.json()
    execution = await save_execution(db, project_id, body)
    return drop_mongo_id(execution)


@router.get("/api/project/{project_id}/execution", response_model=Dict[str, Any])
async def get_project_executions_ep(
    project_id: str,
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    script_id: str = Query(None),
    status: str = Query(None)
):
    db = request.app.state.db
    executions, total = await list_executions(
        db, project_id, page=page, page_size=page_size,
        script_id=script_id, status=status
    )
    return {"executions": drop_mongo_ids(executions), "total": total}



# -- PROMPT ENDPOINTS --

@router.post("/api/project/{project_id}/prompts", response_model=dict)
async def set_project_prompts_ep(project_id: str, request: Request, prompts: List[dict] = Body(...)):
    db = request.app.state.db
    proj = await update_prompts(db, project_id, prompts)
    if not proj:
        raise HTTPException(404, "Project not found")
    return drop_mongo_id(proj)

@router.get("/api/project/{project_id}/prompts", response_model=List[dict])
async def get_project_prompts_ep(project_id: str, request: Request):
    db = request.app.state.db
    prompts = await get_prompts(db, project_id)
    return prompts

# -- CURRENT PROJECT CONTEXT ENDPOINTS --

@router.post("/api/project/current", response_model=dict)
async def set_current_project_ep(request: Request):
    db = request.app.state.db
    body = await request.json()
    project_id = body.get("projectId")
    result = await set_current_project(request, db, project_id)
    if not result:
        raise HTTPException(404, "Project not found")
    return result

@router.get("/api/project/current", response_model=dict)
async def get_current_project_ep(request: Request):
    proj = get_current_project_by_state(request)
    if not proj:
        raise HTTPException(404, "No current project set")
    return drop_mongo_id(proj)


@router.post("/api/project/{project_id}/run", response_model=dict)
async def run_script_ep(project_id: str, request: Request):
    db = request.app.state.db
    body = await request.json()
    script_id = body.get("scriptId")
    max_count = body.get("maxCount", 3)
    try:
        execution = await run_script_for_project(
            db, project_id,
            max_count=max_count,
            script_id=script_id
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    return {"ok": True, "execution": execution}
