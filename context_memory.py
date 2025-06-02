from typing import Any, Dict, List, Optional, Callable
from nanoid import generate
from copy import deepcopy
import time
from tool_local_client import ToolLocalClient

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
NANOID_SIZE = 21

def nanoid(size=NANOID_SIZE):
    return generate(ALPHABET, size)

def ensure_meta(msg):
    msg = dict(msg)
    if "meta" not in msg:
        msg["meta"] = {}
    if "id" not in msg["meta"]:
        msg["meta"]["id"] = nanoid(8)
    if "created_at" not in msg["meta"]:
        msg["meta"]["created_at"] = int(time.time())
    return msg
def get_token_count(text):
    # Basit: karakter/4 ≈ token hesabı (örnek)
    return int(len(text or "") / 4)
recall_description = (
    "Some messages are trimmed in history with '[message_id: ...]'. "
    "This function returns the full content of a message when given its message_id. "
    "Use this to recall any previous message that was cut or summarized."
)

class ContextMemoryManager:
    def __init__(self, system: Optional[str] = None):
        self._messages: List[Dict[str, Any]] = []
        self._observers: List[Callable] = []
        if system is not None:
            self.set_system_message(system)

    def tool_client(self):
        client = ToolLocalClient(server_id="context-memory-manager")
        client.register_tool(
            "recall",
            self.recall,
            description=recall_description,
            parameters={
                "type": "object",
                "properties": {
                    "message_id": {
                        "type": "string",
                        "description": "The ID of the message you want to fully recall."
                    }
                },
                "required": ["message_id"]
            }
        )
        return client

    def recall(self, message_id: str) -> Optional[Dict[str, Any]]:
        """
        Returns the full message and appends a tool message with recalled_from meta.
        Also marks the original message with recalled_by.
        """
        for msg in self._messages:
            if msg.get("meta", {}).get("id") == message_id:
                return "[RECALLED FROM: " + message_id+ "] "+msg.get("content", "")
        return ""

    def get_memory_snapshot(self):
        return {
            "messages": self._messages
        }

    def add_observer(self, callback: Callable) -> None:
        self._observers.append(callback)

    def remove_observer(self, callback: Callable) -> None:
        self._observers = [cb for cb in self._observers if cb != callback]

    def _notify_observers(self):
        snapshot = self.get_memory_snapshot()
        for cb in self._observers:
            cb(snapshot)

    def set_system_message(self, content: str) -> None:
        self._messages = [m for m in self._messages if m["role"] != "system"]
        self._messages.insert(0, ensure_meta({
            "role": "system",
            "content": content.strip()
        }))
        self._notify_observers()

    def add_user_prompt(self, content: str) -> None:
        msg = {"role": "user", "content": content}
        msg = ensure_meta(msg)
        self._messages.append(msg)
        self._notify_observers()

    def add_assistant_reply(self, content: str) -> None:
        self._messages.append(ensure_meta({
            "role": "assistant",
            "content": content.strip()
        }))
        self._notify_observers()

    def add_tool_calls(self, partial_calls: Dict[int, Dict[str, Any]]) -> None:
        tool_calls = [
            {
                "type": call["type"],
                "id": call["id"],
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"],
                },
            }
            for call in partial_calls.values()
        ]
        self._messages.append(ensure_meta({
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls
        }))
        self._notify_observers()

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self._messages.append(ensure_meta({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content.strip()
        }))
        self._notify_observers()

    def get_all_messages(self) -> List[Dict[str, Any]]:
        return self._messages.copy()

    def clear(self):
        self._messages = []
        self._notify_observers()

    def set_messages(self, messages):
        self._messages = [ensure_meta(m.copy()) for m in messages]
        self._notify_observers()

    def add_message(self, msg):
        self._messages.append(ensure_meta(msg.copy()))


    def refine_view(
        self,
        token_limit: int = 60_000,
    ) -> list:
        """
        Context’i token_limit sınırına göre daraltır; 
        assistant.tool_calls ↔ tool mesajlarını daima eşli (pair) tutar.
        """
        from copy import deepcopy

        snapshot = deepcopy(self._messages)
        if not snapshot:
            return []

        # 1) System mesajı
        system_msg = snapshot[0] if snapshot[0]["role"] == "system" else None

        # 2) Hızlı index’ler
        assistant_by_id = {m["meta"]["id"]: m for m in snapshot if m["role"] == "assistant"}
        tool_msgs = [m for m in snapshot if m["role"] == "tool"]

        # tool_call_id  →  çağıran assistant_id
        tool_call_to_assistant = {
            tc["id"]: m["meta"]["id"]
            for m in assistant_by_id.values()
            if "tool_calls" in m
            for tc in m["tool_calls"]
        }

        # tool_call_id  →  tool mesajı
        tool_call_to_tool = {m.get("tool_call_id"): m for m in tool_msgs}

        # 3) En yeni tool + çağıranı
        latest_tool = max(tool_msgs, key=lambda x: x["meta"]["created_at"], default=None)
        latest_tool_call_id = latest_tool.get("tool_call_id") if latest_tool else None
        latest_assistant_id = tool_call_to_assistant.get(latest_tool_call_id) if latest_tool_call_id else None

        # 4) Yeni → eski dolaş
        result, included_ids, total_tokens = [], set(), 0
        for m in reversed(snapshot):
            mid, role = m["meta"]["id"], m["role"]

            # -- system sonradan eklenecek
            if system_msg and mid == system_msg["meta"]["id"]:
                continue

            # ------------------------------------------------------------------
            # A) EN YENİ tool çifti  (önce assistant, sonra tool)
            # ------------------------------------------------------------------
            if latest_tool and mid == latest_tool["meta"]["id"]:
                # çağıran assistant’ı ekle
                if latest_assistant_id and latest_assistant_id not in included_ids:
                    a_msg = assistant_by_id.get(latest_assistant_id)
                    if a_msg:
                        a_tok = get_token_count(a_msg["content"] or "")
                        if total_tokens + a_tok <= token_limit:
                            result.append(a_msg)
                            included_ids.add(latest_assistant_id)
                            total_tokens += a_tok
                # tool’u ekle
                t_tok = get_token_count(latest_tool["content"] or "")
                if total_tokens + t_tok <= token_limit and mid not in included_ids:
                    result.append(latest_tool)
                    included_ids.add(mid)
                    total_tokens += t_tok
                continue

            # ------------------------------------------------------------------
            # B) assistant.tool_calls  →  tüm tool’ları TAM bulabiliyorsak ekle
            # ------------------------------------------------------------------
            if role == "assistant" and "tool_calls" in m and mid not in included_ids:
                call_ids = [tc["id"] for tc in m["tool_calls"]]
                related_tools = [tool_call_to_tool.get(cid) for cid in call_ids]
                if None in related_tools:          # Eksik tool varsa partner de eklenmez
                    continue

                size = get_token_count(m["content"] or "") + \
                    sum(get_token_count(tm["content"] or "") for tm in related_tools)
                if total_tokens + size <= token_limit:
                    # assistant
                    result.append(m)
                    included_ids.add(mid)
                    total_tokens += get_token_count(m["content"] or "")
                    # pair tool’lar
                    for tm in related_tools:
                        if tm["meta"]["id"] not in included_ids:
                            result.append(tm)
                            included_ids.add(tm["meta"]["id"])
                            total_tokens += get_token_count(tm["content"] or "")
                continue

            # ------------------------------------------------------------------
            # C) tool  →  çağıran assistant context’teyse ekle
            # ------------------------------------------------------------------
            if role == "tool" and mid not in included_ids:
                a_id = tool_call_to_assistant.get(m.get("tool_call_id"))
                if a_id and a_id in included_ids:
                    t_tok = get_token_count(m["content"] or "")
                    if total_tokens + t_tok <= token_limit:
                        result.append(m)
                        included_ids.add(mid)
                        total_tokens += t_tok
                continue

            # ------------------------------------------------------------------
            # D) user veya (tool_calls içermeyen) assistant
            # ------------------------------------------------------------------
            if mid in included_ids:
                continue

            u_tok = get_token_count(m["content"] or "")
            if total_tokens + u_tok <= token_limit:
                result.append(m)
                included_ids.add(mid)
                total_tokens += u_tok

        # 5) system en başa
        if system_msg:
            result.append(system_msg)

        # 6) kronolojik sıraya geri dön
        result.sort(key=lambda x: x["meta"]["created_at"])
        return result








