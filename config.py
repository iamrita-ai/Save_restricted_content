import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram API Credentials
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    
    # MongoDB URL
    MONGO_URL = os.environ.get("MONGO_URL", "")
    
    # Owner IDs (Hardcoded as per your requirement)
    OWNER_IDS = [1598576202, 6518065496]
    
    # Logs Channel
    LOG_CHANNEL = -1003286415377
    
    # Force Subscribe Channel और Owner Link
    FORCE_SUB_CHANNEL = "https://t.me/serenaunzipbot"
    OWNER_LINK = "https://t.me/technicalserena"
    
    # Batch Processing Settings
    BATCH_LIMIT = 1000
    SLEEP_TIME = 12  # सेकंड में
    
    # Bot Settings
    BOT_NAME = "File Recovery Bot"
    VERSION = "2.0"
    
    # Premium Settings
    PREMIUM_DAYS = 30
