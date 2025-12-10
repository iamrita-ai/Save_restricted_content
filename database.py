from pymongo import MongoClient
from config import Config
import datetime

client = MongoClient(Config.MONGO_URL)
db = client["telegram_file_bot"]

# Collections (Database Tables)
users_collection = db["users"]
sessions_collection = db["sessions"]
settings_collection = db["settings"]
batch_tasks_collection = db["batch_tasks"]

def add_user(user_id, name):
    """नए user को database में add करता है।"""
    user_data = {
        "user_id": user_id,
        "name": name,
        "join_date": datetime.datetime.now(),
        "is_premium": False,
        "premium_expiry": None
    }
    users_collection.update_one(
        {"user_id": user_id},
        {"$setOnInsert": user_data},
        upsert=True
    )

def get_user_session(user_id):
    """User का Telegram session string database से fetch करता है।"""
    session_data = sessions_collection.find_one({"user_id": user_id})
    return session_data.get("session_string") if session_data else None

def save_user_session(user_id, session_string):
    """User का Telegram session string database में save करता है।"""
    sessions_collection.update_one(
        {"user_id": user_id},
        {"$set": {"session_string": session_string, "updated_at": datetime.datetime.now()}},
        upsert=True
    )

def get_user_setting(user_id, key, default=None):
    """User की किसी setting को fetch करता है।"""
    setting_data = settings_collection.find_one({"user_id": user_id, "key": key})
    return setting_data.get("value", default) if setting_data else default

def update_user_setting(user_id, key, value):
    """User की setting update करता है।"""
    settings_collection.update_one(
        {"user_id": user_id, "key": key},
        {"$set": {"value": value, "updated_at": datetime.datetime.now()}},
        upsert=True
    )

def add_premium_user(user_id, days):
    """User को premium बनाता है और expiry date सेट करता है।"""
    expiry_date = datetime.datetime.now() + datetime.timedelta(days=days)
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"is_premium": True, "premium_expiry": expiry_date}}
    )

def remove_premium_user(user_id):
    """User से premium status हटाता है।"""
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"is_premium": False, "premium_expiry": None}}
  )
