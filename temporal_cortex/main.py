from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv
from typing import Any, Dict
from datetime import datetime
import json
import os

load_dotenv()

mcp = FastMCP("temporal_cortex")

MEMORY_FILE = "memory.json"

def save_memory():
    with open(MEMORY_FILE, "w") as f:
        json.dump(memory, f, indent=2)

def load_memory():
    if os.path.exists(MEMORY_FILE):
        with open(MEMORY_FILE, "r") as f:
            try:
                return json.load(f)
            except json.JSONDecodeError:
                return {}
    return {}

memory: Dict[str, Dict[str, str]] = load_memory()

@mcp.tool(
    name="memorize",
    description="Add a value to memory with a given key."
)
async def memorize(key: str, value: str) -> Any:
    now = datetime.now().isoformat()
    memory[key.strip()] = {"content": value.strip(), "timestamp": now}
    save_memory()
    return {"status": "success", "current_length": len(memory)}

@mcp.tool(
    name="recall",
    description="Retrieve a single value from memory by its key."
)
async def recall(key: str) -> Any:
    if key in memory:
        return memory[key]
    else:
        return {"error": "key not found"}

@mcp.tool(
    name="recall_all",
    description="Retrieve all key-value pairs from memory."
)
async def recall_all() -> Dict[str, Dict[str, str]]:
    return memory

@mcp.tool(
    name="forget",
    description="Remove a single value from memory by its key."
)
async def forget(key: str) -> Any:
    if key in memory:
        del memory[key]
        save_memory()
        return {"status": "deleted", "key": key, "current_length": len(memory)}
    else:
        return {"error": "key not found"}

@mcp.tool(
    name="forget_all",
    description="Clear all stored texts from memory. Use this tool to reset or erase the memory."
)
async def forget_all() -> Any:
    memory.clear()
    save_memory()
    return {"status": "cleared", "current_length": 0}

if __name__ == "__main__":
    mcp.run()
