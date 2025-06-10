# temporal_memory.py

from context_memory import ContextMemory
from typing import List, Dict, Any, Optional
from tool_local_client import ToolLocalClient
import logging
import time

INSTRUCTION_PROMPT="""
Rules:
- if there is summerized [temporal-memory_recall(key)] text,content what is over 4096 character is always trimmed,use temporal recall with key to get full data
"""

class TemporalMemory(ContextMemory):
    def __init__(self, system_prompt):
        system_prompt+=INSTRUCTION_PROMPT
        super().__init__(system_prompt=system_prompt)

        self.temporal_data: Dict[str, str] = {}

    # def memorize(self, key: str, msg_id: str) -> str:
    #     msg = self.find_message(msg_id)
    #     if not msg:
    #         raise ValueError(f"Message with id {msg_id} not found.")
    #     self.temporal_data[key] = msg.get("content", "")
    #     return "success"

    async def recall(self, keys: List[str]) -> Dict[str, Any]:
        return {key: self.temporal_data.get(key, None) for key in keys}

    def add_tool_result(self, tool_call_id: str, content: str,meta=None) -> None:
        if meta is None:
            raise ValueError("add_tool_result fn is None")
        import json
        MAX_SIZE = 4096
        # Skip summarization if the tool_call_id starts with "temporal-memory"
        if meta["name"].startswith("temporal-memory"):
            super().add_tool_result(tool_call_id, content)
            return
        if len(content) > MAX_SIZE:
            key = f"{tool_call_id}"
            self.temporal_data[key] = content
            summary = content[:256] + f"\n\n---\\n ...summarized!\n full data is saved to [temporal_memory_key: {key}]"
            super().add_tool_result(tool_call_id, summary)
        else:
            super().add_tool_result(tool_call_id, content)

    def add_user_prompt(self, content: str) -> None:
        super().add_user_prompt(content)
        self.keep_n_recall_pairs_before_last_user(n=0)

    def keep_n_recall_pairs_before_last_user(self, n=3):
        """
        En son user prompt'tan sonraki recall pair'ları daima saklar,
        önceki pair'lar arasında ise son n tanesini tutar, fazlasını siler.
        Sadece recall tool call pair'ları (assistant'ın content'i None ve tool_calls'da
        function name'i 'temporal-memory__recall' olanlar) silinir.
        """
        messages = self.snapshot()
        last_user_idx = None
        for idx in range(len(messages) - 1, -1, -1):
            if messages[idx].get("role") == "user":
                last_user_idx = idx
                break
        if last_user_idx is None:
            return []

        def collect_pairs(start, end):
            pairs = []
            i = start
            while i < end:
                msg = messages[i]
                if msg.get("role") == "assistant" and msg.get("tool_calls"):
                    call_ids = [call["id"] for call in msg["tool_calls"]]
                    j = i + 1
                    tool_msgs = []
                    while j < end:
                        next_msg = messages[j]
                        if next_msg.get("role") == "tool" and next_msg.get("tool_call_id") in call_ids:
                            tool_msgs.append(next_msg)
                        elif next_msg.get("role") in {"user", "assistant"}:
                            break
                        j += 1
                    for tool_msg in tool_msgs:
                        pairs.append((msg, tool_msg))
                    i = j
                else:
                    i += 1
            return pairs

        recall_after = collect_pairs(last_user_idx + 1, len(messages))
        recall_before = collect_pairs(0, last_user_idx)

        if n > 0:
            to_remove_pairs = recall_before[:-n] if len(recall_before) > n else []
        else:
            to_remove_pairs = recall_before

        ids_to_delete = []
        for assistant_msg, tool_msg in to_remove_pairs:
            # Sadece recall tool call pair'larını sil
            if (
                assistant_msg.get("tool_calls") is not None
                and len(assistant_msg["tool_calls"]) > 0
                and any(
                    call.get("function", {}).get("name", "").startswith("temporal-memory__recall")
                    for call in assistant_msg["tool_calls"]
                )
            ):
                ids_to_delete.append(assistant_msg["meta"]["id"])
                ids_to_delete.append(tool_msg["meta"]["id"])
            # Aksi halde dokunma

        if ids_to_delete:
            self.delete(ids_to_delete)

        return ids_to_delete


    def create_tool_client(self):
        client = ToolLocalClient(server_id="temporal-memory")
        client.register_tool_auto(
            self.recall,
            name="recall",
            description=(
                "Returns the concatenated contents for multiple keys from temporal memory "
                "as a dictionary mapping each key to its associated text, if any."
            )
        )
        # client.register_tool_auto(
        #     self.memorize,
        #     name="memorize",
        #     description=(
        #         "Given a unique 'key' and a 'msg_id' (the ID of a previous message), "
        #         "saves the content of that message in temporal memory under the given key. "
        #         "Enables selective recall of important conversation segments."
        #     )
        # )
        return client
