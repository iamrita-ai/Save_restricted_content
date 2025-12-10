import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram API Credentials (Render Environment Variables से लोड होंगे)
    API_ID = int(os.environ.get("API_ID", 0))
    API_HASH = os.environ.get("API_HASH", "")
    BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
    
    # MongoDB URL (Render Environment Variable से लोड होगा)
    MONGO_URL = os.environ.get("MONGO_URL", "")
    
    # Owner और Logs Channel के IDs (Hardcoded, आपके दिए गए अनुसार)
    OWNER_IDS = [1598576202, 6518065496]
    LOG_CHANNEL = int(os.environ.get("LOG_CHANNEL", -1003286415377))
    
    # Force Subscribe Channel और Owner Link
    FORCE_SUB_CHANNEL = "https://t.me/serenaunzipbot"
    OWNER_LINK = "https://t.me/technicalserena"
    
    # Batch Processing सेटिंग्स
    BATCH_LIMIT = 1000
    SLEEP_TIME = 12  # सेकंड में
