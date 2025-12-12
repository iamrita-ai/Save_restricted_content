# tools.py
import os
from datetime import datetime
from pymongo import MongoClient
import gridfs
from bson import ObjectId

# MongoDB connection
MONGO_URL = os.environ.get("MONGO_URL")
client = MongoClient(MONGO_URL)
db = client["serena_file_bot"]
fs = gridfs.GridFS(db)

# Collections
users_col = db["users"]
premium_col = db["premium_users"]
settings_col = db["settings"]
logs_col = db["logs"]

async def save_user_session(user_id, session_string):
    """Save user session string to database"""
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {
            "session": session_string, 
            "updated_at": datetime.now(),
            "last_activity": datetime.now()
        }},
        upsert=True
    )
    return True

async def get_user_session(user_id):
    """Retrieve user session from database"""
    user = users_col.find_one({"user_id": user_id})
    return user.get("session") if user else None

async def delete_temp_file(file_path):
    """Delete temporary file from server"""
    try:
        # Simulate file deletion
        # In actual implementation, this would delete real files
        print(f"Simulated file deletion: {file_path}")
        return True
    except:
        return False

async def save_log_to_channel(bot, log_channel, log_text):
    """Save log to MongoDB logs collection"""
    try:
        logs_col.insert_one({
            "text": log_text,
            "timestamp": datetime.now(),
            "type": "bot_log",
            "channel_id": log_channel
        })
        return True
    except Exception as e:
        print(f"Failed to save log to DB: {e}")
        return False

async def is_premium_user(user_id):
    """Check if user has active premium subscription"""
    premium = premium_col.find_one({
        "user_id": user_id,
        "expiry": {"$gt": datetime.now()}
    })
    return premium is not None

async def add_premium_user(user_id, expiry_date):
    """Add premium user with expiry date"""
    premium_col.update_one(
        {"user_id": user_id},
        {"$set": {"expiry": expiry_date, "added_on": datetime.now()}},
        upsert=True
    )
    return True

async def remove_premium_user(user_id):
    """Remove user from premium list"""
    premium_col.delete_one({"user_id": user_id})
    return True

async def update_setting(user_id, key, value):
    """Update user setting"""
    settings_col.update_one(
        {"user_id": user_id},
        {"$set": {key: value, "updated_at": datetime.now()}},
        upsert=True
    )
    return True

async def get_setting(user_id, key):
    """Get user setting"""
    setting = settings_col.find_one({"user_id": user_id})
    return setting.get(key) if setting else None

async def save_file_to_gridfs(file_data, filename, metadata=None):
    """Save file to GridFS for logging/storage"""
    file_id = fs.put(
        file_data,
        filename=filename,
        metadata=metadata or {},
        uploadDate=datetime.now()
    )
    return str(file_id)

async def get_file_from_gridfs(file_id):
    """Retrieve file from GridFS"""
    try:
        file_data = fs.get(ObjectId(file_id))
        return file_data.read()
    except:
        return None
