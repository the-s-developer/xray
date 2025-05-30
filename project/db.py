import motor.motor_asyncio

def get_db():
    client = motor.motor_asyncio.AsyncIOMotorClient("mongodb://mongo:mongo@192.168.99.97:27017")
    return client["xray"]

def setup_db(app):
    app.state.db = get_db()
