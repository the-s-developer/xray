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
        context_size: int = 60_000,
        enable_trace: bool = True,
    ) -> list:
        def trace(*args):
            if enable_trace:
                print("[TRACE]", *args)

        from copy import deepcopy

        snapshot = deepcopy(self._messages)
        if not snapshot:
            trace("Snapshot boş.")
            return []

        # System mesajı varsa ayır
        system_msg = snapshot[0] if snapshot[0]["role"] == "system" else None
        if system_msg:
            trace("System mesajı ayrıldı:", (str(system_msg.get("content") or ""))[:60])
            non_system_msgs = snapshot[1:]
        else:
            non_system_msgs = snapshot[:]

        # Mesajları gruplara ayır: her bir user mesajı ve ona cevap olan assistant (ve varsa tool)
        groups = []
        idx = 0
        while idx < len(non_system_msgs):
            msg = non_system_msgs[idx]
            if msg["role"] == "user":
                group = [msg]
                # Sonraki asistan mesajı bu user'a cevap mı bak (sıradaki ise)
                if idx + 1 < len(non_system_msgs):
                    next_msg = non_system_msgs[idx + 1]
                    if next_msg["role"] == "assistant":
                        group.append(next_msg)
                        # Eğer tool_calls varsa pair'leri de ekle
                        if "tool_calls" in next_msg:
                            tools = []
                            for tc in next_msg["tool_calls"]:
                                # O tool_call_id'ye karşılık gelen tool mesajını bul
                                for candidate in non_system_msgs:
                                    if candidate["role"] == "tool" and candidate.get("tool_call_id") == tc["id"]:
                                        tools.append(candidate)
                            group.extend(tools)
                groups.append(group)
                # Atlama: eğer bir assistant ve/veya tool eklendiyse, indexi ona göre artır
                idx += len(group)
            else:
                # user ile başlamayan (ör. orphan assistant/tool) mesajı tek başına bir grup yap
                groups.append([msg])
                idx += 1

        # Sliding window: grupları en yeniden eskiye sırala
        total_tokens = 0
        selected_groups = []

        for group in reversed(groups):
            group_tokens = sum(get_token_count(m.get("content", "") or "") for m in group)
            if total_tokens + group_tokens > context_size:
                trace(f"[GRUP] Eklenemedi (token limit aşılır): {[m['role'] for m in group]}")
                continue
            selected_groups.append(group)
            total_tokens += group_tokens
            trace(f"[GRUP] Eklendi: {[m['role'] for m in group]} (token: {group_tokens}, toplam: {total_tokens})")

        # System mesajı en başa
        result = []
        for group in reversed(selected_groups):  # en eski → en yeni
            result.extend(group)
        if system_msg:
            result.insert(0, system_msg)
            trace("[SYSTEM] System mesajı eklendi.")

        trace(f"Sonuçta {len(result)} mesaj var. Toplam token: {total_tokens}")
        return result







import json

if __name__ == "__main__":
    # Your manager class must be imported or defined in the same script
    manager = ContextMemoryManager()

    # Read input messages from JSON file
    with open("orginal.json", "r", encoding="utf-8") as f:
        messages = json.load(f)

    # Set all messages to manager
    manager.set_messages(messages)

    # Refine context (change context_size as needed)
    refined = manager.refine_view(context_size=30000)

    # Write refined messages to output JSON file
    with open("refined.json", "w", encoding="utf-8") as f:
        json.dump(refined, f, indent=2, ensure_ascii=False)

    print(f"Refined {len(refined)} messages written to refined.json")


