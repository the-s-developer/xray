# frontal_cortex/main.py

from mcp.server.fastmcp import FastMCP
from semantic_memory import SemanticMemory
from dotenv import load_dotenv
from typing import Optional
from datetime import datetime

load_dotenv()

mem = SemanticMemory()
mcp = FastMCP("longterm_memory")

def to_iso8601(val: Optional[str]) -> Optional[str]:
    """
    Convert input date string to ISO 8601 UTC format with 'Z'.
    Accepts e.g. '2024-06-08', '2024-06-08 14:30', or ISO 8601 already.
    """
    if not val:
        return None
    val = val.strip()
    if "T" in val and val.endswith("Z"):
        return val
    formats = [
        "%Y-%m-%d",
        "%Y-%m-%d %H:%M",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%dT%H:%M",
        "%Y-%m-%dT%H:%M:%S",
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(val, fmt)
            return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"
        except ValueError:
            continue
    raise ValueError(
        f"Invalid date format: '{val}'. "
        "Use ISO 8601 (2024-06-08T13:00:00.000Z) or YYYY-MM-DD[ HH:MM[:SS]]"
    )

@mcp.tool(
    name="memorize",
    description="Store text with optional key; returns the key."
)
async def memorize(content: str, key: Optional[str] = None):
    """Store a text in semantic memory. Optionally specify a key; returns the key used."""
    return {"key": mem.memorize(content, key)}

@mcp.tool(
    name="recall",
    description="Retrieve stored content by key."
)
async def recall(key: str):
    """Retrieve text from semantic memory by key."""
    return mem.recall(key)

@mcp.tool(
    name="semantic_search",
    description=(
        "Semantic search over stored memory; returns top‑k matches. "
        "Optionally filter by 'after' and 'before' (accepts ISO 8601 or date string: YYYY-MM-DD[ HH:MM[:SS]])."
    )
)
async def semantic_search(
    query: str,
    k: int = 5,
    after: Optional[str] = None,
    before: Optional[str] = None
):
    """
    Perform a semantic search over stored texts.
    Optionally filter results by timestamp (after/before, ISO 8601 or date string).
    """
    after_iso = to_iso8601(after) if after else None
    before_iso = to_iso8601(before) if before else None
    return mem.semantic_search(query, top_k=k, after=after_iso, before=before_iso)

@mcp.tool(
    name="forget",
    description="Remove stored content by key."
)
async def forget(key: str):
    """Remove a text from semantic memory by key."""
    return {"deleted": mem.forget(key)}

@mcp.tool(
    name="status",
    description="Get collection status: field names and record count."
)
async def status():
    """Get information about the memory collection: field names and record count."""
    return mem.status()

if __name__ == "__main__":
    mcp.run()
