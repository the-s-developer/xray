from typing import Dict, Any, List, Optional
from contextlib import AsyncExitStack
from tool_client import ToolClient

class ToolRouter(ToolClient):
    """
    Birden fazla ToolClient'i (lokal/remote fark etmez) 
    tek noktadan yönetip OpenAI tool çağrılarına uygun API sunar.
    """

    def __init__(self, clients: Optional[List[ToolClient]] = None):
        self.clients: List[ToolClient] = clients or []
        self._stack: AsyncExitStack = AsyncExitStack()
        self.active_clients: List[ToolClient] = []

    async def __aenter__(self) -> "ToolRouter":
        self.active_clients = []
        for client in self.clients:
            active_client = await self._stack.enter_async_context(client)
            self.active_clients.append(active_client)
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        await self._stack.aclose()
        self.active_clients = []

    async def list_tools(self) -> List[Dict[str, Any]]:
        """Tüm client’lardan tool listesini topla, isimleri prefix’le."""
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
        """
        Prefix’ine göre doğru ToolClient’e yönlendir.
        """
        if not isinstance(name, str) or not name:
            raise ValueError(f"Tool name must be a non-empty string, got: {repr(name)}")
        for client in self.active_clients:
            client_id = getattr(client, 'server_id', getattr(client, 'client_id', str(id(client))))
            prefix = f"{client_id}__"
            if name.startswith(prefix):
                raw_name = name[len(prefix):]
                return await client.call_tool(call_id, raw_name, args)
        raise ValueError(f"Tool '{name}' not found (called with args={args})")
