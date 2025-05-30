# tool_local_client.py
from typing import Any, Dict, List, Callable
from tool_client import ToolClient
import inspect
from typing import get_type_hints
import inspect
import asyncio



def python_function_to_json_schema(fn, description=None, doc_comments=None):
    """
    Bir Python fonksiyonundan otomatik olarak OpenAI function-calling için JSON Schema üretir.
    - fn: Fonksiyon (callable)
    - description: tool açıklaması (opsiyonel, yoksa docstring kullanılır)
    - doc_comments: param açıklamaları için opsiyonel dict (ör: {"param": "desc"})
    """
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    required = []
    props = {}

    # Param açıklamaları
    doc_dict = doc_comments or {}
    docstring = (fn.__doc__ or "").strip()
    tool_description = description or docstring or fn.__name__

    for name, param in sig.parameters.items():
        param_type = hints.get(name, str)  # type hint varsa al, yoksa string varsay
        if param.default is inspect.Parameter.empty:
            required.append(name)
        if param_type is int:
            typ = "integer"
        elif param_type is float:
            typ = "number"
        elif param_type is bool:
            typ = "boolean"
        else:
            typ = "string"
        param_desc = doc_dict.get(name, "")
        props[name] = {
            "type": typ,
        }
        if param_desc:
            props[name]["description"] = param_desc
        if param.default is not inspect.Parameter.empty:
            props[name]["default"] = param.default

    schema = {
        "type": "object",
        "properties": props,
        "required": required,
    }
    return tool_description, schema

class ToolLocalClient(ToolClient):
    """
    Lokal Python fonksiyonlarını OpenAI-compatible 'tool' olarak expose eden client.
    """

    def __init__(self, server_id: str = "local"):
        self.server_id = server_id
        # tool_name -> { function, description, parameters }
        self.local_tools: Dict[str, Dict[str, Any]] = {}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    def register_tool(self, name: str, function: Callable, description: str, parameters: dict):
        """
        Bir Python fonksiyonunu tool olarak kaydet.
        - name: string, tool fonksiyon adı
        - function: callable
        - description: kısa açıklama
        - parameters: OpenAI function calling JSON Schema (dict)
        """
        if not callable(function):
            raise ValueError("Function must be callable")
        if not isinstance(parameters, dict):
            raise ValueError("Parameters must be a dict (OpenAI JSON Schema format)")
        if name in self.local_tools:
            raise ValueError(f"Tool '{name}' already registered.")
        self.local_tools[name] = {
            "function": function,
            "description": description,
            "parameters": parameters,
        }

    def register_tool_auto(self, fn, name=None, description=None, doc_comments=None):
        tool_name = name or fn.__name__
        desc, params_schema = python_function_to_json_schema(fn, description, doc_comments)
        self.register_tool(tool_name, fn, desc, params_schema)



    async def list_tools(self) -> List[Dict[str, Any]]:
        """
        Tool listesini OpenAI-compatible olarak döndürür.
        """
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": t["description"],
                    "parameters": t["parameters"],
                }
            }
            for name, t in self.local_tools.items()
        ]

    async def call_tool(self, call_id: str, tool_name: str, args: Dict[str, Any]) -> Any:
        if tool_name not in self.local_tools:
            raise Exception(f"Tool {tool_name} not registered.")
        fn = self.local_tools[tool_name]["function"]
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
