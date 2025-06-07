import os
from datetime import datetime
from typing import List, Dict, Any, Optional

import numpy as np
from sentence_transformers import SentenceTransformer
from pymilvus import MilvusClient, DataType

COLLECTION_NAME = os.getenv("MEMORY_COLLECTION", "semantic_memory")
EMBED_MODEL_NAME = os.getenv("EMBED_MODEL", "all-MiniLM-L6-v2")
EMBED_DIM = 384
MILVUS_URI = os.getenv("MILVUS_URI", None)
MILVUS_TOKEN = os.getenv("MILVUS_TOKEN", None)
MILVUS_DB_FILE = os.getenv("MILVUS_DB_FILE", "./memory.db")   # Local DB file path for Milvus Lite
DEFAULT_TTL = int(os.getenv("MEMORY_TTL", "0"))

def _normalize(v: np.ndarray) -> np.ndarray:
    v = v.astype(np.float32)
    norms = np.linalg.norm(v, axis=1, keepdims=True)
    return v / np.clip(norms, a_min=1e-9, a_max=None)

def _timestamp() -> str:
    return datetime.utcnow().isoformat(timespec='milliseconds') + 'Z'

class SemanticMemory:
    """
    SemanticMemory using Milvus 2.5+ API (works with Milvus Lite/Standalone or remote).
    """
    def __init__(
        self,
        collection: str = COLLECTION_NAME,
        model_name: str = EMBED_MODEL_NAME,
        uri: Optional[str] = MILVUS_URI,
        token: Optional[str] = MILVUS_TOKEN,
        db_file: Optional[str] = MILVUS_DB_FILE,           # <--- Local DB!
        ttl_seconds: int = DEFAULT_TTL,
        enable_dynamic_field: bool = False,
        num_shards: int = 1,
        enable_mmap: bool = True,
        consistency_level: str = "Session"
    ):
        self.model = SentenceTransformer(model_name)
        self.collection = collection

        # --- MilvusClient Initialization ---
        # Use local Milvus Lite if db_file is provided and uri is not.
        client_kwargs = {}
        if uri:
            client_kwargs["uri"] = uri
        if token:
            client_kwargs["token"] = token
        if db_file and not uri:
            client_kwargs["db_file"] = db_file
        #self.client = MilvusClient(**client_kwargs)
        self.client = MilvusClient("./memory.db")

        # --- Schema Setup ---
        schema = self.client.create_schema(
            auto_id=True,
            enable_dynamic_field=enable_dynamic_field,
        )
        schema.add_field(field_name="id", datatype=DataType.INT64, is_primary=True)
        schema.add_field(field_name="key", datatype=DataType.VARCHAR, max_length=128)
        schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=EMBED_DIM)
        schema.add_field(field_name="content", datatype=DataType.VARCHAR, max_length=2048)
        schema.add_field(field_name="timestamp", datatype=DataType.VARCHAR, max_length=64)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            index_type="AUTOINDEX",
            metric_type="COSINE"
        )

        properties = {}
        if ttl_seconds > 0:
            properties["collection.ttl.seconds"] = ttl_seconds

        if not self.client.has_collection(self.collection):
            self.client.create_collection(
                collection_name=self.collection,
                schema=schema,
                index_params=index_params,
                properties=properties,
                num_shards=num_shards,
                enable_mmap=enable_mmap,
                consistency_level=consistency_level,
            )
        self.client.load_collection(self.collection)

    def memorize(self, content: str, key: Optional[str] = None) -> str:
        key = (key or f"mem_{int(datetime.utcnow().timestamp()*1000)}").strip()
        encoded = self.model.encode([content])
        if not isinstance(encoded, np.ndarray) or encoded.shape[0] == 0:
            raise ValueError("Failed to encode content for memory.")
        vector = _normalize(encoded)[0].tolist()
        entity = {
            "vector": vector,
            "key": key,
            "content": content,
            "timestamp": _timestamp()
        }
        self.client.insert(collection_name=self.collection, data=[entity])
        return key

    def recall(self, key: str) -> Dict[str, Any]:
        res = self.client.query(
            collection_name=self.collection,
            filter=f"key == '{key}'",
            output_fields=["content", "timestamp", "key"],
            limit=1,
        )
        if res:
            return res[0]
        raise KeyError(f"Key not found: {key}")

    def semantic_search(
        self,
        query: str,
        top_k: int = 5,
        after: Optional[str] = None,
        before: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        if self.count() == 0:
            return []
        encoded = self.model.encode([query])
        if not isinstance(encoded, np.ndarray) or encoded.shape[0] == 0:
            return []
        vector = _normalize(encoded)[0].tolist()
        filter_clauses = []
        if after:
            filter_clauses.append(f"timestamp >= '{after}'")
        if before:
            filter_clauses.append(f"timestamp <= '{before}'")
        filter_str = " and ".join(filter_clauses) if filter_clauses else None
        hits = self.client.search(
            collection_name=self.collection,
            data=[vector],
            limit=top_k,
            output_fields=["key", "content", "timestamp"],
            filter=filter_str,
        )
        results: List[Dict[str, Any]] = []
        for hit in hits[0]:
            results.append({
                "key": hit.entity.get("key"),
                "content": hit.entity.get("content"),
                "timestamp": hit.entity.get("timestamp"),
                "COSINE": float(hit.distance),
            })
        return results

    def forget(self, key: str) -> bool:
        res = self.client.delete(
            collection_name=self.collection,
            filter=f"key == '{key}'",
        )
        if isinstance(res, dict):
            return res.get("delete_count", 0) > 0
        if isinstance(res, list):
            return len(res) > 0
        return False

    def count(self) -> int:
        info = self.client.get_collection_stats(self.collection)
        return info.get("row_count", 0)

    def status(self) -> Dict[str, Any]:
        info = self.client.describe_collection(self.collection)
        fields = [f["name"] for f in info.get("fields", [])]
        row_count = self.count()
        return {
            "record_count": row_count,
            "fields": fields
        }
