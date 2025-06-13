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
    if "cycle" not in msg["meta"]:
        msg["meta"]["cycle"] = 0
    return msg

class ContextMemory:
    """Conversation buffer with private messages list."""

    def __init__(self, system_prompt: Optional[str] = None):
        self.__messages: List[Dict[str, Any]] = []
        self._observers: List[Callable] = []
        if system_prompt is not None:
            self.set_system_prompt(system_prompt)

    def _get_last_user_id(self) -> Optional[str]:
        for msg in reversed(self.__messages):
            if msg["role"] == "user":
                return msg["meta"]["id"]
        return None

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
    
    def cycle(self) -> None:
            for msg in self.__messages:
                meta = msg.setdefault("meta", {})
                meta["cycle"] = meta.get("cycle", 0) + 1
            self.notify_observers()

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
        self.add_message(msg)

    def add_assistant_reply(self, content: str) -> None:
        parent_id = self._get_last_user_id()
        msg = {
            "role": "assistant",
            "content": content.strip(),
            "meta": {}
        }
        if parent_id is not None:
            msg["meta"]["parent_id"] = parent_id
        self.add_message(msg)

    def add_tool_calls(self, call: Dict[str, Any]) -> None:
        parent_id = self._get_last_user_id()
        tool_calls = [
            {
                "type": call["type"],
                "id": call["id"],
                "function": {
                    "name": call["name"],
                    "arguments": call["arguments"],
                },
            }
        ]
        msg = {
            "role": "assistant",
            "content": None,
            "tool_calls": tool_calls,
            "meta": {}
        }
        if parent_id is not None:
            msg["meta"]["parent_id"] = parent_id
        self.add_message(msg)

    def add_tool_result(self, tool_call_id: str, content: str, meta=None) -> None:
        parent_id = self._get_last_user_id()
        msg = {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content.strip(),
            "meta": {}
        }
        if parent_id is not None:
            msg["meta"]["parent_id"] = parent_id
        self.add_message(msg)


    def get_message(self, msg_id: str) -> Optional[Dict[str, Any]]:
        for m in self.__messages:
            if m.get("meta", {}).get("id") == msg_id:
                return copy.deepcopy(m)
        return None
    
    def update_content(self, msg_id: str, new_content: str) -> bool:
        for msg in self.__messages:
            if msg.get("meta", {}).get("id") == msg_id:
                msg["content"] = new_content
                self.notify_observers()
                return True
        return False

    def delete(self, ids: List[str]) -> int:
        """
        Verilen mesaj ID listesine göre mesajları siler.
        Sadece o mesajlar silinir.
        System mesajları silinmez.
        """
        protected_ids = {m["meta"]["id"] for m in self.__messages if m["role"] == "system"}
        ids_to_delete = set(ids) - protected_ids

        new_messages = [m for m in self.__messages if m["meta"]["id"] not in ids_to_delete]
        deleted_count = len(self.__messages) - len(new_messages)
        if deleted_count > 0:
            self.__messages = new_messages
            self.notify_observers()
        return deleted_count

    def delete_user(self, user_ids: List[str]) -> int:
        """
        Her user mesajı için: 
        o user mesajı + ona bağlı (sonraki user'a kadar) assistant/tool mesajlarını siler.
        """
        if not user_ids:
            return 0
        user_ids = set(user_ids)
        to_delete = set()
        i = 0
        while i < len(self.__messages):
            msg = self.__messages[i]
            if msg["role"] == "user" and msg["meta"]["id"] in user_ids:
                # Bu user ve ona bağlı assistant/tool mesajlarını to_delete'a ekle
                to_delete.add(msg["meta"]["id"])
                i += 1
                while i < len(self.__messages) and self.__messages[i]["role"] in ("assistant", "tool"):
                    to_delete.add(self.__messages[i]["meta"]["id"])
                    i += 1
            else:
                i += 1
        # system hariç to_delete olanları sil
        protected_ids = {m["meta"]["id"] for m in self.__messages if m["role"] == "system"}
        final_to_delete = to_delete - protected_ids
        new_messages = [m for m in self.__messages if m["meta"]["id"] not in final_to_delete]
        deleted_count = len(self.__messages) - len(new_messages)
        if deleted_count > 0:
            self.__messages = new_messages
            self.notify_observers()
        return deleted_count

    def delete_tool(self, call_id: str) -> int:
        """
        Belirli bir tool call id'sine göre,
        ilgili assistant (tool call) ve ona karşılık gelen tool (tool response) mesajlarını siler.
        """
        to_delete = set()
        for i, msg in enumerate(self.__messages):
            if msg["role"] == "assistant" and "tool_calls" in msg:
                for tc in msg["tool_calls"]:
                    if tc["id"] == call_id:
                        to_delete.add(msg["meta"]["id"])
            if msg["role"] == "tool" and msg.get("tool_call_id") == call_id:
                to_delete.add(msg["meta"]["id"])
        if not to_delete:
            return 0
        # system hariç sil
        protected_ids = {m["meta"]["id"] for m in self.__messages if m["role"] == "system"}
        final_to_delete = to_delete - protected_ids
        new_messages = [m for m in self.__messages if m["meta"]["id"] not in final_to_delete]
        deleted_count = len(self.__messages) - len(new_messages)
        if deleted_count > 0:
            self.__messages = new_messages
            self.notify_observers()
        return deleted_count
    
    def insert_after(self, after_id: str, role: str, content: str) -> Optional[str]:
        index = next((i for i, m in enumerate(self.__messages) if m.get("meta", {}).get("id") == after_id), None)
        if index is None:
            return None
        new_msg = ensure_meta({"role": role, "content": content})
        self.__messages.insert(index + 1, new_msg)
        self.notify_observers()
        return new_msg["meta"]["id"]

    def delete_after(self, msg_id: str) -> bool:
        """
        Verilen mesajdan (msg_id) SONRAKİ tüm mesajları siler.
        System mesajları silinmez.
        """
        index = next((i for i, m in enumerate(self.__messages) if m.get("meta", {}).get("id") == msg_id), None)
        if index is None:
            return False
        protected_ids = {m["meta"]["id"] for m in self.__messages if m["role"] == "system"}
        # index+1'den başla, sona kadar git, system'ları koru
        del_msgs = [m for m in self.__messages[index+1:] if m["meta"]["id"] not in protected_ids]
        if not del_msgs:
            return False
        # Sadece kalanları tut
        self.__messages = self.__messages[:index+1] + [m for m in self.__messages[index+1:] if m["meta"]["id"] in protected_ids]
        self.notify_observers()
        return True
    