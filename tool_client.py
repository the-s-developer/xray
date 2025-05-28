from abc import ABC, abstractmethod
from typing import Any, Dict, List

class ToolClient(ABC):
    @abstractmethod
    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        List the available tools.
        """
        pass

    @abstractmethod
    async def call_tool(self,call_id: str, tool_name: str, args: Dict[str, Any]) -> Any:
        """
        Call a specific tool by name with arguments.
        """
        pass
