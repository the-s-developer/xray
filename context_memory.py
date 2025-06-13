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

    def __init__(self, system: Optional[str] = None):
        self.__messages: List[Dict[str, Any]] = []
        self._observers: List[Callable] = []
        if system is not None:
            self.set_system_prompt(system)

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

    def add_message(self, msg: Dict[str, Any], meta=None) -> Any:
        if msg.get("role") == "system":
            # Enforce using set_system_prompt for system messages
            return
        new_msg = ensure_meta(msg.copy())
        if meta:
            # Merge meta, with meta argument taking precedence
            merged_meta = {**new_msg.get("meta", {}), **meta}
            new_msg["meta"] = merged_meta
        self.__messages.append(new_msg)
        self.notify_observers()
        return new_msg["meta"]["id"]

    # Convenience methods for adding typed messages
    def set_system_prompt(self, content: str) -> None:
        self.__messages = [m for m in self.__messages if m["role"] != "system"]
        msg = ensure_meta({"role": "system", "content": content.strip()})
        self.__messages.insert(0, msg)
        self.notify_observers()

    def add_user_prompt(self, content: str) -> None:
        id=self.add_message({"role": "user", "content": content})
        self.notify_observers()
        return id


    def add_assistant_reply(self,content: Optional[str],tool_calls_with_result: Optional[List[Dict[str, Any]]]=None) -> None:
        assistan_reply={
            "role": "assistant"
        }
        tool_responses=[]
        
        if tool_calls_with_result:
            tool_calls = [
                {
                    "type": call["type"],
                    "id": call["id"],
                    "function": {
                        "name": call["name"],
                        "arguments": call["arguments"],
                    },
                }  for call in tool_calls_with_result
            ]
            assistan_reply["tool_calls"]=tool_calls
            import json
            for call in tool_calls_with_result:
                tool_responses.append({
                    "role": "tool",
                    "tool_call_id":call["id"],
                    "content": call["result"],
                })

        if len(tool_responses)>0:
            assistan_reply["tool_calls"]=tool_calls
            for tr in tool_responses:
                assistant_id=self.add_message(assistan_reply)
                self.add_message(tr,meta={"assistant_id":assistant_id})
        elif content:    
             assistan_reply["content"]=content
             assistant_id=self.add_message(assistan_reply)
        else:
            raise ValueError("")
        
        self.notify_observers()
        

    def get_message(self, msg_id: str) -> Optional[Dict[str, Any]]:
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

    def refine(self) -> List[Dict[str, Any]]:
        return self.snapshot()
