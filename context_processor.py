# context_processor.py

from typing import List, Dict, Any

class ContextProcessor:
    def refine(self, messages: List[Dict[str, Any]], **kwargs) -> List[Dict[str, Any]]:
        """
        Mesaj listesini alır, işleyip yine mesaj listesi döndürür.
        Override edilmelidir.
        """
        raise NotImplementedError("refine method must be implemented by subclasses.")
