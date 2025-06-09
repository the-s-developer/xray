from typing import Any, Dict, List, Optional, Callable
import time
import copy

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
NANOID_SIZE = 21

def nanoid(size=NANOID_SIZE):
    from nanoid import generate as ng
    return ng(ALPHABET, size)

def now_ms():
    return int(time.time() * 1000)

def ensure_meta(msg):
    msg = dict(msg)
    if "meta" not in msg:
        msg["meta"] = {}
    if "id" not in msg["meta"]:
        msg["meta"]["id"] = nanoid(8)
    if "created_at" not in msg["meta"]:
        msg["meta"]["created_at"] = now_ms()
    else:
        msg["meta"]["created_at"] = to_epoch_ms(msg["meta"]["created_at"])
    return msg

def to_epoch_ms(ts):
    if isinstance(ts, float):
        if ts < 1e11:
            return int(ts * 1000)
        elif ts > 1e13:
            return int(ts // 1_000_000)
        else:
            return int(ts)
    if isinstance(ts, int):
        if ts < 1e11:
            return ts * 1000
        elif ts > 1e13:
            return ts // 1_000_000
        else:
            return ts
    try:
        ts = int(ts)
        if ts < 1e11:
            return ts * 1000
        elif ts > 1e13:
            return ts // 1_000_000
        else:
            return ts
    except Exception:
        return now_ms()

class ContextMemory:
    def __init__(
        self,
        system_prompt: Optional[str] = None,
    ):
        self._messages: List[Dict[str, Any]] = []
        self._observers: List[Callable] = []
        if system_prompt is not None:
            self.set_system_prompt(system_prompt)

    def add_observer(self, callback: Callable) -> None:
        self._observers.append(callback)

    def remove_observer(self, callback: Callable) -> None:
        self._observers = [cb for cb in self._observers if cb != callback]

    def _notify_observers(self):
        snapshot = {"messages": self.snapshot()}
        for cb in self._observers:
            cb(snapshot)

    def set_system_prompt(self, content: str) -> None:
        self._messages = [m for m in self._messages if m["role"] != "system"]
        self._messages.insert(0, ensure_meta({
            "role": "system",
            "content": content.strip()
        }))
        self._notify_observers()

    def add_user_prompt(self, content: str) -> None:
        msg = {"role": "user", "content": content}
        self._messages.append(ensure_meta(msg))
        self._notify_observers()

    def add_assistant_reply(self, content: str) -> None:
        self._messages.append(ensure_meta({
            "role": "assistant",
            "content": content.strip()
        }))
        self._notify_observers()

    def add_tool_calls(self, partial_calls: Dict[str, Dict[str, Any]]) -> None:
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

    def snapshot(self) -> List[Dict[str, Any]]:
        return copy.deepcopy(self._messages)

    def clear(self):
        self._messages = []
        self._notify_observers()

    def set_messages(self, messages: List[Dict[str, Any]]):
        self._messages = [ensure_meta(m.copy()) for m in messages]
        self._notify_observers()

    def add_message(self, msg: Dict[str, Any]):
        self._messages.append(ensure_meta(msg.copy()))
        self._notify_observers()
