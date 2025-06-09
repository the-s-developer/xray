# tool_local_client.py
from typing import Any, Dict, List, Callable
from tool_client import ToolClient
import inspect
from typing import get_type_hints
import inspect
import asyncio


from typing import get_origin, get_args, Union
import inspect

def type_to_schema(param_type):
    origin = get_origin(param_type)
    args = get_args(param_type)
    # Optional (Union[..., None]) tespiti
    if origin is Union and type(None) in args:
        non_none = [a for a in args if a is not type(None)][0]
        s = type_to_schema(non_none)
        # OpenAI uyumlu: ["string", "null"]
        if "type" in s:
            s["type"] = [s["type"], "null"]
        return s
    if param_type is int:
        return {"type": "integer"}
    if param_type is float:
        return {"type": "number"}
    if param_type is bool:
        return {"type": "boolean"}
    if param_type is str:
        return {"type": "string"}
    if origin is list or origin is List:
        item_type = args[0] if args else str
        return {"type": "array", "items": type_to_schema(item_type)}
    if origin is dict or origin is Dict:
        val_type = args[1] if len(args) > 1 else str
        return {"type": "object", "additionalProperties": type_to_schema(val_type)}
    return {"type": "string"} # fallback

def python_function_to_json_schema(fn, description=None, doc_comments=None):
    sig = inspect.signature(fn)
    hints = get_type_hints(fn)
    required = []
    props = {}

    doc_dict = doc_comments or {}
    docstring = (fn.__doc__ or "").strip()
    tool_description = description or docstring or fn.__name__

    for name, param in sig.parameters.items():
        param_type = hints.get(name, str)
        # Optional tespiti için yukarıdaki fonksiyon zaten tip olarak ["string", "null"] vs. döndürür
        # Sadece default'u None ise required'a ekleme
        if param.default is inspect.Parameter.empty:
            required.append(name)
        prop_schema = type_to_schema(param_type)
        param_desc = doc_dict.get(name, "")
        props[name] = prop_schema
        if param_desc:
            props[name]["description"] = param_desc
        if param.default is not inspect.Parameter.empty and param.default is not None:
            props[name]["default"] = param.default

    schema = {
        "type": "object",
        "properties": props,
        "required": required,
        "additionalProperties": False,
    }
    # Yeni OpenAI formatında:
    function_def = {
        "type": "function",
        "function": {
            "name": fn.__name__,
            "description": tool_description,
            "parameters": schema,
            "strict": True
        }
    }
    return function_def

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
        function_schema = python_function_to_json_schema(fn, description, doc_comments)
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
