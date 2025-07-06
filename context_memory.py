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

    def __init__(self, system: Optional[str] = None, *, dedup_tool_calls: bool = True):
        self._dedup_tool_calls: bool = dedup_tool_calls
        self.__messages: List[Dict[str, Any]] = []
        self._observers: List[Callable[["ContextMemory"], None]] = []
        if system is not None:
            self.set_system_prompt(system)

    # --- Observer methods ---
    def add_observer(self, callback: Callable) -> None:
        self._observers.append(callback)

    def clear_observers(self) -> None:
        self._observers = []

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
        return new_msg["meta"]["id"]

    # Convenience methods for adding typed messages
    def set_system_prompt(self, content: str) -> None:
        self.__messages = [m for m in self.__messages if m["role"] != "system"]
        msg = ensure_meta({"role": "system", "content": content.strip()})
        self.__messages.insert(0, msg)

    def add_user_prompt(self, content: str) -> None:
        id=self.add_message({"role": "user", "content": content})
        return id


    def add_assistant_reply(
        self,
        content: Optional[str],
        tool_calls_with_result: Optional[List[Dict[str, Any]]] = None
    ) -> None:
        assistant_reply = {
            "role": "assistant"
        }
        if tool_calls_with_result:
            assistant_reply["content"] = None
            assistant_reply["tool_calls"] = [
                {
                    "type": call["type"],
                    "id": call["id"],
                    "function": {
                        "name": call["name"],
                        "arguments": call["arguments"],
                    }
                }
                for call in tool_calls_with_result
            ]
            assistant_id = self.add_message(assistant_reply)
            # Sadece BİR assistant mesajı, ardından her tool_call için tool mesajı!
            for call in tool_calls_with_result:
                self.add_message({
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": call["result"],
                }, meta={"assistant_id": assistant_id})
        elif content:
            assistant_reply["content"] = content
            self.add_message(assistant_reply)
        else:
            raise ValueError("Assistant reply: No content or tool call!")

        

    def get_message(self, msg_id: str) -> Optional[Dict[str, Any]]:
        for m in self.__messages:
            if m.get("meta", {}).get("id") == msg_id:
                return m
        return None

    def update_content(self, msg_id: str, new_content: str) -> bool:
        for msg in self.__messages:
            if msg.get("meta", {}).get("id") == msg_id:
                msg["content"] = new_content
                return True
        return False

    def insert_after(self, after_id: str, role: str, content: str) -> Optional[str]:
        index = next((i for i, m in enumerate(self.__messages) if m.get("meta", {}).get("id") == after_id), None)
        if index is None:
            return None
        new_msg = ensure_meta({"role": role, "content": content})
        self.__messages.insert(index + 1, new_msg)
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
        return deleted_count

     # ------------------------------------------------------------------
    # Refinement
    # ------------------------------------------------------------------
    def refine(self,no_metadata=False) -> List[Dict[str, Any]]:
        """Return a *clean* view of the conversation buffer.

        If *dedup_tool_calls* is **True**, duplicate tool‑calls (identical
        ``function.name`` + ``arguments``) are pruned so that **only the most
        recent** call and its tool response remain.  Otherwise the snapshot is
        returned unchanged.
        """
        msgs = self.snapshot()
        if not self._dedup_tool_calls:
            return msgs  # early exit – deduplication disabled

        # 1. Map each tool response line: call_id -> index
        tool_line_of_call: Dict[str, int] = {
            m.get("tool_call_id"): idx
            for idx, m in enumerate(msgs)
            if m.get("role") == "tool"
        }

        # 2. Collect every assistant tool‑call entry
        calls: List[tuple] = []  # (assistant_idx, call_id, key, created_at)
        for idx, m in enumerate(msgs):
            if m.get("role") == "assistant" and "tool_calls" in m:
                created = m.get("meta", {}).get("created_at", 0)
                for call in m["tool_calls"]:
                    key = (call["function"]["name"], str(call["function"]["arguments"]))
                    calls.append((idx, call["id"], key, created))

        # 3. Traverse backwards, keeping first (i.e., latest) occurrence per key
        seen: set = set()
        remove: set[int] = set()
        for a_idx, call_id, key, _ in reversed(calls):
            if key in seen:
                # Older duplicate – mark assistant line and its tool line
                remove.add(a_idx)
                t_idx = tool_line_of_call.get(call_id)
                if t_idx is not None:
                    remove.add(t_idx)
            else:
                seen.add(key)

        result= [m for i, m in enumerate(msgs) if i not in remove]
        if no_metadata:
            # Remove metadata from all messages
            for m in result:    
                m.pop("meta", None)
        return result
