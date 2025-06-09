import asyncio
import json
from tool_client import ToolClient
from typing import Any, Dict, List

class ToolWebSocketClient(ToolClient):
    def __init__(self, server_id: str, ws_clients):
        self.server_id = server_id
        self.ws_clients = ws_clients
        self.pending_results = {}   # call_id -> asyncio.Future
        self.dynamic_tools = {}     # tool_name -> {...}

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        pass

    async def list_tools(self) -> List[Dict[str, Any]]:
        return [
            {
                "type": "function",
                "function": {
                    "name": name,
                    "description": tool["description"],
                    "parameters": tool["parameters"],
                }
            }
            for name, tool in self.dynamic_tools.items()
        ]

    async def call_tool(self, call_id: str, tool_name: str, args: dict) -> Any:
        print("ws tool called", tool_name, args)
        tool_def = self.dynamic_tools.get(tool_name)
        if not tool_def:
            raise Exception(f"Tool {tool_name} not found")
        fut = asyncio.get_event_loop().create_future()
        self.pending_results[call_id] = fut

        msg = {
            "event": "tool_call",
            "tool": tool_name,
            "args": args,
            "call_id": call_id,
        }
        # Broadcast all ws_clients
        for ws in list(self.ws_clients):
            try:
                await ws.send_json(msg)
            except Exception:
                continue
        result = await fut
        del self.pending_results[call_id]
        return result

    async def receive_tool_result(self, call_id, result):
        fut = self.pending_results.get(call_id)
        if fut:
            fut.set_result(result)


    def register_tool(self, name: str, description: str, parameters: dict) -> None:
        """
        Registers a new tool with JSON schema validation for parameters.

        Example parameters (OpenAI function calling / JSON Schema format):
        {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query to use for searching"
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return"
                },
                "filters": {
                    "type": "object",
                    "description": "Optional filters for the search",
                    "properties": {
                        "language": {
                            "type": "string",
                            "description": "Language code for filtering results"
                        }
                    }
                },
                "tags": {
                    "type": "array",
                    "description": "A list of tags to filter by",
                    "items": {
                        "type": "string",
                        "description": "A tag to filter results"
                    }
                }
            },
            "required": ["query"]
        }

        Raises:
            ValueError: if parameters are not valid according to the schema requirements.
        """
        if name in self.dynamic_tools:
            print(f"Tool '{name}' already registered, skipping.")
            return        
        # 1. Tool name collision
        if not isinstance(name, str) or not name.strip():
            raise ValueError("Tool 'name' must be a non-empty string.")
        if name in self.dynamic_tools:
            raise ValueError(f"Tool with name '{name}' already exists!")

        # 2. Description check
        if not isinstance(description, str) or not description.strip():
            raise ValueError("Tool 'description' must be a non-empty string.")

        # 3. Parameters is a dict
        if not isinstance(parameters, dict):
            raise ValueError("Tool 'parameters' must be a dict (JSON Schema).")

        # 4. Top-level 'type'
        if "type" not in parameters:
            raise ValueError("Tool parameters must have a top-level 'type' field (must be 'object').")
        if parameters["type"] != "object":
            raise ValueError("Tool parameters top-level 'type' must be 'object'.")

        # 5. Top-level 'properties'
        if "properties" not in parameters:
            raise ValueError("Tool parameters must have a top-level 'properties' field.")
        if not isinstance(parameters["properties"], dict):
            raise ValueError("Tool parameters 'properties' must be a dict.")

        # 6. Properties must be valid
        for key, prop in parameters["properties"].items():
            if not isinstance(prop, dict):
                raise ValueError(f"Tool parameter '{key}' definition must be a dict.")
            # Each property must have type and description (most function calling UIs expect this)
            if "type" not in prop:
                raise ValueError(f"Tool parameter '{key}' must have a 'type' field (e.g., 'string', 'integer').")
            if prop["type"] not in ("string", "integer", "number", "boolean", "object", "array"):
                raise ValueError(f"Tool parameter '{key}' has unknown type '{prop['type']}'.")
            if "description" not in prop or not isinstance(prop["description"], str) or not prop["description"].strip():
                raise ValueError(f"Tool parameter '{key}' must have a non-empty 'description'.")

            # If type is 'array', 'items' must exist and be a dict
            if prop["type"] == "array":
                if "items" not in prop or not isinstance(prop["items"], dict):
                    raise ValueError(f"Tool parameter '{key}' of type 'array' must have an 'items' field (dict describing element type).")
                # Recursively check array items type/description
                items = prop["items"]
                if "type" not in items:
                    raise ValueError(f"Tool parameter '{key}' array 'items' must have a 'type'.")
                if items["type"] not in ("string", "integer", "number", "boolean", "object", "array"):
                    raise ValueError(f"Tool parameter '{key}' array 'items' has unknown type '{items['type']}'.")
                if "description" not in items or not isinstance(items["description"], str) or not items["description"].strip():
                    raise ValueError(f"Tool parameter '{key}' array 'items' must have a non-empty 'description'.")

            # If type is 'object', should ideally have nested 'properties' or 'description'
            if prop["type"] == "object":
                # Not strictly required, but warn if no description or properties
                if "properties" not in prop and ("description" not in prop or not prop["description"].strip()):
                    raise ValueError(f"Tool parameter '{key}' of type 'object' should have either 'properties' (dict) or a 'description'.")

        # 7. Optionally: check 'required' (if exists)
        if "required" in parameters and not isinstance(parameters["required"], list):
            raise ValueError("Tool parameters 'required' field must be a list of required property names.")

        self.dynamic_tools[name] = {
            "description": description,
            "parameters": parameters,
        }