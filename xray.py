#!/usr/bin/env python3
import argparse
import asyncio
import json
import sys
from xray_config import load_xray_config, get_db_config
from project.db import get_db
from project.service import run_script_for_project

cfg = load_xray_config()
mongo_uri, db_name = get_db_config(cfg)

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

async def run(project_id, script_id=None, script_version=None, max_count=3):
    db = get_db(mongo_uri, db_name)
    try:
        execution = await run_script_for_project(
            db,
            project_id,
            script_id=script_id,
            script_version=script_version,
            max_count=max_count
        )
    except ValueError as e:
        print(f"[ERROR] {e}")
        sys.exit(1)
    print_execution(execution)

def main():
    parser = argparse.ArgumentParser(description="XRAY CLI - Run a script for a project (direct db, no API)")
    parser.add_argument("project",   help="Project ID (required)")
    parser.add_argument("--script-id", "-i", required=False, help="Script ID (optional)")
    parser.add_argument("--script-version", "-s", required=False, type=int, help="Script version (optional, integer)")
    parser.add_argument("--max-count", "-m", required=False, type=int, default=3, help="Maximum count (default: 3)")
    args = parser.parse_args()
    asyncio.run(
        run(
            args.project,
            script_id=args.script_id,
            script_version=args.script_version,
            max_count=args.max_count
        )
    )

if __name__ == "__main__":
    main()
