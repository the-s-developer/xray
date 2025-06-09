from __future__ import annotations
import json
import time
from typing import Any, Dict, Optional, Callable, AsyncGenerator, Union, List

from openai import AsyncOpenAI
from tool_client import ToolClient
from context_memory import ContextMemory
from context_processor import ContextProcessor
from status_enum import AgentStatus

MAX_TOOL_LOOP = 10  # Maximum number of tool calls in a single ask operation

def dump_messages(messages, path="messages_dump.json"):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(messages, f, indent=2, ensure_ascii=False)

class OpenAIAgent:
    """Async OpenAI agent that supports function‑calling (tool-calls) and streaming."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_id: str,
        tool_client: ToolClient,
        context_memory: ContextMemory,
        on_status_update: Optional[Callable[[dict], None]] = None,
        context_processors: Optional[List[ContextProcessor]] = None,
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model_id = model_id
        self.tool_client = tool_client
        self.context_memory = context_memory
        self.on_status_update = on_status_update
        self.client: Optional[AsyncOpenAI] = None
        self.context_processors = context_processors or []

    # ---------------------------------------------------------------------
    # Lifecycle helpers
    # ---------------------------------------------------------------------

    async def __aenter__(self) -> "OpenAIAgent":
        self.client = AsyncOpenAI(api_key=self.api_key, base_url=self.base_url)
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

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_tool_arguments(call):
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

    @staticmethod
    def _assistant_waiting(choice) -> bool:
        """Modelin gerçekten bittiğini (user input beklediğini) anlama fonksiyonu."""
        fr = getattr(choice, "finish_reason", None)
        message = getattr(choice, "message", None)
        no_toolcalls = not (message.tool_calls if message else False)
        no_content = not ((message.content if message else "") or "").strip()
        return fr == "stop" and (no_toolcalls or no_content)
    
    def _refine(self):
        messages = self.context_memory.snapshot()
        for processor in self.context_processors:
            messages = processor.refine(messages)
        return messages

    # ------------------------------------------------------------------
    # Public ask entrypoint
    # ------------------------------------------------------------------

    async def ask(
        self,
        prompt: str,
        stream: bool = False,
    ) -> Union[str, AsyncGenerator[str, None]]:
        if stream:
            return self.ask_chain_stream(prompt)
        return await self.ask_chain_non_stream(prompt)

    # ------------------------------------------------------------------
    # NON‑STREAM CHAIN
    # ------------------------------------------------------------------

    async def ask_chain_non_stream(self, prompt: str) -> str:
        if self.client is None:
            raise RuntimeError("Agent not initialized – use `async with`")

        await self._notify_status({"state": AgentStatus.GENERATING.value, "phase": "start"})
        self.context_memory.add_user_prompt(prompt)
        tool_defs = await self.tool_client.list_tools()

        loop_guard = 0
        reply = ""

        refined_messages = self._refine()

        while True:
            if loop_guard >= MAX_TOOL_LOOP:
                raise RuntimeError("MAX_TOOL_LOOP limit aşıldı – muhtemel sonsuz döngü")
            loop_guard += 1

            resp = await self.client.chat.completions.create(
                model=self.model_id,
                messages=refined_messages,
                tools=tool_defs,
                stream=False,
            )
            choice = resp.choices[0]
            msg = choice.message
            finish_reason = getattr(choice, "finish_reason", None)

            buffer = ""
            tool_calls = []

            # ----------- Asistan cevabı geldiyse -----------
            if msg.content and msg.content.strip():
                buffer += msg.content
                self.context_memory.add_assistant_reply(buffer)
                reply += buffer
                await self._notify_status({
                    "state": AgentStatus.GENERATING.value,
                    "phase": "partial_assistant",
                    "content": buffer,
                })

            # ----------- Tool-call geldiyse -----------
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    call_id = tc.id
                    name = tc.function.name
                    raw_args = tc.function.arguments or ""
                    self.context_memory.add_tool_calls({
                        call_id: {
                            "id": call_id,
                            "type": tc.type,
                            "name": name,
                            "arguments": raw_args,
                        }
                    })
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError:
                        args = {}
                    try:
                        result = await self.tool_client.call_tool(call_id, name, args)
                        await self._notify_status({
                            "state": AgentStatus.TOOL.value,
                            "phase": "tool_result",
                            "call_id": call_id,
                            "result": result,
                        })
                    except Exception as ex:
                        result = json.dumps({"error": "TOOL EXECUTION FAILED", "detail": str(ex)})
                        await self._notify_status({"state": AgentStatus.ERROR.value, "phase": "tool_error"})

                    self.context_memory.add_tool_result(
                        call_id,
                        result if isinstance(result, str) else json.dumps(result),
                    )

            # --- Dump memory for debugging ---
            dump_messages(refined_messages, "refined_memory_dump.json")
            dump_messages(self.context_memory.snapshot(), "orginal_memory_dump.json")

            # ----- Finish reason ile çıkış kararı -----
            if finish_reason == "stop":
                if not buffer.strip():
                    reply += "\n(Soru tamamlandı, lütfen yeni bir komut girin.)"
                await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed"})
                break

            refined_messages = self._refine()

        return reply

    # ------------------------------------------------------------------
    # STREAM CHAIN
    # ------------------------------------------------------------------

    async def ask_chain_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        if self.client is None:
            raise RuntimeError("Agent not initialized – use `async with`")

        await self._notify_status({"state": AgentStatus.GENERATING.value, "phase": "start"})
        self.context_memory.add_user_prompt(prompt)

        token_count = 0
        t0 = time.perf_counter()
        tps = lambda: token_count / max(time.perf_counter() - t0, 1e-3)

        from collections import defaultdict
        loop_guard = 0
        refined_messages = self._refine()
        while True:
            if loop_guard >= MAX_TOOL_LOOP:
                raise RuntimeError("MAX_TOOL_LOOP limit aşıldı – muhtemel sonsuz döngü")
            loop_guard += 1

            tool_defs = await self.tool_client.list_tools()
            buffer: str = ""
            tool_parts: Dict[int, Dict[str, Any]] = defaultdict(
                lambda: {"id": None, "type": None, "name": None, "arguments": ""}
            )
            finish_reason: Optional[str] = None

            stream_resp = await self.client.chat.completions.create(
                model=self.model_id,
                messages=refined_messages,
                tools=tool_defs,
                stream=True,
            )
            tool_calls = []
            async for chunk in stream_resp:
                delta = chunk.choices[0].delta
                if delta.content:
                    buffer += delta.content
                    token_count += len(delta.content.split())
                    yield json.dumps({
                        "type": "partial_assistant",
                        "content": buffer,
                        "tps": tps(),
                    })

                if chunk.choices[0].finish_reason is not None:
                    finish_reason = chunk.choices[0].finish_reason

                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        p = tool_parts[tc.index]
                        if tc.id:
                            p["id"] = tc.id
                        if tc.type:
                            p["type"] = tc.type
                        if tc.function:
                            if tc.function.name:
                                p["name"] = tc.function.name
                            if tc.function.arguments:
                                p["arguments"] += tc.function.arguments

                        args_ready = (
                            p["arguments"].startswith("{")
                            and p["arguments"].rstrip().endswith("}")
                        )
                        if p["id"] and p["type"] and p["name"] and args_ready:
                            try:
                                args_dict = json.loads(p["arguments"])
                            except json.JSONDecodeError:
                                args_dict = {}
                            call_id = p["id"]
                            tool_calls.append({
                                call_id: {
                                    "id": call_id,
                                    "type": p["type"],
                                    "name": p["name"],
                                    "arguments": p["arguments"],
                                }
                            })
                            del tool_parts[tc.index]

            if buffer.strip():
                self.context_memory.add_assistant_reply(buffer)
                await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed"})
                yield json.dumps({"type": "end", "tps": tps()})

            for tool_call in tool_calls:
                self.context_memory.add_tool_calls(tool_call)
                try:
                    result = await self.tool_client.call_tool(call_id, p["name"], args_dict)
                except Exception as ex:
                    result = json.dumps({"error": "TOOL EXECUTION FAILED", "detail": str(ex)})
                    await self._notify_status({"state": AgentStatus.ERROR.value})

                self.context_memory.add_tool_result(
                    call_id,
                    result if isinstance(result, str) else json.dumps(result),
                )
                yield json.dumps({
                    "type": "tool_result",
                    "call_id": call_id,
                    "result": result,
                    "tps": tps(),
                })

            refined_messages = self._refine()
            dump_messages(refined_messages, "refined_memory_dump.json")
            dump_messages(self.context_memory.snapshot(), "orginal_memory_dump.json")

            if finish_reason == "stop":
                await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed"})
                yield json.dumps({
                    "type": "end",
                    "info": "Soru tamamlandı, lütfen yeni bir komut girin.",
                    "tps": tps(),
                })
                break

        dump_messages(refined_messages, "refined_memory_dump.json")
        dump_messages(self.context_memory.snapshot(), "orginal_memory_dump.json")
