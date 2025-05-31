from __future__ import annotations
import json
import time
from typing import Any, Dict, Optional, Callable, AsyncGenerator, Union

from openai import AsyncOpenAI
from tool_client import ToolClient
from context_memory import ContextMemoryManager
from status_enum import AgentStatus

class OpenAIAgent:
    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_id: str,
        tool_client: ToolClient,
        memory_manager: ContextMemoryManager,
        on_status_update: Optional[Callable[[dict], None]] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model_id = model_id
        self.tool_client = tool_client
        self.memory_manager = memory_manager
        self.on_status_update = on_status_update
        self.client: Optional[AsyncOpenAI] = None

    async def __aenter__(self) -> "OpenAIAgent":
        self.client = AsyncOpenAI(
            api_key=self.api_key,
            base_url=self.base_url,
        )
        return self

    async def __aexit__(self, *_):
        if self.client and hasattr(self.client, "aclose"):
            await self.client.aclose()
        self.client = None

    async def _notify_status(self, status: dict):
        if self.on_status_update:
            maybe_coro = self.on_status_update(status)
            if hasattr(maybe_coro, "__await__"):
                await maybe_coro

    def _save_context(self):
        try:
            with open("context_refined.json", "w", encoding="utf-8") as f:
                json.dump(
                    self.memory_manager.get_all_messages(),
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            print(f"⚠️ Failed to save context: {e}")

    def _parse_tool_arguments(self, call):
        arguments = call.get("arguments", "")
        if not arguments:
            return {}
        if isinstance(arguments, dict):
            return arguments
        try:
            return json.loads(arguments)
        except Exception as e:
            print("[WARN] Tool-call argümantasyon hatası:", e, "| Raw arguments:", repr(arguments))
            return {}

    async def ask(
        self,
        prompt: str,
        stream: bool = False,
    ) -> Union[str, AsyncGenerator[str, None]]:
        if stream:
            return self.ask_stream(prompt)
        else:
            return await self.ask_non_stream(prompt)

    async def ask_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        if self.client is None:
            raise RuntimeError("Agent not initialized – use `async with`")
        self.memory_manager.add_user_prompt(prompt)
        tool_defs = await self.tool_client.list_tools()
        self.memory_manager.retain_last_tool_call_pairs(3)
        messages = self.memory_manager.get_all_messages()

        buffer = ""
        ongoing: Dict[int, Dict[str, Any]] = {}
        token_count = 0
        start_time = time.perf_counter()

        def current_tps():
            elapsed = max(time.perf_counter() - start_time, 0.001)
            return token_count / elapsed

        try:
            await self._notify_status({"state": AgentStatus.GENERATING.value, "phase": "start"})
            stream_resp = await self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                tools=tool_defs,
                stream=True,
            )

            async for chunk in stream_resp:
                delta = chunk.choices[0].delta
                if getattr(delta, "content", None):
                    buffer += delta.content
                    token_count += len(delta.content.split())
                    yield json.dumps({
                        "type": "partial_assistant",
                        "content": buffer,
                        "tps": current_tps()
                    })

                if delta.tool_calls:
                    await self._notify_status({"state": AgentStatus.TOOL_CALLING.value, "phase": "tools"})
                    for tc in delta.tool_calls:
                        idx = tc.index
                        entry = ongoing.setdefault(
                            idx,
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "name": getattr(tc.function, "name", None),
                                "arguments": "",
                            },
                        )
                        entry["id"] = entry["id"] or tc.id
                        entry["type"] = entry["type"] or tc.type
                        entry["name"] = entry["name"] or getattr(tc.function, "name", None)
                        entry["arguments"] += getattr(tc.function, "arguments", "")
                    yield json.dumps({
                        "type": "tool_call",
                        "calls": ongoing,
                        "tps": current_tps()
                    })

            if buffer.strip():
                self.memory_manager.add_assistant_reply(buffer)

            if ongoing:
                for call in ongoing.values():
                    if not (call["id"] and call["name"] and call["type"]):
                        continue
                    args = self._parse_tool_arguments(call)
                    if not args:
                        continue
                    self.memory_manager.add_tool_calls({call["id"]: call})
                    try:
                        result = await self.tool_client.call_tool(call["id"], call["name"], args)
                        if not isinstance(result, str):
                            result = json.dumps(result, ensure_ascii=False)
                    except Exception as ex:
                        await self._notify_status({"state": AgentStatus.ERROR.value})
                        result = json.dumps({"error": "TOOL EXECUTION FAILED", "detail": str(ex)})
                    self.memory_manager.add_tool_result(call["id"], result)
                    yield json.dumps({
                        "type": "tool_result",
                        "call_id": call["id"],
                        "result": result,
                        "tps": current_tps()
                    })

            tps = current_tps()
            await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed"})
            yield json.dumps({"type": "end", "tps": tps})

        except Exception as err:
            await self._notify_status({"state": AgentStatus.ERROR.value})
            yield json.dumps({"type": "end", "error": str(err)})

    async def ask_non_stream(self, prompt: str) -> str:
        if self.client is None:
            raise RuntimeError("Agent not initialized – use `async with`")
        self.memory_manager.add_user_prompt(prompt)
        tool_defs = await self.tool_client.list_tools()
        self.memory_manager.retain_last_tool_call_pairs(3)
        messages = self.memory_manager.get_all_messages()

        try:
            await self._notify_status({"state": AgentStatus.GENERATING.value, "phase": "start"})
            resp = await self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                tools=tool_defs,
                stream=False,
            )

            full_reply = ""
            ongoing: Dict[int, Dict[str, Any]] = {}

            for choice in resp.choices:
                msg = choice.message
                if msg.content:
                    full_reply += msg.content
                if msg.tool_calls:
                    await self._notify_status({"state": AgentStatus.TOOL_CALLING.value, "phase": "tools"})
                    for idx,tc in msg.tool_calls:
                        entry = ongoing.setdefault(
                            idx,
                            {
                                "id": tc.id,
                                "type": tc.type,
                                "name": tc.function.name,
                                "arguments": "",
                            },
                        )
                        entry["arguments"] += tc.function.arguments or ""

            if full_reply.strip():
                self.memory_manager.add_assistant_reply(full_reply)

            if ongoing:
                for call in ongoing.values():
                    if not (call["id"] and call["name"] and call["type"]):
                        continue
                    args = self._parse_tool_arguments(call)
                    if not args:
                        continue
                    self.memory_manager.add_tool_calls({call["id"]: call})
                    try:
                        result = await self.tool_client.call_tool(call["id"], call["name"], args)
                        if not isinstance(result, str):
                            result = json.dumps(result, ensure_ascii=False)
                    except Exception as ex:
                        await self._notify_status({"state": AgentStatus.ERROR.value})
                        result = json.dumps({"error": "TOOL EXECUTION FAILED", "detail": str(ex)})
                    self.memory_manager.add_tool_result(call["id"], result)

            await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed"})
            self._save_context()
            return full_reply
        except Exception as err:
            await self._notify_status({"state": AgentStatus.ERROR.value})
            raise
