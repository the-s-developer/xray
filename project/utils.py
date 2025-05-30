# project/utils.py
from nanoid import generate

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
NANOID_SIZE = 21

def nanoid(size=NANOID_SIZE):
    return generate(ALPHABET, size)

def drop_mongo_id(doc):
    """MongoDB dökümanından _id alanını siler."""
    if doc and "_id" in doc:
        doc = dict(doc)
        doc.pop("_id", None)
    return doc
# project/utils.py

def strip_mongo_ids(obj):
    """
    Herhangi bir dict/list yapısından _id (ObjectId) ve bson uyumsuz objeleri çıkarır.
    """
    if isinstance(obj, dict):
        return {k: strip_mongo_ids(v) for k, v in obj.items() if k != "_id"}
    elif isinstance(obj, list):
        return [strip_mongo_ids(i) for i in obj]
    else:
        return obj
