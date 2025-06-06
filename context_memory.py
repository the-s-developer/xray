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
        self._messages = [ensure_meta(m.copy()) for m in messages]
        self._notify_observers()

    def add_message(self, msg):
        self._messages.append(ensure_meta(msg.copy()))

    def refine_view(
        self,
        context_size=1000000,
        enable_trace=True,
    ):
        """
        Refine_view fonksiyonunun işlevi:
        
        1. **Amaç:**  
           - Tüm mesaj geçmişinden, toplam token (veya karakter) sınırını aşmayacak şekilde  
             mantıksal olarak tutarlı ve kopuksuz bir context (mesaj dizisi) oluşturmak.
           - Özellikle tool call ve tool response çiftlerini **daima birlikte** tutmak,
             arka arkaya iki user veya yanıtı eksik kalan tool call bırakmamak.

        2. **Çalışma Prensibi:**
           - Mesajları (system mesajı hariç) en yenisinden en eskiye sıralar.
           - Her assistant tool çağrısı için, ilgili tüm tool yanıtları varsa
             *çift* olarak birlikte ekler (ve ikisi de token limitine sığıyorsa).
           - Tek başına kalan, pair’i olmayan tool call veya tool response mesajlarını
             **asla eklemez** (bağlam bütünlüğü bozulmasın diye).
           - Sadece user veya tool_calls olmayan assistant mesajları ise,
             token limitine sığıyorsa tek başına eklenir.
           - Her eklenen mesajın ID’si takip edilir, çiftler tekrar tekrar eklenmez.
           - Her eklemede toplam token (karakter/4) miktarı izlenir, aşılırsa ekleme durur.
           - System mesajı (varsa) en sona eklenir (aslında başa koymak gerekebilir, istersen tersine çevir).

        3. **Neden bu yöntem?**
           - LLM context’inde **kopuk, cevapsız user promptu**, ya da pair’i eksik tool call bırakmak, modelin akışını bozar.
           - Bu yöntem, sadece “tam diyalog bloklarını” (user+assistant veya assistant[tool_call]+tool) içeri alır.
           - Token limitinin verimli kullanılmasını ve anlam bütünlüğünü garanti eder.

        4. **Sonuç:**
           - Refined context, “sliding window” ile, token sınırına uygun ve her zaman tutarlı
             (kopuk olmayan, cevapsız user promptu veya tool pair’i bırakmayan) bir geçmiş üretir.

        5. **Debug/Trace:**
           - enable_trace parametresi True ise, hangi mesajların neden eklenip eklenmediğini stdout’a basar.

        NOT:  
        - Eğer context limitine ilk sığmayan mesaj bir assistant+tool pair’iyse, o komple atlanır.
        - Arka arkaya iki user, arka arkaya iki assistant veya pair’i eksik mesaj **asla eklenmez**.
        """

        def trace(*args):
            if enable_trace:
                print("[TRACE]", *args)

        from copy import deepcopy
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

        for m in non_system_msgs:
            if m["role"] == "assistant" and m.get("tool_calls"):
                for tc in m["tool_calls"]:
                    tool_calls_by_id[tc["id"]] = m
            if m["role"] == "tool" and m.get("tool_call_id"):
                tool_msgs_by_call_id[m["tool_call_id"]] = m

        # Kopyası, id ile hızlı erişim için
        by_id = {m["meta"]["id"]: m for m in non_system_msgs}

        # Sliding window için en yeni → en eski
        sorted_msgs = sorted(non_system_msgs, key=lambda x: x["meta"]["created_at"], reverse=True)
        selected_ids = set()
        total_tokens = 0
        result_msgs = []

        for msg in sorted_msgs:
            mid = msg["meta"]["id"]

            # Tool çağrısı ise, pair'i var mı kontrol et
            if msg["role"] == "assistant" and msg.get("tool_calls"):
                all_pair_exists = True
                for tc in msg["tool_calls"]:
                    if tc["id"] not in tool_msgs_by_call_id:
                        all_pair_exists = False
                        break
                if not all_pair_exists:
                    trace(f"[SKIP] Tool çağrısının pair'i yok: {mid}")
                    continue

                # Hepsi pair ise, hem assistant'ı hem tool mesajlarını ekle
                chain = [msg]
                for tc in msg["tool_calls"]:
                    tmsg = tool_msgs_by_call_id[tc["id"]]
                    chain.append(tmsg)
                new_chain = [m for m in chain if m["meta"]["id"] not in selected_ids]
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
                # Zaten pair eklenmişse tekrar eklemeye gerek yok
                if a_msg["meta"]["id"] in selected_ids and mid in selected_ids:
                    continue
                # Bu tool çağrısı yukarıda zaten eklendiği için burada atla
                continue

            # Normal user & assistant (tool_calls olmayan)
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

        result_msgs.sort(key=lambda x: x["meta"]["created_at"])
        return result_msgs




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
    refined = manager.refine_view(context_size=20000)

    # Write refined messages to output JSON file
    with open("refined.json", "w", encoding="utf-8") as f:
        json.dump(refined, f, indent=2, ensure_ascii=False)

    print(f"Refined {len(refined)} messages written to refined.json")


