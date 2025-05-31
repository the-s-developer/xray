from __future__ import annotations
import json
import time
from typing import Any, Dict, Optional, Callable, AsyncGenerator, Union

from openai import AsyncOpenAI
from tool_client import ToolClient
from context_memory import ContextMemoryManager
from status_enum import AgentStatus

MAX_TOOL_LOOP = 10  # Maximum number of tool calls in a single ask operation

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
            return self.ask_chain_stream(prompt)
        else:
            return await self.ask_chain_non_stream(prompt)

    async def ask_chain_non_stream(self, prompt: str) -> str:
        if self.client is None:
            raise RuntimeError("Agent not initialized – use `async with`")

        await self._notify_status({"state": AgentStatus.GENERATING.value, "phase": "start"})
        self.memory_manager.add_user_prompt(prompt)
        tool_defs  = await self.tool_client.list_tools()
        loop_guard = 0
        reply      = ""

        while True:
            if loop_guard >= MAX_TOOL_LOOP:
                raise RuntimeError("MAX_TOOL_LOOP limit aşıldı – muhtemel sonsuz döngü")
            loop_guard += 1

            self.memory_manager.retain_last_tool_call_pairs(3)
            messages = self.memory_manager.get_all_messages()

            resp = await self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                tools=tool_defs,
                stream=False,
            )
            msg = resp.choices[0].message

            # --- asistan cevabı geldiyse ---
            if msg.content:
                self.memory_manager.add_assistant_reply(msg.content)
                reply += msg.content
                break

            # --- tool-call geldiyse ---
            if msg.tool_calls:
                tc       = msg.tool_calls[0]        # sadece ilkini işliyoruz
                raw_args = tc.function.arguments or ""
                self.memory_manager.add_tool_calls({
                    tc.id: {
                        "id":        tc.id,
                        "type":      tc.type,
                        "name":      tc.function.name,
                        "arguments": raw_args      # *** string olarak ***
                    }
                })

                try:
                    args = json.loads(raw_args) if raw_args else {}
                except json.JSONDecodeError:
                    args = {}
                    print("⚠️ JSON decode error – args boş alındı")

                try:
                    result = await self.tool_client.call_tool(tc.id, tc.function.name, args)
                except Exception as ex:
                    result = json.dumps({"error": "TOOL EXECUTION FAILED", "detail": str(ex)})
                    await self._notify_status({"state": AgentStatus.ERROR.value})

                self.memory_manager.add_tool_result(tc.id, result if isinstance(result, str) else json.dumps(result))
                continue     # yeni LLM çağrısı
            break            # ne cevap ne tool-call

        await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed"})
        self._save_context()
        return reply


    # ---------- STREAM ------------------------------------------------------
    async def ask_chain_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        if self.client is None:
            raise RuntimeError("Agent not initialized – use `async with`")

        await self._notify_status({"state": AgentStatus.GENERATING.value, "phase": "start"})
        self.memory_manager.add_user_prompt(prompt)

        token_count = 0
        t0 = time.perf_counter()
        tps = lambda: token_count / max(time.perf_counter() - t0, 1e-3)

        from collections import defaultdict
        loop_guard = 0

        while True:
            if loop_guard >= MAX_TOOL_LOOP:
                raise RuntimeError("MAX_TOOL_LOOP limit aşıldı – muhtemel sonsuz döngü")
            loop_guard += 1

            tool_defs = await self.tool_client.list_tools()
            buffer    = ""
            tool_call_happened = False
            tool_parts: dict[int, dict[str, Any]] = defaultdict(
                lambda: {"id": None, "type": None, "name": None, "arguments": ""}
            )

            self.memory_manager.retain_last_tool_call_pairs(3)
            messages = self.memory_manager.get_all_messages()

            stream_resp = await self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                tools=tool_defs,
                stream=True,
            )

            async for chunk in stream_resp:
                delta = chunk.choices[0].delta

                # --- asistan content ---
                if delta.content:
                    buffer += delta.content
                    token_count += len(delta.content.split())
                    yield json.dumps({"type": "partial_assistant", "content": buffer, "tps": tps()})

                # --- tool-call parçaları ---
                if delta.tool_calls:
                    for tc in delta.tool_calls:
                        p = tool_parts[tc.index]
                        if tc.id:               p["id"]   = tc.id
                        if tc.type:             p["type"] = tc.type
                        if tc.function:
                            if tc.function.name:       p["name"] = tc.function.name
                            if tc.function.arguments:  p["arguments"] += tc.function.arguments

                        # tamamlandı mı?
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

                            # belleğe string arg ile ekle
                            self.memory_manager.add_tool_calls({
                                call_id: {
                                    "id": call_id,
                                    "type": p["type"],
                                    "name": p["name"],
                                    "arguments": p["arguments"]
                                }
                            })
                            try:
                                result = await self.tool_client.call_tool(call_id, p["name"], args_dict)
                            except Exception as ex:
                                result = json.dumps({"error": "TOOL EXECUTION FAILED", "detail": str(ex)})
                                await self._notify_status({"state": AgentStatus.ERROR.value})

                            self.memory_manager.add_tool_result(call_id, result if isinstance(result, str) else json.dumps(result))
                            yield json.dumps({"type": "tool_result", "call_id": call_id, "result": result, "tps": tps()})
                            del tool_parts[tc.index]
                            tool_call_happened = True

            # --- döngü sonu karar ---
            if buffer.strip():
                self.memory_manager.add_assistant_reply(buffer)
                await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed"})
                self._save_context()
                yield json.dumps({"type": "end", "tps": tps()})
                break
            elif tool_call_happened:
                continue
            else:
                await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed"})
                self._save_context()
                yield json.dumps({"type": "end", "tps": tps()})
                break



