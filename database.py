import os
import motor.motor_asyncio
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

MONGODB_URI = os.getenv("MONGODB_URI", "mongodb://localhost:27017")

# MongoDB Client
mongo_client = motor.motor_asyncio.AsyncIOMotorClient(MONGODB_URI)
db = mongo_client["appsuite_db"]
image_cache_collection = db["image_cache"]

async def check_connections():
    try:
        # Check MongoDB
        await mongo_client.admin.command('ping')
        print("✅ MongoDB connected successfully")
    except Exception as e:
        print(f"❌ Connection error: {e}")
