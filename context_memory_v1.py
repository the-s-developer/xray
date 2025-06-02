from typing import Any, Dict, List, Optional, Callable
from nanoid import generate
from copy import deepcopy
from datetime import datetime
import time

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
        # unix timestamp
        msg["meta"]["created_at"] = int(time.time())
    return msg


class ContextMemoryManager:
    def __init__(self, system: Optional[str] = None):
        self._messages: List[Dict[str, Any]] = []
        self._observers: List[Callable] = []
        if system is not None:
            self.set_system_message(system)

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
        msg = ensure_meta(msg)  # Burada her zaman yeni id üret
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
        """Tüm mesajları siler ve observerlara bildirir."""
        self._messages = []
        self._notify_observers()


    def set_messages(self, messages):
        # Her mesajı kendi id’siyle değil, YENİ id ile memory’ye ekle!
        self._messages = [ensure_meta(m.copy()) for m in messages]
        self._notify_observers()


    def add_message(self, msg):
        """Tek bir mesajı ekler, observerlara hemen bildirmez (isteğe bağlı!)."""
        self._messages.append(ensure_meta(msg.copy()))
        
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
    
    def refine_view(
        self,
        n_tool_pairs: int = 10,
        n_assistant: int = 2,
        max_tool_chars: int = 200,
        max_assistant_chars: int = 200,
        drop_message_before_n_user_prompt: int = None,
        trim_tool_before_last_n: Optional[int] = 1,
    ) -> List[Dict[str, Any]]:
        from copy import deepcopy

        def _trim(content: str, limit: int):
            if isinstance(content, str) and len(content) > limit:
                trimmed_len = len(content) - limit
                return content[:limit] + f"\n...[TRIMMED {trimmed_len} chars]...", True
            return content, False

        snapshot = deepcopy(self._messages)

        result = [m.copy() for m in snapshot if m["role"] == "system"]

        # --- USER PROMPT FİLTRESİ (SON N ADET) ---
        if drop_message_before_n_user_prompt is not None and drop_message_before_n_user_prompt > 0:
            user_idxs = [i for i, m in enumerate(snapshot) if m["role"] == "user"]
            if len(user_idxs) >= drop_message_before_n_user_prompt:
                start_idx = user_idxs[-drop_message_before_n_user_prompt]
                sub_snapshot = snapshot[start_idx:]
            else:
                sub_snapshot = snapshot
        else:
            sub_snapshot = snapshot

        # --- ASISTAN MESAJLARI ---
        assistant_msgs = [m for m in sub_snapshot if m["role"] == "assistant" and "tool_calls" not in m]
        assistant_keep = assistant_msgs[-n_assistant:] if n_assistant > 0 else []

        # --- TOOL CALL’LI ASISTANLAR ---
        asst_tool_calls = [m for m in sub_snapshot if m["role"] == "assistant" and "tool_calls" in m]
        last_tool_calls = asst_tool_calls[-n_tool_pairs:] if n_tool_pairs > 0 else []
        tool_call_ids = []
        for m in last_tool_calls:
            for tc in m["tool_calls"]:
                tool_call_ids.append(tc["id"])
        tool_results = [m for m in sub_snapshot if m["role"] == "tool" and m.get("tool_call_id") in tool_call_ids]

        # --- TOOL TRIM: SADECE EN SON N ADET TOOL MESAJI HARİÇ, GERİSİNİ TRIMLE ---
        if trim_tool_before_last_n is not None and trim_tool_before_last_n > 0:
            all_tool_msgs = sorted(
                (m for m in sub_snapshot if m["role"] == "tool"),
                key=lambda m: m["meta"]["created_at"],
                reverse=True  # SONDAN BAŞA
            )
            # En yeni N tool mesajı
            tool_keep_ids = set(m.get("tool_call_id") for m in all_tool_msgs[:trim_tool_before_last_n])
        else:
            tool_keep_ids = set()

        # --- USER MESAJLARINI EKLE ---
        for m in sub_snapshot:
            if m["role"] == "user":
                result.append(m.copy())

        # --- ASISTAN & TOOL ---
        for m in sub_snapshot:
            role = m["role"]
            if role in {"system", "user"}:
                continue

            m2 = m.copy()
            trimmed = False

            if role == "assistant":
                if "tool_calls" in m and m in last_tool_calls:
                    pass  # koru
                elif "tool_calls" not in m and m in assistant_keep:
                    pass  # koru
                else:
                    m2["content"], trimmed = _trim(m2.get("content", ""), max_assistant_chars)

            elif role == "tool":
                if trim_tool_before_last_n is not None and trim_tool_before_last_n > 0:
                    print("TRIMMING TOOL MESSAGES", m2.get("tool_call_id"))
                    # Sadece en yeni N tool mesajı korunsun, diğerleri trimlensin
                    if m.get("tool_call_id") not in tool_keep_ids:
                        m2["content"], trimmed = _trim(m2.get("content", ""), max_tool_chars)
                        print("trimmed tool message:",m2.get("tool_call_id") , m2.get("content"))
                # else hiçbir şey yapma; tool'lar yukarıdaki eski mantığa göre eklenmez

            if trimmed:
                m2["trimmed"] = True

            result.append(m2)

        result.sort(key=lambda m: m["meta"]["created_at"])
        return result







        


