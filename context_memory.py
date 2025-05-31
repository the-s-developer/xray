from typing import Any, Dict, List, Optional, Callable
import uuid
from nanoid import generate

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
NANOID_SIZE = 21

def nanoid(size=NANOID_SIZE):
    return generate(ALPHABET, size)

def ensure_id(msg):
    msg = dict(msg)  # Kopyala (güvenlik için)
    msg["id"] = nanoid(8)
    return msg


class ContextMemoryManager:
    def __init__(
        self,
        system: Optional[str] = None,
    ):
        self._messages: List[Dict[str, Any]] = []
        self._observers: List[Callable] = []
        if system is not None:
            self.set_system_message(system)


    
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
        self._messages.insert(0, ensure_id({
            "role": "system",
            "content": content.strip()
        }))
        self._notify_observers()

    def add_user_prompt(self, content: str) -> None:
        msg = {"role": "user", "content": content}
        msg = ensure_id(msg)  # Burada her zaman yeni id üret
        self._messages.append(msg)
        self._notify_observers()

    def add_assistant_reply(self, content: str) -> None:
        self._messages.append(ensure_id({
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
        self._messages.append(ensure_id({
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls
        }))
        self._notify_observers()

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self._messages.append(ensure_id({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content.strip()
        }))
        self._notify_observers()

    def get_all_messages(self) -> List[Dict[str, Any]]:
        return self._messages.copy()

    def get_memory_snapshot(self):
        return {
            "messages": self._messages
        }


    def clear(self):
        """Tüm mesajları siler ve observerlara bildirir."""
        self._messages = []
        self._notify_observers()


    def set_messages(self, messages):
        # Her mesajı kendi id’siyle değil, YENİ id ile memory’ye ekle!
        self._messages = [ensure_id(m.copy()) for m in messages]
        self._notify_observers()


    def add_message(self, msg):
        """Tek bir mesajı ekler, observerlara hemen bildirmez (isteğe bağlı!)."""
        self._messages.append(ensure_id(msg.copy()))
        
    def dump(self) -> str:
        lines = []
        for msg in self._messages:
            role = msg.get("role", "?")
            if role == "assistant" and msg.get("tool_calls"):
                calls_str = []
                for call in msg["tool_calls"]:
                    calls_str.append(
                        f"[tool_call] type={call.get('type')} id={call.get('id')} "
                        f"function={call.get('function', {}).get('name')} "
                        f"args={call.get('function', {}).get('arguments')}"
                    )
                lines.append(f"assistant (tool_calls):\n    " + "\n    ".join(calls_str))
            elif role == "tool":
                lines.append(
                    f"tool (id={msg.get('tool_call_id')}): {msg.get('content')}"
                )
            else:
                content = msg.get("content")
                lines.append(f"\n\n{role}:\n\n {content}")
            lines.append("="*50)        
        return "\n".join(lines)
    def retain_last_tool_call_pairs(self, n: int):
        """
        Sadece tool çağrısı içeren assistant ve tool mesajlarını son n çift olacak şekilde tutar.
        Diğer user, system ve tool_calls olmayan assistant mesajları KORUNUR.
        """
        # 1. Diğer mesajlar sabit dursun
        preserved = [msg for msg in self._messages if (
            msg.get("role") in ("system", "user") or (
                msg.get("role") == "assistant" and "tool_calls" not in msg
            )
        )]

        # 2. Tool çağrısı içeren assistant ve tool mesajlarını al
        assistant_toolcalls = []
        tool_results = []
        for msg in self._messages:
            if msg.get("role") == "assistant" and "tool_calls" in msg:
                assistant_toolcalls.append(msg)
            elif msg.get("role") == "tool":
                tool_results.append(msg)

        # 3. Son n tool çağrısı bul ve id’lerini çıkar
        last_n_assistants = assistant_toolcalls[-n:]
        tool_call_ids_to_keep = []
        for msg in last_n_assistants:
            for call in msg["tool_calls"]:
                tool_call_ids_to_keep.append(call["id"])

        # 4. Sadece bu tool_call_id’lere ait tool sonuçlarını tut
        last_n_tool_results = [msg for msg in tool_results if msg.get("tool_call_id") in tool_call_ids_to_keep]

        # 5. Tümünü kronolojik sıraya göre birleştir
        filtered = []
        for msg in self._messages:
            if msg in preserved:
                filtered.append(msg)
            elif msg in last_n_assistants:
                filtered.append(msg)
            elif msg in last_n_tool_results:
                filtered.append(msg)

        self._messages = filtered
        self._notify_observers()

