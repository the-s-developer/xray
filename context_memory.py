from typing import Any, Dict, List, Optional, Callable
from nanoid import generate
from copy import deepcopy
import time
import json
from tool_local_client import ToolLocalClient

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
NANOID_SIZE = 21

def nanoid(size=NANOID_SIZE):
    return generate(ALPHABET, size)

def now_ms():
    """Şu anın epoch milisaniyesini döndürür."""
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
        # Her gelen created_at'ı milisaniyeye normalize et
        msg["meta"]["created_at"] = to_epoch_ms(msg["meta"]["created_at"])
    return msg

def to_epoch_ms(ts):
    """Timestamp değerini her durumda milisaniyeye çevirir."""
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
    # str ise int'e çevirip yine uygula
    try:
        ts = int(ts)
        if ts < 1e11:
            return ts * 1000
        elif ts > 1e13:
            return ts // 1_000_000
        else:
            return ts
    except:
        return now_ms()  # fallback

    """
    Assistant tool_calls ile onların tool response'larını 
    aralarına başka mesaj girmişse hemen arkasına taşı ve 
    timestamp'i güncelle.
    """
    # Önce sıralayalım
    messages.sort(key=lambda m: m["meta"]["created_at"])
    id_to_index = {m["meta"]["id"]: i for i, m in enumerate(messages)}

    # assistant tool_call mesajlarını bul
    for i, msg in enumerate(messages):
        if msg["role"] == "assistant" and msg.get("tool_calls"):
            for tc in msg["tool_calls"]:
                # Bu call id'ye sahip bir tool cevabı var mı?
                # Arada prompt/başka bir şey girmiş mi bakalım
                for j in range(i+1, len(messages)):
                    tmsg = messages[j]
                    if (
                        tmsg["role"] == "tool" 
                        and tmsg.get("tool_call_id") == tc["id"]
                    ):
                        # Hemen sonrasındaysa zaten sıkıntı yok
                        if j == i+1:
                            break
                        # Araya başka şey girmiş, taşı!
                        tool_msg = messages.pop(j)
                        tool_msg["meta"]["created_at"] = msg["meta"]["created_at"] + 1
                        messages.insert(i+1, tool_msg)
                        break
    return messages

def get_token_count(text):
    # Basit: karakter/4 ≈ token hesabı (örnek)
    return int(len(text or "") / 4)

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
        # Burada da gelen tüm mesajların created_at'ını normalize ediyoruz
        self._messages = [ensure_meta(m.copy()) for m in messages]
        self._notify_observers()

    def add_message(self, msg):
        self._messages.append(ensure_meta(msg.copy()))

    def refine_view(
        self,
        context_size=50000,
        enable_trace=False,
    ):
        def trace(*args):
            if enable_trace:
                print("[TRACE]", *args)

        snapshot = deepcopy(self._messages)
        if not snapshot:
            return []

        system_msg = snapshot[0] if snapshot[0]["role"] == "system" else None
        if system_msg:
            non_system_msgs = snapshot[1:]
        else:
            non_system_msgs = snapshot[:]

        # Pair indexlerini hazırla
        tool_calls_by_id = {}
        tool_msgs_by_call_id = {}
        tool_call_ids = set()
        tool_response_ids = set()

        for m in non_system_msgs:
            if m["role"] == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    tool_calls_by_id[tc["id"]] = m
                    tool_call_ids.add(tc["id"])
            if m["role"] == "tool" and m.get("tool_call_id"):
                tool_msgs_by_call_id[m["tool_call_id"]] = m
                tool_response_ids.add(m["tool_call_id"])

        # Eksik pair’leri bul
        incomplete_tool_calls = set()
        incomplete_tool_responses = set()
        for tc_id in tool_call_ids:
            if tc_id not in tool_response_ids:
                incomplete_tool_calls.add(tc_id)
        for tr_id in tool_response_ids:
            if tr_id not in tool_call_ids:
                incomplete_tool_responses.add(tr_id)

        # Hangi mesajların dahil edilmemesi gerektiğini id bazında işaretle
        exclude_ids = set()
        # Eksik pair’li assistant mesajlarını hariç tut
        for tc_id in incomplete_tool_calls:
            msg = tool_calls_by_id.get(tc_id)
            if msg:
                exclude_ids.add(msg["meta"]["id"])
        # Eksik pair’li tool mesajlarını hariç tut
        for tr_id in incomplete_tool_responses:
            msg = tool_msgs_by_call_id.get(tr_id)
            if msg:
                exclude_ids.add(msg["meta"]["id"])

        # Ayrıca eksik pair’li assistant mesajının tool_call_ids’ini gezip, o tool response’ları da hariç tut
        for tc_id in incomplete_tool_calls:
            tmsg = tool_msgs_by_call_id.get(tc_id)
            if tmsg:
                exclude_ids.add(tmsg["meta"]["id"])
        # Eksik pair’li tool response’ların çağıran assistant’larını da hariç tut
        for tr_id in incomplete_tool_responses:
            amsg = tool_calls_by_id.get(tr_id)
            if amsg:
                exclude_ids.add(amsg["meta"]["id"])

        by_id = {m["meta"]["id"]: m for m in non_system_msgs}

        # Sliding window için en yeni → en eski, created_at her zaman milisaniye!
        sorted_msgs = sorted(
            non_system_msgs, 
            key=lambda x: x["meta"]["created_at"], 
            reverse=True
        )
        selected_ids = set()
        total_tokens = 0
        result_msgs = []

        for msg in sorted_msgs:
            mid = msg["meta"]["id"]
            if mid in exclude_ids:
                trace(f"[SKIP] Eksik pair'li mesaj: {msg['role']} {mid}")
                continue

            # Tool çağrısı ise, pair'i var mı kontrol et (ek güvenlik, yukarıda da kontrol edildi)
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                all_pair_exists = True
                for tc in msg["tool_calls"]:
                    if tc["id"] not in tool_msgs_by_call_id:
                        all_pair_exists = False
                        break
                if not all_pair_exists:
                    trace(f"[SKIP] Tool çağrısının pair'i yok: {mid}")
                    continue

                chain = [msg]
                for tc in msg["tool_calls"]:
                    tmsg = tool_msgs_by_call_id[tc["id"]]
                    chain.append(tmsg)
                new_chain = [m for m in chain if m["meta"]["id"] not in selected_ids and m["meta"]["id"] not in exclude_ids]
                group_tokens = sum(len((m.get("content") or "")) // 4 for m in new_chain)
                if total_tokens + group_tokens > context_size:
                    trace(f"[SKIP] Pair limit dışı: {[m['role'] for m in new_chain]}")
                    continue
                result_msgs.extend(new_chain)
                for m in new_chain:
                    selected_ids.add(m["meta"]["id"])
                total_tokens += group_tokens
                trace(f"[PAIR] Eklendi: {[m['role'] for m in new_chain]} (t={group_tokens}, toplam={total_tokens})")
                continue

            # Tool cevabı ise, pair'inin assistant'ı var mı kontrol et
            if msg["role"] == "tool" and msg.get("tool_call_id"):
                a_msg = tool_calls_by_id.get(msg["tool_call_id"])
                if not a_msg:
                    trace(f"[SKIP] Tool cevabının pair'i yok: {mid}")
                    continue
                if a_msg["meta"]["id"] in selected_ids and mid in selected_ids:
                    continue
                continue

            if mid in selected_ids:
                continue
            t = len((msg.get("content") or "")) // 4
            if total_tokens + t > context_size:
                trace(f"[SKIP] Tekil token limit: {msg['role']} {mid}")
                continue
            result_msgs.append(msg)
            selected_ids.add(mid)
            total_tokens += t
            trace(f"[TEKIL] Eklendi: {msg['role']} (t={t}, toplam={total_tokens}) -- {msg.get('content', '')[:60]}")

        if system_msg:
            result_msgs.append(system_msg)
            trace("[SYSTEM] System mesajı eklendi.")

        # En son yine milisaniyeye göre sırala
        result_msgs.sort(key=lambda x: x["meta"]["created_at"])
        return result_msgs


if __name__ == "__main__":
    manager = ContextMemoryManager()

    # Girdi mesajlarını oku
    with open("orginal.json", "r", encoding="utf-8") as f:
        messages = json.load(f)

    # Eski mesajların created_at alanlarını da normalize et!
    for m in messages:
        if "meta" in m and "created_at" in m["meta"]:
            m["meta"]["created_at"] = to_epoch_ms(m["meta"]["created_at"])

    manager.set_messages(messages)

    # Refine context (change context_size as needed)
    refined = manager.refine_view(context_size=20000)

    # Çıktıyı kaydet
    with open("refined.json", "w", encoding="utf-8") as f:
        json.dump(refined, f, indent=2, ensure_ascii=False)

    print(f"Refined {len(refined)} messages written to refined.json")
