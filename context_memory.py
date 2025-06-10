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
    return msg


class ContextMemory:
    """Conversation buffer with private messages list."""

    def __init__(self, system_prompt: Optional[str] = None):
        self.__messages: List[Dict[str, Any]] = []
        self._observers: List[Callable] = []
        if system_prompt is not None:
            self.set_system_prompt(system_prompt)

    # --- Observer methods ---
    def add_observer(self, callback: Callable) -> None:
        self._observers.append(callback)

    def remove_observer(self, callback: Callable) -> None:
        self._observers = [cb for cb in self._observers if cb != callback]

    def notify_observers(self):
        for cb in self._observers:
            cb(self)

    # --- Message accessors ---
    def snapshot(self) -> List[Dict[str, Any]]:
        # Return deep copy to avoid external mutation
        return copy.deepcopy(self.__messages)

    # --- Message mutators ---
    def clear(self, keep_system: bool = True) -> None:
        self.__messages = [m for m in self.__messages if keep_system and m["role"] == "system"]
        self.notify_observers()

    def add_message(self, msg: Dict[str, Any]) -> None:
        if msg.get("role") == "system":
            # Enforce using set_system_prompt for system messages
            return
        self.__messages.append(ensure_meta(msg.copy()))
        self.notify_observers()

    # Convenience methods for adding typed messages
    def set_system_prompt(self, content: str) -> None:
        self.__messages = [m for m in self.__messages if m["role"] != "system"]
        msg = ensure_meta({"role": "system", "content": content.strip()})
        self.__messages.insert(0, msg)
        self.notify_observers()

    def add_user_prompt(self, content: str) -> None:
        msg = ensure_meta({"role": "user", "content": content})
        self.__messages.append(msg)
        self.notify_observers()

    def add_assistant_reply(self, content: str) -> None:
        msg = ensure_meta({"role": "assistant", "content": content.strip()})
        self.__messages.append(msg)
        self.notify_observers()

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
        msg = ensure_meta({
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls,
        })
        self.__messages.append(msg)
        self.notify_observers()

    def add_tool_result(self, tool_call_id: str, content: str) -> None:
        msg = ensure_meta({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content.strip(),
        })
        self.__messages.append(msg)
        self.notify_observers()

    # --- Find and update/delete methods ---

    def find_message(self, msg_id: str) -> Optional[Dict[str, Any]]:
        for m in self.__messages:
            if m.get("meta", {}).get("id") == msg_id:
                return m
        return None

    def update_content(self, msg_id: str, new_content: str) -> bool:
        for msg in self.__messages:
            if msg.get("meta", {}).get("id") == msg_id:
                msg["content"] = new_content
                self.notify_observers()
                return True
        return False

    def insert_after(self, after_id: str, role: str, content: str) -> Optional[str]:
        index = next((i for i, m in enumerate(self.__messages) if m.get("meta", {}).get("id") == after_id), None)
        if index is None:
            return None
        new_msg = ensure_meta({"role": role, "content": content})
        self.__messages.insert(index + 1, new_msg)
        self.notify_observers()
        return new_msg["meta"]["id"]

    def delete_after(self, msg_id: str) -> bool:
        index = next((i for i, m in enumerate(self.__messages) if m.get("meta", {}).get("id") == msg_id), None)
        if index is None:
            return False
        protected_ids = [m["meta"]["id"] for m in self.__messages if m["role"] == "system"]
        del_msgs = self.__messages[index:]
        if any(m["meta"]["id"] in protected_ids for m in del_msgs):
            # Don't allow deleting system prompt
            return False
        self.__messages = self.__messages[:index]
        self.notify_observers()
        return True
    
    def delete(self, ids: List[str]) -> int:
        """
        Verilen mesaj ID listesine göre mesajları siler.
        System mesajları silinmez.
        User mesajı silinirse, ona bağlı assistant ve tool mesajları da silinir.
        Silinen mesaj sayısını döner.
        """
        protected_ids = {m["meta"]["id"] for m in self.__messages if m["role"] == "system"}
        ids_to_delete = set(ids) - protected_ids

        new_messages = []
        i = 0
        messages = self.__messages
        while i < len(messages):
            m = messages[i]
            msg_id = m["meta"]["id"]
            if msg_id in ids_to_delete:
                # Eğer silinen mesaj user ise, bağlı assistant/tool mesajlarını atla
                if m["role"] == "user":
                    i += 1
                    while i < len(messages) and messages[i]["role"] in ("assistant", "tool"):
                        i += 1
                    continue
                else:
                    # user değilse sadece bu mesajı atla
                    i += 1
                    continue
            else:
                new_messages.append(m)
                i += 1

        deleted_count = len(self.__messages) - len(new_messages)
        if deleted_count > 0:
            self.__messages = new_messages
            self.notify_observers()
        return deleted_count

    def refine(self,with_id=True) -> List[Dict[str, Any]]:
        messages = self.snapshot()

        system_msg: Optional[Dict[str, Any]] = None
        for m in reversed(messages):
            if m.get("role") == "system":
                system_msg = m
                break

        user_msgs: List[Dict[str, Any]] = [m for m in messages if m.get("role") == "user"]

        assistant_plain: List[Dict[str, Any]] = [
            m for m in messages if m.get("role") == "assistant" and not m.get("tool_calls")
        ]

        last_user_idx: Optional[int] = None
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].get("role") == "user":
                last_user_idx = idx
                break

        tool_section: List[Dict[str, Any]] = []
        if last_user_idx is not None:
            i = last_user_idx + 1
            while i < len(messages):
                current = messages[i]
                if current.get("role") == "assistant" and current.get("tool_calls"):
                    tool_section.append(current)
                    call_ids = {call["id"] for call in current["tool_calls"]}
                    j = i + 1
                    while j < len(messages):
                        maybe_tool = messages[j]
                        if maybe_tool.get("role") in {"user", "assistant"} and not maybe_tool.get("role") == "tool":
                            break
                        if maybe_tool.get("role") == "tool" and maybe_tool.get("tool_call_id") in call_ids:
                            tool_section.append(maybe_tool)
                        j += 1
                    i = j
                else:
                    i += 1

        result: List[Dict[str, Any]] = []
        if system_msg:
            result.append(system_msg)
        result.extend(user_msgs)
        result.extend(assistant_plain)
        result.extend(tool_section)

        result.sort(key=lambda m: m.get("meta", {}).get("created_at", 0))

        if with_id:
            for m in result:
                if m.get("content") and m.get("meta", {}).get("id") and m.get("role") in ["asistan", "tool"]:
                    m["content"] += f" [#msgid:{m['meta']['id']}]"

        return result
