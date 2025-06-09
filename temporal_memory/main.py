from mcp.server.fastmcp import FastMCP
from dotenv import load_dotenv

load_dotenv()

mcp = FastMCP("temporal_memory")

memory = ""
summaries = []  # Eklenecek yeni özet alanı

def summarize_content(content: str) -> str:
    # Çok basit bir özetleyici örneği. Dilersen burada GPT, başka LLM ya da servis kullanabilirsin.
    return content.strip()[:100] + ("..." if len(content.strip()) > 100 else "")

@mcp.tool(
    name="push",
    description="Add a value to memory. New content is appended with '\\n---\\n' separator. Also adds a summary."
)
async def push(value: str):
    """
    Add content to memory. Appends with '\n---\n' separator if not empty.
    Also generates and stores a summary of the value.
    """
    global memory, summaries
    value = value.strip()
    if memory:
        memory = memory + "\n---\n" + value
    else:
        memory = value

    summary = summarize_content(value)
    summaries.append(summary)
    return {"status": "success", "summary": summary}

@mcp.tool(
    name="recall",
    description="Retrieve the combined content string from memory."
)
async def recall():
    """
    Retrieve all content from memory.
    """
    global memory
    return {"content": memory}

@mcp.tool(
    name="forget",
    description="Clear all stored content from memory and summaries."
)
async def forget():
    """
    Clear the memory and summaries.
    """
    global memory, summaries
    memory = ""
    summaries = []
    return {"status": "success"}

@mcp.tool(
    name="get_summaries",
    description="Retrieve the list of all content summaries added so far."
)
async def get_summaries():
    """
    Retrieve all content summaries.
    """
    global summaries
    return {"summaries": summaries}

if __name__ == "__main__":
    mcp.run()
