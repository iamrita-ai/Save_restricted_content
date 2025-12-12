from pymongo import MongoClient
from config import Config
import datetime

client = MongoClient(Config.MONGO_URL)
db = client["telegram_file_bot"]

# Collections
users_collection = db["users"]
sessions_collection = db["sessions"]
settings_collection = db["settings"]
batch_tasks_collection = db["batch_tasks"]
premium_users_collection = db["premium_users"]

# User Functions
def add_user(user_id, name):
    """Add new user to database"""
    user_data = {
        "user_id": user_id,
        "name": name,
        "join_date": datetime.datetime.now(),
        "is_premium": False,
        "premium_expiry": None,
        "last_active": datetime.datetime.now()
    }
    users_collection.update_one(
        {"user_id": user_id},
        {"$setOnInsert": user_data},
        upsert=True
    )
    return True

def get_user(user_id):
    """Get user data"""
    return users_collection.find_one({"user_id": user_id})

def update_user_last_active(user_id):
    """Update user last active time"""
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"last_active": datetime.datetime.now()}}
    )

# Session Functions
def get_user_session(user_id):
    """Get user session string"""
    session_data = sessions_collection.find_one({"user_id": user_id})
    return session_data.get("session_string") if session_data else None

def save_user_session(user_id, session_string):
    """Save user session string"""
    sessions_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "session_string": session_string, 
            "updated_at": datetime.datetime.now(),
            "login_date": datetime.datetime.now()
        }},
        upsert=True
    )
    return True

def delete_user_session(user_id):
    """Delete user session (logout)"""
    result = sessions_collection.delete_one({"user_id": user_id})
    return result.deleted_count > 0

def get_all_sessions():
    """Get all sessions"""
    return list(sessions_collection.find({}))

# Settings Functions
def get_user_setting(user_id, key, default=None):
    """Get user setting"""
    setting_data = settings_collection.find_one({"user_id": user_id, "key": key})
    return setting_data.get("value", default) if setting_data else default

def update_user_setting(user_id, key, value):
    """Update user setting"""
    settings_collection.update_one(
        {"user_id": user_id, "key": key},
        {"$set": {"value": value, "updated_at": datetime.datetime.now()}},
        upsert=True
    )
    return True

def delete_user_settings(user_id):
    """Delete all user settings"""
    result = settings_collection.delete_many({"user_id": user_id})
    return result.deleted_count

# Premium Functions
def add_premium_user(user_id, days):
    """Add premium to user"""
    expiry_date = datetime.datetime.now() + datetime.timedelta(days=days)
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {
            "is_premium": True, 
            "premium_expiry": expiry_date,
            "premium_added": datetime.datetime.now()
        }}
    )
    
    # Also add to premium collection
    premium_data = {
        "user_id": user_id,
        "days": days,
        "added_date": datetime.datetime.now(),
        "expiry_date": expiry_date,
        "added_by": "admin"
    }
    premium_users_collection.update_one(
        {"user_id": user_id},
        {"$set": premium_data},
        upsert=True
    )
    return True

def remove_premium_user(user_id):
    """Remove premium from user"""
    users_collection.update_one(
        {"user_id": user_id},
        {"$set": {"is_premium": False, "premium_expiry": None}}
    )
    premium_users_collection.delete_one({"user_id": user_id})
    return True

def check_premium(user_id):
    """Check if user has active premium"""
    user = users_collection.find_one({"user_id": user_id})
    if user and user.get("is_premium", False):
        expiry = user.get("premium_expiry")
        if expiry and expiry > datetime.datetime.now():
            return True
        else:
            # Premium expired
            remove_premium_user(user_id)
    return False

def get_premium_users():
    """Get all premium users"""
    return list(users_collection.find({"is_premium": True}))

# Batch Task Functions
def create_batch_task(user_id, chat_id, start_msg_id, count, target_chat_id):
    """Create new batch task"""
    from bson import ObjectId
    task_id = ObjectId()
    
    task_data = {
        "_id": task_id,
        "user_id": user_id,
        "chat_id": chat_id,
        "start_msg_id": start_msg_id,
        "count": count,
        "target_chat_id": target_chat_id,
        "status": "queued",
        "progress": 0,
        "successful": 0,
        "failed": 0,
        "created_at": datetime.datetime.now(),
        "updated_at": datetime.datetime.now()
    }
    
    batch_tasks_collection.insert_one(task_data)
    return task_id

def get_user_tasks(user_id):
    """Get all tasks for user"""
    return list(batch_tasks_collection.find(
        {"user_id": user_id},
        sort=[("created_at", -1)]
    ))

def get_active_task(user_id):
    """Get active task for user"""
    return batch_tasks_collection.find_one({
        "user_id": user_id,
        "status": {"$in": ["queued", "processing", "paused"]}
    })

def update_task_status(task_id, status, progress=0, successful=0, failed=0):
    """Update task status"""
    batch_tasks_collection.update_one(
        {"_id": task_id},
        {"$set": {
            "status": status,
            "progress": progress,
            "successful": successful,
            "failed": failed,
            "updated_at": datetime.datetime.now()
        }}
    )
    return True

def cancel_user_tasks(user_id):
    """Cancel all user tasks"""
    result = batch_tasks_collection.update_many(
        {
            "user_id": user_id,
            "status": {"$in": ["queued", "processing", "paused"]}
        },
        {"$set": {"status": "cancelled", "updated_at": datetime.datetime.now()}}
    )
    return result.modified_count

# Stats Functions
def get_user_stats(user_id):
    """Get user statistics"""
    total_tasks = batch_tasks_collection.count_documents({"user_id": user_id})
    completed_tasks = batch_tasks_collection.count_documents({
        "user_id": user_id,
        "status": "completed"
    })
    
    # Calculate total messages processed
    pipeline = [
        {"$match": {"user_id": user_id, "status": "completed"}},
        {"$group": {
            "_id": None,
            "total_messages": {"$sum": "$count"},
            "successful": {"$sum": "$successful"},
            "failed": {"$sum": "$failed"}
        }}
    ]
    
    stats = list(batch_tasks_collection.aggregate(pipeline))
    if stats:
        return {
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "total_messages": stats[0].get("total_messages", 0),
            "successful_messages": stats[0].get("successful", 0),
            "failed_messages": stats[0].get("failed", 0)
        }
    
    return {
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "total_messages": 0,
        "successful_messages": 0,
        "failed_messages": 0
    }
