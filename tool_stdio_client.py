from typing import Any, Dict, List
import json
from tool_client import ToolClient
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

def is_valid_openai_parameters(params):
    """
    params: dict -- Kontrol edilecek parameters nesnesi.
    """
    if not isinstance(params, dict):
        return False
    if params.get("type") != "object":
        return False
    if "properties" not in params or not isinstance(params["properties"], dict):
        return False
    # Her property'nin bir type'ı olmalı
    for key, val in params["properties"].items():
        if not isinstance(val, dict) or "type" not in val:
            return False
    return True

class ToolStdioClient(ToolClient):
    def __init__(self, server_id: str, command: str, args: List[str] = None):
        self.server_id = server_id
        self.command = command
        self.args = args or []
        self.session = None
        self._read = None
        self._write = None
        self._stdio_client = None
        self._read_write_cm = None

    async def __aenter__(self):
        server_params = StdioServerParameters(
            command=self.command,
            args=self.args
        )
        self._stdio_client = stdio_client(server_params)
        self._read_write_cm = self._stdio_client.__aenter__()
        self._read, self._write = await self._read_write_cm
        self.session = ClientSession(self._read, self._write)
        await self.session.__aenter__()
        await self.session.initialize()
        return self

    async def __aexit__(self, exc_type, exc, tb):
        await self.session.__aexit__(exc_type, exc, tb)
        await self._stdio_client.__aexit__(exc_type, exc, tb)

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        Return tool definitions in OpenAI function format.
        """
        raw_tools = (await self.session.list_tools()).tools

        tool_defs = []
        for tool in raw_tools:
            tool_defs.append({
                "type": "function",
                "function": {
                    "name": f"{tool.name}",
                    "description": tool.description,
                    "parameters": tool.inputSchema,
                }
            })
        return tool_defs

    async def call_tool(self,call_id: str, tool_name: str, args: Dict[str, Any]) ->  Any:
        """
        Call a tool and return the parsed JSON from the first text content,
        or the raw result as a fallback.
        """
        print(f"[DEBUG] call_tool: tool_name={tool_name}, args={args}")
        result = (await self.session.call_tool(tool_name, args)).model_dump()
        return result["content"][0]["text"]
