# temporal_memory.py

from context_memory import ContextMemory, nanoid
from typing import List, Dict, Any, Optional

INSTRUCTION_PROMPT = """
**Rules:**
- If a tool response exceeds 4096 characters, it will be trimmed and marked with `[temporal-memory_recall([key])]`. Use the key to retrieve the full content.
- always use temporal memory recall if you need data
"""

class TemporalMemory(ContextMemory):
    def __init__(
        self, 
        system_prompt, 
        massive_cycle: int = 3,     # Trim için gereken minimum cycle
        review_cycle: int = 3,      # Review mesaj silme cycle'ı
        max_size: int = 4096,
        skip_last_user_responses: bool = True  
    ):
        system_prompt += INSTRUCTION_PROMPT
        super().__init__(system_prompt=system_prompt)
        self.temporal_data: Dict[str, str] = {}
        self.MASSIVE_RESPONSE_CYCLE_LIMIT = massive_cycle
        self.REVIEW_RESPONSE_CYCLE_LIMIT = review_cycle
        self.MAX_SIZE = max_size
        self.skip_last_user_responses = skip_last_user_responses  # 🔹 Yeni alan

    async def recall(self, keys: List[str]) -> Dict[str, Any]:
        return {key: self.temporal_data.get(key, None) for key in keys}

    def cycle(self) ->  List[Dict[str, Any]]:
        super().cycle()
        #self._process_tool_responses()
        return self.snapshot()

    def _process_tool_responses(self) -> None:
            exclude_ids = set()
            if self.skip_last_user_responses:
                last_user_id = self._get_last_user_id()
                if last_user_id:
                    found = False
                    for msg in self.snapshot():
                        if msg["meta"]["id"] == last_user_id:
                            found = True
                            continue
                        if found and msg["role"] in ("assistant", "tool") and msg.get("meta", {}).get("parent_id") == last_user_id:
                            exclude_ids.add(msg["meta"]["id"])
                        elif found and msg["role"] == "user":
                            break  # Sonraki user geldi, dur

            for msg in self.snapshot():
                if msg["meta"]["id"] in exclude_ids:
                    continue
                if self._should_trim(msg):
                    self._trim_tool_response(msg)
                elif self._should_delete_review(msg):
                    self._delete_review_response(msg)

    def _should_trim(self, msg: Dict[str, Any]) -> bool:
        return (
            msg.get("role") == "tool"
            and len(msg.get("content", "")) > self.MAX_SIZE
            and msg.get("meta", {}).get("cycle", 0) >= self.MASSIVE_RESPONSE_CYCLE_LIMIT
        )

    def _should_delete_review(self, msg: Dict[str, Any]) -> bool:
        return (
            msg.get("role") == "tool"
            and msg.get("meta", {}).get("review", False)
            and msg.get("meta", {}).get("cycle", 0) >= self.REVIEW_RESPONSE_CYCLE_LIMIT
        )

    def _trim_tool_response(self, msg: Dict[str, Any]) -> None:
        key = nanoid(10)
        self.temporal_data[key] = msg["content"]
        trimmed = msg["content"][:512] + f"\n\n---\n [ rest of content is trimmed, ref: temporal memory recall([key:{key}])]"
        self.update_content(msg["meta"]["id"], trimmed)

    def _delete_review_response(self, msg: Dict[str, Any]) -> None:
        self.delete([msg["meta"]["id"]])

    def create_tool_client(self):
        from tool_local_client import ToolLocalClient
        client = ToolLocalClient(server_id="temporal-memory")
        client.register_tool_auto(
            self.recall,
            name="recall",
            description="Returns the full content of tool responses previously trimmed into temporal memory."
        )
        return client
