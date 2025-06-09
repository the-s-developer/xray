# chain_of_thought.py

from typing import List, Dict, Any
from context_processor import ContextProcessor

class ChainOfThought(ContextProcessor):
    """
    LLM context hazırlama/refine işlemini yapan sınıf.
    """
    @staticmethod
    def refine(
        messages: List[Dict[str, Any]],
        context_size: int = 1000000,
        enable_trace: bool = False
    ) -> List[Dict[str, Any]]:
        def trace(*args):
            if enable_trace:
                print("[TRACE]", *args)

        if not messages:
            return []

        system_msg = messages[0] if messages[0]["role"] == "system" else None
        if system_msg:
            non_system_msgs = messages[1:]
        else:
            non_system_msgs = messages[:]

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

        incomplete_tool_calls = set()
        incomplete_tool_responses = set()
        for tc_id in tool_call_ids:
            if tc_id not in tool_response_ids:
                incomplete_tool_calls.add(tc_id)
        for tr_id in tool_response_ids:
            if tr_id not in tool_call_ids:
                incomplete_tool_responses.add(tr_id)

        exclude_ids = set()
        for tc_id in incomplete_tool_calls:
            msg = tool_calls_by_id.get(tc_id)
            if msg:
                exclude_ids.add(msg["meta"]["id"])
        for tr_id in incomplete_tool_responses:
            msg = tool_msgs_by_call_id.get(tr_id)
            if msg:
                exclude_ids.add(msg["meta"]["id"])
        for tc_id in incomplete_tool_calls:
            tmsg = tool_msgs_by_call_id.get(tc_id)
            if tmsg:
                exclude_ids.add(tmsg["meta"]["id"])
        for tr_id in incomplete_tool_responses:
            amsg = tool_calls_by_id.get(tr_id)
            if amsg:
                exclude_ids.add(amsg["meta"]["id"])

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

        result_msgs.sort(key=lambda x: x["meta"]["created_at"])
        return result_msgs
