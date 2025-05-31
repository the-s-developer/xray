# project/db.py
import motor.motor_asyncio

def get_db(mongo_uri, db_name):
    """
    Parametre ile gelen URI ve db_name ile Motor async db client döndürür.
    """
    client = motor.motor_asyncio.AsyncIOMotorClient(mongo_uri)
    return client[db_name]
