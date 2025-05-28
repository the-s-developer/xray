from __future__ import annotations
import json
from typing import Any, Dict, Optional

from openai import AsyncOpenAI
from tool_client import ToolClient
from context_memory import ContextMemoryManager

class OpenAIAgent:
    """OpenAI API wrapper with session-aware tool routing."""

    def __init__(
        self,
        api_key: str,
    ) -> None:
        self.api_key = api_key
        self.client: Optional[AsyncOpenAI] = None

    async def __aenter__(self) -> "OpenAIAgent":
        self.client = AsyncOpenAI(api_key=self.api_key)
        return self

    async def __aexit__(self, *args):
        if self.client and hasattr(self.client, "aclose"):
            await self.client.aclose()
        self.client = None

    async def ask(
        self,
        tool_client: ToolClient,
        prompt: str,
        memory_manager: ContextMemoryManager,
        model: str = "gpt-4.1-nano",
    ) -> str:
        """
        OpenAI ile, tool ve hafıza kullanarak tek seferde chat cevabı alır.
        Streaming yok!
        """
        if self.client is None:
            raise RuntimeError("Agent not initialized – use `async with`")

        memory_manager.add_user_prompt(prompt)
        tool_defs = await tool_client.list_tools()

        while True:
            messages = memory_manager.get_all_messages()
            response = await self.client.chat.completions.create(
                model=model,
                messages=messages,
                tools=tool_defs,
                stream=False,
            )

            full_response = ""
            partial_calls: Dict[str, Dict[str, Any]] = {}

            for choice in getattr(response, 'choices', []):
                msg = getattr(choice, 'message', None)
                if msg and getattr(msg, 'content', None):
                    full_response += msg.content

                # Tool call varsa topla
                if hasattr(msg, "tool_calls") and msg.tool_calls:
                    for tc in msg.tool_calls:
                        entry = partial_calls.setdefault(
                            str(tc.id),
                            {
                                "id": str(tc.id),
                                "type": tc.type,
                                "name": tc.function.name,
                                "arguments": "",
                            }
                        )
                        entry["arguments"] += tc.function.arguments or ""

            if isinstance(full_response, str) and full_response.strip():
                memory_manager.add_assistant_reply(full_response)
            elif isinstance(full_response, dict):
                memory_manager.add_assistant_reply(json.dumps(full_response, ensure_ascii=False))

            if not partial_calls:
                self._save_context(memory_manager)
                return full_response

            # Sadece ilk tool çağrısını işle (chain-of-thought için döngü)
            first_call_id = next(iter(partial_calls))
            first_call = partial_calls[first_call_id]
            memory_manager.add_tool_calls({first_call_id: first_call})

            try:
                args = {}
                if first_call["arguments"]:
                    try:
                        args = json.loads(first_call["arguments"])
                    except Exception as e:
                        print(f"⚠️ JSON decode error: {e} (input: {first_call['arguments']!r})")
                        args = {}
                result = await tool_client.call_tool(first_call_id, first_call["name"], args)
                # *** Burada tip kontrolü ***
                if not isinstance(result, str):
                    result = json.dumps(result, ensure_ascii=False)
                memory_manager.add_tool_result(first_call_id, result)
            except Exception as ex:
                print(f"⚠️ Tool execution failed: {ex}")
                error_json = json.dumps({
                    "error": "TOOL EXECUTION FAILED",
                    "detail": str(ex)
                })
                memory_manager.add_tool_result(first_call["id"], error_json)

            self._save_context(memory_manager)

    def _save_context(self, memory_manager: ContextMemoryManager):
        """İsteğe bağlı: context'i diske yaz."""
        try:
            with open("context_refined.json", "w", encoding="utf-8") as f:
                json.dump(memory_manager.get_all_messages(), f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"⚠️ Failed to save context: {e}")
    async def list_models(self) -> list[dict]:
            """OpenAI'dan erişilebilir modelleri çeker (kendi API anahtarın ile)."""
            if self.client is None:
                raise RuntimeError("Agent not initialized – use `async with`")

            models = await self.client.models.list()
            model_list = []
            for model in models.data:
                # Sadece GPT içerenleri göstermek için:
                if "gpt" in model.id:
                    model_list.append({
                        "value": model.id,
                        "label": model.id.replace("-", " ").upper()
                    })
            return model_list