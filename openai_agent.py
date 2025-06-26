from __future__ import annotations
import json
import time
from typing import Any, Dict, Optional, Callable, AsyncGenerator, Union

from openai import AsyncOpenAI
from tool_client import ToolClient
from context_memory import ContextMemory
from status_enum import AgentStatus

def dump_messages(messages, path="messages_dump.json"):
    # with open(path, "w", encoding="utf-8") as f:
    #     json.dump(messages, f, indent=2, ensure_ascii=False)
    pass

class OpenAIAgent:
    """Async OpenAI agent that supports function-calling (tool-calls) and streaming."""

    def __init__(
        self,
        api_key: str,
        base_url: str,
        model_id: str,
        tool_client: ToolClient,
        context_memory: ContextMemory,
        on_status_update: Optional[Callable[[dict], None]] = None,
        max_tool_loop=10        
    ):
        self.api_key = api_key
        self.base_url = base_url
        self.model_id = model_id
        self.tool_client = tool_client
        self.context_memory = context_memory
        self.on_status_update = on_status_update
        self.client: Optional[AsyncOpenAI] = None
        self.max_tool_loop = max_tool_loop        

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
    
    def dump(self):
        dump_messages(self.context_memory.refine(), "refined_memory_dump.json")
        dump_messages(self.context_memory.snapshot(), "orginal_memory_dump.json")
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
    # NON-STREAM CHAIN
    # ------------------------------------------------------------------
    async def ask_chain_non_stream(self, prompt: str) -> str:
        if self.client is None:
            raise RuntimeError("Agent not initialized – use `async with`")

        await self._notify_status({"state": AgentStatus.GENERATING.value, "phase": "start"})
        self.context_memory.add_user_prompt(prompt)
        tool_defs = await self.tool_client.list_tools()

        loop_guard = 0
        reply = ""

        while True:
            if loop_guard >= self.max_tool_loop:
                raise RuntimeError("MAX_TOOL_LOOP limit aşıldı – muhtemel sonsuz döngü")
            loop_guard += 1

            resp = await self.client.chat.completions.create(
                model=self.model_id,
                messages=self.context_memory.refine(),
                tools=tool_defs,
                stream=False,
            )
            choice = resp.choices[0]
            msg = choice.message
            finish_reason = getattr(choice, "finish_reason", None)

            buffer = ""
            tool_calls = []
            tool_calls_with_result = []

            # ----------- Asistan cevabı geldiyse -----------
            if msg.content and msg.content.strip():
                buffer += msg.content
                reply += buffer
                await self._notify_status({
                    "state": AgentStatus.GENERATING.value,
                    "phase": "partial_assistant",
                    "content": buffer,
                    "loop": loop_guard,
                    "max_loop": self.max_tool_loop,
                })


            # ----------- Tool-call geldiyse -----------
            if msg.tool_calls:
                for tc in msg.tool_calls:
                    call_id = tc.id
                    name = tc.function.name
                    raw_args = tc.function.arguments or ""
                    # Tool çağrısını context'e eklemeye gerek yok, topluca ekleyeceğiz
                    try:
                        args = json.loads(raw_args) if raw_args else {}
                    except json.JSONDecodeError as e:
                        print(str(e))
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
                        result = json.dumps({"error": "TOOL EXECUTION FAILED", "detail": str(ex)}, indent=2)
                        print(result)
                        await self._notify_status({"state": AgentStatus.ERROR.value, "phase": "tool_error"})

                    tool_calls_with_result.append({
                        "id": call_id,
                        "type": tc.type,
                        "name": name,
                        "arguments": raw_args,
                        "result": result if isinstance(result, str) else json.dumps(result),
                    })

            # --- Cevap ve/veya tool-calls context'e topluca ekleniyor ---
            if tool_calls_with_result:
                self.context_memory.add_assistant_reply(None, tool_calls_with_result)

            elif buffer.strip():
                self.context_memory.add_assistant_reply(buffer)
            else:
                # Asistan ne cevap ne de tool call verdi, döngüyü kır
                break

            self.dump()

            # ----- Finish reason ile çıkış kararı -----
            if finish_reason == "stop":
                if not buffer.strip():
                    reply += "\n(Soru tamamlandı, lütfen yeni bir komut girin.)"
                await self._notify_status({
                    "state": AgentStatus.DONE.value,
                    "phase": "done",
                    "loop": loop_guard,
                    "max_loop": self.max_tool_loop,
                })
                break

        return reply


    # ------------------------------------------------------------------
    # STREAM CHAIN
    # ------------------------------------------------------------------

    async def ask_chain_stream(self, prompt: str) -> AsyncGenerator[str, None]:
        if self.client is None:
            raise RuntimeError("Agent not initialized – use `async with`")

        loop_guard = 0
        
        token_count = 0
        t0 = time.perf_counter()
        tps = lambda: token_count / max(time.perf_counter() - t0, 1e-3)


        await self._notify_status({"state": AgentStatus.GENERATING.value, "phase": "start", "tps":tps(), "loop": loop_guard, "max_loop": self.max_tool_loop})
        self.context_memory.add_user_prompt(prompt)
        self.context_memory.notify_observers()

        
        from collections import defaultdict
        while True:
            if loop_guard >= self.max_tool_loop:
                raise RuntimeError("MAX_TOOL_LOOP limit aşıldı – muhtemel sonsuz döngü")
            loop_guard += 1
            await self._notify_status({"state": AgentStatus.GENERATING.value,"phase": "loop", "tps":tps(), "loop": loop_guard, "max_loop": self.max_tool_loop })            

            tool_defs = await self.tool_client.list_tools()
            buffer: str = ""
            tool_parts: Dict[int, Dict[str, Any]] = defaultdict(
                lambda: {"id": None, "type": None, "name": None, "arguments": ""}
            )
            finish_reason: Optional[str] = None

            stream_resp = await self.client.chat.completions.create(
                model=self.model_id,
                messages=self.context_memory.refine(),
                tools=tool_defs,
                stream=True,
            )
            tool_calls = []
            async for chunk in stream_resp:
                delta = chunk.choices[0].delta
                if delta.content:
                    buffer += delta.content
                    token_count += len(delta.content.split())
                    yield json.dumps({"type": "partial_assistant","content": buffer})

                if chunk.choices[0].finish_reason is not None:
                    finish_reason = chunk.choices[0].finish_reason
                    print(f"!!!!!!!!!!!!!!!!!!!!{finish_reason}!!!!!!!!!!!!!!!!!!!!!!!!!!!")

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
                                # Sadece burada parse et, aksi halde biriktirmeye devam
                                args_dict = json.loads(p["arguments"])
                            except json.JSONDecodeError:
                                # Henüz tam gelmemiş olabilir, bir sonraki chunk'ı bekle
                                continue
                    
                            tool_calls.append({
                                    "id": p["id"],
                                    "type": p["type"],
                                    "name": p["name"],
                                    "arguments": p["arguments"],
                                }
                            )
                            del tool_parts[tc.index]

            content=""
            if buffer.strip():
                content=buffer
            if len(tool_calls)==0:
                self.context_memory.add_assistant_reply(content)
                self.context_memory.notify_observers()
                await self._notify_status({"state": AgentStatus.DONE.value, "phase": "completed", "tps":tps(), "loop": loop_guard, "max_loop": self.max_tool_loop})
                yield json.dumps({"type": "end"})
            else:
                tool_calls_with_result = []

                for tool_call in tool_calls:
                    call_id = tool_call["id"]
                    name = tool_call["name"]
                    args = json.loads(tool_call["arguments"])
                    try:
                        result = await self.tool_client.call_tool(call_id, name, args)
                    except Exception as ex:
                        result = json.dumps({"error": "TOOL EXECUTION FAILED", "detail": str(ex)})
                        await self._notify_status({"state": AgentStatus.ERROR.value, "tps":tps(), "loop": loop_guard, "max_loop": self.max_tool_loop})

                    tool_calls_with_result.append({
                        "id": call_id,
                        "type": tool_call["type"],
                        "name": name,
                        "arguments": tool_call["arguments"],
                        "result": result if isinstance(result, str) else json.dumps(result),
                    })
                    # yield json.dumps({
                    #     "type": "tool_result",
                    #     "call_id": call_id,
                    #     "result": result,
                    #     "tps": tps(),
                    # })

                self.context_memory.add_assistant_reply(None, tool_calls_with_result)
                self.context_memory.notify_observers()
            await self._notify_status({"state": AgentStatus.DONE.value, "phase": "done","tps":tps(), "loop": loop_guard, "max_loop": self.max_tool_loop})
            if finish_reason == "stop":
                yield json.dumps({
                    "type": "end",
                    "info": "Soru tamamlandı, lütfen yeni bir komut girin."
                })
                await self._notify_status({"state": AgentStatus.DONE.value, "phase": "idle", "tps":tps(), "loop": loop_guard, "max_loop": self.max_tool_loop})
                break

        self.dump()
