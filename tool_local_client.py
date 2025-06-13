# tool_local_client.py
from typing import Any, Dict, List, Callable
from tool_client import ToolClient
import inspect
from typing import get_type_hints
import inspect
import asyncio
from openai_tool_utils import python_function_to_json_schema


from typing import get_origin, get_args, Union
import inspect

class ToolLocalClient(ToolClient):
    """
    Lokal Python fonksiyonlarını OpenAI-compatible 'tool' olarak expose eden client.
    """

    def __init__(self, server_id: str = "local"):
        self.server_id = server_id
        self.local_tools: Dict[str, Dict[str, Any]] = {}
        self.python_functions: Dict[str, Callable] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    def register_tool_auto(self, fn, name=None, description=None, doc_comments=None):
        function_schema = python_function_to_json_schema(fn, description=description,doc_comments = doc_comments)
        tool_name = name or fn.__name__
        self.local_tools[tool_name] = function_schema
        self.python_functions[tool_name] = fn
        print(f"Registered tool: {tool_name}\nSchema: {function_schema}\n")

    async def list_tools(self) -> List[Dict[str, Any]]:
        return [schema for schema in self.local_tools.values()]

    async def call_tool(self, call_id: str, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name not in self.python_functions:
            raise Exception(f"Tool {tool_name} not registered.")
        fn = self.python_functions[tool_name]
        if inspect.iscoroutinefunction(fn):
            return await fn(**args)
        else:
            return fn(**args)


# ÖRNEK KULLANIM (test)
if __name__ == "__main__":
    import asyncio

    def add_numbers(a: int, b: int) -> int:
        return a + b

    parameters = {
        "type": "object",
        "properties": {
            "a": {"type": "integer", "description": "First number"},
            "b": {"type": "integer", "description": "Second number"},
        },
        "required": ["a", "b"],
    }

    async def test():
        client = ToolLocalClient()
        client.register_tool(
            "add_numbers", add_numbers,
            description="Adds two numbers.",
            parameters=parameters
        )

        tools = await client.list_tools()
        print("TOOL DEFINITIONS:", tools)
        res = await client.call_tool("testid", "add_numbers", {"a": 10, "b": 22})
        print("CALL RESULT:", res)

    asyncio.run(test())
