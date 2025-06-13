from typing import  Dict, List
import inspect
from typing import get_type_hints
import inspect

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

def python_function_to_json_schema(fn, fn_name = None, description=None, doc_comments=None):
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
            "name": fn_name or fn.__name__,
            "description": tool_description,
            "parameters": schema,
            "strict": True
        }
    }
    return function_def