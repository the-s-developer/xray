# frontal_cortex/main.py
from mcp.server.fastmcp import FastMCP
from semantic_memory import SemanticMemory
from dotenv import load_dotenv
load_dotenv()

mem = SemanticMemory()
mcp = FastMCP("semantic_memory_milvus_agent")

@mcp.tool(name="memorize", description="Store text with optional key; returns the key.")
async def _memorize(content: str, key: str | None = None):
    return {"key": mem.memorize(content, key)}

@mcp.tool(name="recall", description="Retrieve stored content by key.")
async def _recall(key: str):
    return mem.recall(key)

@mcp.tool(name="semantic_search", description="Semantic search over stored memory; returns top‑k matches.")
async def _semantic_search(query: str, k: int = 5):
    return mem.semantic_search(query, top_k=k)

@mcp.tool(name="forget", description="Remove stored content by key.")
async def _forget(key: str):
    return {"deleted": mem.forget(key)}


@mcp.tool(name="status", description="Get collection status: field names and record count.")
async def _status():
    return mem.status()

if __name__ == "__main__":
    mcp.run()
