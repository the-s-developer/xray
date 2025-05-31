from typing import Dict, Any, List, Optional
from contextlib import AsyncExitStack
from tool_client import ToolClient

class ToolRouter(ToolClient):
    """
    Manages both local and remote (MCP) tools via a unified interface.
    Each client must be a ToolClient.
    Implements the ToolClient interface itself.
    """
    def __init__(self, clients: Optional[List[ToolClient]] = None):
        self.clients = clients or []
        self._stack: AsyncExitStack = AsyncExitStack()
        self.active_clients: List[ToolClient] = []

    async def __aenter__(self) -> "ToolRouter":
        for client in self.clients:
            active_client = await self._stack.enter_async_context(client)
            self.active_clients.append(active_client)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._stack.aclose()

    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        Return all registered tools in OpenAI function format, dynamically.
        """
        tools = []
        for client in self.active_clients:
            client_id = getattr(client, 'server_id', getattr(client, 'client_id', str(id(client))))
            client_tools = await client.list_tools()
            for tool in client_tools:
                if "function" in tool:
                    raw_name = tool["function"]["name"]
                    description = tool["function"].get("description", "")
                    parameters = tool["function"].get("parameters", {"type": "object"})
                else:
                    raw_name = tool.get("name")
                    description = tool.get("description", "")
                    parameters = tool.get("parameters", tool.get("inputSchema", {"type": "object"}))
                prefixed_name = f"{client_id}__{raw_name}"
                tools.append({
                    "type": "function",
                    "function": {
                        "name": prefixed_name,
                        "description": description,
                        "parameters": parameters
                    }
                })
        return tools

    async def call_tool(self, call_id: str, name: str, args: dict) -> str:
        if not isinstance(name, str) or not name:
            raise ValueError(f"Tool name must be a non-empty string, got: {repr(name)}")
        for client in self.active_clients:
            client_id = getattr(client, 'server_id', getattr(client, 'client_id', str(id(client))))
            prefix = f"{client_id}__"
            if name.startswith(prefix):
                raw_name = name[len(prefix):]
                return await client.call_tool(call_id, raw_name, args)
        raise ValueError(f"Tool '{name}' not found (called with args={args})")
