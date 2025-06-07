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
    """Async OpenAI agent that supports function‑calling (tool-calls) and streaming.

    Güncellemeler:
    - `finish_reason` alanı kullanılarak modelin gerçekten bittiği (user input beklediği)
      durum güvenle tespit ediliyor.
    - Non‑stream ve stream akışlarında "user’dan yeni komut bekleniyor" işareti dönüyor.
    """

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

    # Modelin gerçekten bittiğini (user input beklediğini) anlama fonksiyonu
    @staticmethod
    def _assistant_waiting(choice) -> bool:
        """`True` dönerse model yeni içerik üretmeyecek, user’dan mesaj bekliyor."""
        fr = getattr(choice, "finish_reason", None)
        message = getattr(choice, "message", None)
        no_toolcalls = not (message.tool_calls if message else False)
        no_content = not ((message.content if message else "") or "").strip()
        return fr == "stop" and (no_toolcalls or no_content)

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
        self.memory_manager.add_user_prompt(prompt)
        tool_defs = await self.tool_client.list_tools()

        loop_guard = 0
        reply = ""

        messages = self.memory_manager.refine_view()

        while True:
            if loop_guard >= MAX_TOOL_LOOP:
                raise RuntimeError("MAX_TOOL_LOOP limit aşıldı – muhtemel sonsuz döngü")
            loop_guard += 1

            resp = await self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
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
                self.memory_manager.add_assistant_reply(buffer)
                reply += buffer
                # Non-stream’de, aynı döngüde hem content hem tool-call olamaz (genelde),
                # ama yine de döngüyü streaming ile paralel tutmak için burada kırmıyoruz.

            # ----------- Tool-call geldiyse -----------
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    call_id = tc.id
                    name = tc.function.name
                    raw_args = tc.function.arguments or ""
                    self.memory_manager.add_tool_calls({
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
                    except Exception as ex:
                        result = json.dumps({"error": "TOOL EXECUTION FAILED", "detail": str(ex)})
                        await self._notify_status({"state": AgentStatus.ERROR.value})

                    self.memory_manager.add_tool_result(
                        call_id,
                        result if isinstance(result, str) else json.dumps(result),
                    )

            # ----- Dump memory (opsiyonel, debugging için) -----
            with open("refined_memory_dump.json", "w") as f:
                json.dump(self.memory_manager.refine_view(), f, indent=2, ensure_ascii=False)
            with open("orginal_memory_dump.json", "w") as f:
                json.dump(self.memory_manager.get_memory_snapshot(), f, indent=2, ensure_ascii=False)

            # ----- Finish reason ile çıkış kararı -----
            if finish_reason == "stop":
                if not buffer.strip():
                    reply += "\n(Soru tamamlandı, lütfen yeni bir komut girin.)"
                await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed"})
                break

            # Yeni döngü için context’i güncelle
            messages = self.memory_manager.refine_view()

        return reply


    # ------------------------------------------------------------------
    # STREAM CHAIN
    # ------------------------------------------------------------------

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
        messages = self.memory_manager.refine_view()
        while True:
            if loop_guard >= MAX_TOOL_LOOP:
                raise RuntimeError("MAX_TOOL_LOOP limit aşıldı – muhtemel sonsuz döngü")
            loop_guard += 1

            tool_defs = await self.tool_client.list_tools()
            buffer: str = ""
            tool_call_happened = False
            tool_parts: Dict[int, Dict[str, Any]] = defaultdict(
                lambda: {"id": None, "type": None, "name": None, "arguments": ""}
            )
            finish_reason: Optional[str] = None

                
            stream_resp = await self.client.chat.completions.create(
                model=self.model_id,
                messages=messages,
                tools=tool_defs,
                stream=True,
            )
            tool_calls=[]
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

                # stream API: finish_reason yalnızca son chunk’ta gelir
                if chunk.choices[0].finish_reason is not None:
                    finish_reason = chunk.choices[0].finish_reason
                    print(f"!!!!!!!!!!!!!!!!!!!!!!!{finish_reason}!!!!!!!!!!!!!!!!!!!!!!!!!!!")

                # ------------- tool‑call parçalama -------------
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

            # ------------- döngü sonu karar -------------
            if buffer.strip():
                # asistan en az bir content döndürdü
                self.memory_manager.add_assistant_reply(buffer)
                await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed"})
                yield json.dumps({"type": "end", "tps": tps()})
            
            for tool_call in tool_calls:
                self.memory_manager.add_tool_calls(tool_call)
                try:
                    result = await self.tool_client.call_tool(call_id, p["name"], args_dict)
                except Exception as ex:
                    result = json.dumps({"error": "TOOL EXECUTION FAILED", "detail": str(ex)})
                    await self._notify_status({"state": AgentStatus.ERROR.value})

                self.memory_manager.add_tool_result(
                    call_id,
                    result if isinstance(result, str) else json.dumps(result),
                )
                yield json.dumps({
                    "type": "tool_result",
                    "call_id": call_id,
                    "result": result,
                    "tps": tps(),
                })
            
            messages = self.memory_manager.refine_view()
            with open("refined_memory_dump.json", "w") as f:
                json.dump(messages, f, indent=2, ensure_ascii=False)
            with open("orginal_memory_dump.json", "w") as f:
                json.dump(self.memory_manager.get_memory_snapshot(), f, indent=2, ensure_ascii=False)

            if finish_reason == "stop":
                await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed"})
                yield json.dumps({
                    "type": "end",
                    "info": "Soru tamamlandı, lütfen yeni bir komut girin.",
                    "tps": tps(),
                })
                break
        
        with open("refined_memory_dump.json", "w") as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)
    
        with open("orginal_memory_dump.json", "w") as f:
            json.dump(self.memory_manager.get_memory_snapshot(), f, indent=2, ensure_ascii=False)