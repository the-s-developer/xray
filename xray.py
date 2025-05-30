#!/usr/bin/env python3
import argparse
import asyncio
from datetime import datetime
import json
import sys
from motor.motor_asyncio import AsyncIOMotorClient
from pw_simulator.pw_runner.runner import execute_python_code

MONGO_URI = "mongodb://mongo:mongo@192.168.99.97:27017"
DB_NAME = "xray"

def now_iso():
    return datetime.utcnow().isoformat()

async def get_db():
    client = AsyncIOMotorClient(MONGO_URI)
    return client[DB_NAME]

async def find_script(db, project_id, script_version=None):
    if script_version is not None:
        script = await db.scripts.find_one({
            "projectId": project_id,
            "version": int(script_version)
        })
        if script:
            return script
        print(f"[ERROR] Script version {script_version} not found in project {project_id}.")
        sys.exit(1)
    # Get latest version
    scripts = await db.scripts.find({"projectId": project_id}).sort("version", -1).to_list(1)
    if scripts:
        return scripts[0]
    print(f"[ERROR] No script found in project {project_id}.")
    sys.exit(1)

async def save_execution(db, execution):
    await db.executions.insert_one(execution)
    print(f"[INFO] Execution saved with id: {execution['executionId']}")

async def run(project_id, script_version, max_count):
    db = await get_db()
    script = await find_script(db, project_id, script_version)
    print(f"[INFO] Running script (project: {project_id}, version: {script['version']}, id: {script['scriptId']}, max_count: {max_count})")
    # Kod çalıştır
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

    from project.utils import nanoid  # DB util fonksiyonun varsa kullan
    execution_id = nanoid(14) if "nanoid" in globals() else script["scriptId"] + "EXE"

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
        "output": json.dumps(output_json) if output_json else "",
        "logs": logs,
        "errorMessage": error or "",
        "result": output_json if isinstance(output_json, dict) else {},
    }
    await save_execution(db, execution)
    print_execution(execution)

def print_execution(exe):
    print("\n==== EXECUTION RESULT ====")
    print(f"Status      : {exe.get('status')}")
    print(f"Script ver. : {exe.get('scriptVersion')}")
    print(f"Started at  : {exe.get('startTime')}")
    print(f"Ended at    : {exe.get('endTime')}")
    print(f"Duration    : {exe.get('duration')} s")
    print(f"Result count: {exe.get('resultCount')}")
    print("\n--- Output ---")
    try:
        output = exe.get("output", "")
        if output:
            try:
                out_obj = json.loads(output)
                print(json.dumps(out_obj, ensure_ascii=False, indent=2))
            except Exception:
                print(output)
        else:
            print("(No output)")
    except Exception:
        print("(Could not parse output)")
    if exe.get("logs"):
        print(f"\n--- Logs ---\n{exe['logs']}")
    if exe.get("errorMessage"):
        print(f"\n--- ERROR ---\n{exe['errorMessage']}")
    print("========================\n")

def main():
    parser = argparse.ArgumentParser(description="XRAY CLI - Run a script for a project (direct db, no API)")
    parser.add_argument("project",   help="Project ID (required)")
    parser.add_argument("--script-version", "-s", required=False, help="Script version (optional)")
    parser.add_argument("--max-count", "-m",required=False ,type=int, default=3, help="Maximum count (default: 3)")
    args = parser.parse_args()
    asyncio.run(run(args.project, args.script_version, args.max_count))


if __name__ == "__main__":
    main()
