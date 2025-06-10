# temporal_memory.py

from context_memory import ContextMemory
from typing import List, Dict, Any, Optional
from tool_local_client import ToolLocalClient
import logging

class TemporalMemory():
    """
    TemporalMemory, önceki mesajlara dayalı olarak içerikleri hafızaya yazan ve
    anahtarlarla bu içerikleri geri çağıran bir yardımcı bellek sistemidir.
    """

    def __init__(
        self,
        context_memory
        
    ):
        self.data: Dict[str, str] = {}
        self.memory=context_memory

    def memorize(self, key: str, msg_id: str) -> str:
        """
        msg_id ile daha önce kaydedilmiş bir mesajı bulur, content'ini alır
        ve verilen key altında hafızaya ekler.
        """
        if not key:
            raise ValueError("key is empty")
        if not msg_id:
            raise ValueError("msg_id is empty")

        # Mesajı bul
        msg = self.memory.find_message(msg_id)
        if not msg:
            raise ValueError(f"Message with id {msg_id} not found.")
        content = msg.get("content")
        if not content:
            raise ValueError("content is None or empty in the found message.")

        self.data[key] = content

        logging.info(f"[TM] memorize: key={key}, total length={len(self.data[key])}")
        return "success"

    async def recall(self, keys: List[str]) -> Dict[str, Any]:
        """
        Verilen key listesine karşılık gelen içerikleri döndürür.
        """
        return {key: self.data.get(key, None) for key in keys}

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
        client.register_tool_auto(
            self.memorize,
            name="memorize",
            description=(
                "Given a unique 'key' and a 'msg_id' (the ID of a previous message), "
                "saves the content of that message in temporal memory under the given key. "
                "Enables selective recall of important conversation segments."
            )
        )
        return client
