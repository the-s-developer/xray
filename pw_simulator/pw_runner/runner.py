import os
import sys
import tempfile
import subprocess
import json
from typing import Any

import re

def replace_libname(code: str) -> str:
    # playwright. → patchright.
    #code = code.replace("playwright.", "patchright.")
    # import playwright → import patchright
    #code = re.sub(r'\bimport\s+playwright\b', 'import patchright', code)
    # from playwright → from patchright
    #code = re.sub(r'\bfrom\s+playwright\b', 'from patchright', code)
    return code


def read_injectable_code():
    inject_folder = os.path.join(os.path.dirname(__file__), "inject")
    header, footer = "", ""
    header_path = os.path.join(inject_folder, "header.py")
    footer_path = os.path.join(inject_folder, "footer.py")

    if os.path.exists(header_path):
        with open(header_path, encoding="utf-8") as f:
            header = f.read()
    if os.path.exists(footer_path):
        with open(footer_path, encoding="utf-8") as f:
            footer = f.read()
    return header, footer

async def execute_python_code(code: str, no_prints=True, max_count: int = 5) -> dict[str, Any]:
    if not code.strip():
        return {"success": False, "error": "No code provided", "stdout": "", "stderr": "", "json": None}


    code=replace_libname(code)

    if max_count is not None:
        code = f"MAX_COUNT = {max_count}\n" + code

    
    header, footer = read_injectable_code()
    full_code = header + "\n" + code + "\n" + footer

    try:
        with tempfile.TemporaryDirectory() as tmpdir:
            temp_script_path = os.path.join(tmpdir, "user_script.py")
            with open(temp_script_path, "w", encoding="utf-8") as temp_script:
                temp_script.write(full_code)

            result = subprocess.run(
                [sys.executable, temp_script_path],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=120
            )

            data = result.stdout.strip()
            logs = result.stderr.strip()

            if data:
                try:
                    data = json.loads(data)
                except Exception:
                    data = None

            result={}
            if data is not None:
                 result["result"]= data

            if no_prints==False:
                result["logs"]= logs
            
            return result

    except subprocess.TimeoutExpired:
        return {"error": "Script execution timed out","logs": logs if 'logs' in locals() else ''}
    except Exception as e:
        return {"exception": str(e), "logs": logs if 'logs' in locals() else ''}
    

