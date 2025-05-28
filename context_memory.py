from typing import Any, Dict, List, Optional, Callable
import uuid

class ContextMemoryManager:
    def __init__(
        self,
        max_context_tokens: int = 1000000,
        system: Optional[str] = None,
        max_big_content: Optional[int] = 2,
        big_content_threshold: int = 2000
    ):
        self.max_context_tokens = max_context_tokens
        self.max_big_content = max_big_content
        self.big_content_threshold = big_content_threshold
        self._messages: List[Dict[str, Any]] = []
        self._observers: List[Callable] = []
        if system is not None:
            self.set_system_message(system)

    def _new_id(self) -> str:
        # Kısa ama rastgele bir id, 12 karakter (uuid4)
        return str(uuid.uuid4())[:12]

    def add_observer(self, callback: Callable) -> None:
        print("add observer")
        self._observers.append(callback)

    def remove_observer(self, callback: Callable) -> None:
        self._observers = [cb for cb in self._observers if cb != callback]

    def _notify_observers(self):
        snapshot = self.get_memory_snapshot()
        for cb in self._observers:
            cb(snapshot)

    def set_system_message(self, content: str) -> None:
        self._messages = [m for m in self._messages if m["role"] != "system"]
        self._messages.insert(0, {
            "id": self._new_id(),
            "role": "system",
            "content": content.strip()
        })
        self._notify_observers()

    def add_user_prompt(self, content: str) -> None:
        self._messages.append({
            "id": self._new_id(),
            "role": "user",
            "content": content
        })
        self._notify_observers()

    def add_assistant_reply(self, content: str) -> None:
        self._messages.append({
            "id": self._new_id(),
            "role": "assistant",
            "content": content.strip()
        })
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
        self._messages.append({
            "id": self._new_id(),
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls
        })
        self._notify_observers()

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        self._messages.append({
            "id": self._new_id(),
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content.strip()
        })
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
        """Memory’yi verilen mesajlarla sıfırlar (deepcopy ile)."""
        self._messages = [m.copy() for m in messages]
        self._notify_observers()

    def add_message(self, msg):
        """Tek bir mesajı ekler, observerlara hemen bildirmez (isteğe bağlı!)."""
        self._messages.append(msg)
        
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
