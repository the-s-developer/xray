# project/utils.py
from nanoid import generate
from datetime import datetime
from bson import ObjectId

ALPHABET = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
NANOID_SIZE = 21

def nanoid(size=NANOID_SIZE):
    return generate(ALPHABET, size)

def now_iso():
    return datetime.utcnow().isoformat()

def drop_mongo_id(doc):
    if not doc:
        return doc
    doc = dict(doc)
    doc.pop('_id', None)
    # Eğer başka ObjectId varsa, onları da string'e çevir
    for k, v in list(doc.items()):
        if isinstance(v, ObjectId):
            doc[k] = str(v)
    return doc

def drop_mongo_ids(docs):
    return [drop_mongo_id(doc) for doc in docs]
def strip_mongo_ids(obj):
    if isinstance(obj, dict):
        return {k: strip_mongo_ids(v) for k, v in obj.items() if k != "_id"}
    elif isinstance(obj, list):
        return [strip_mongo_ids(i) for i in obj]
    else:
        return obj

