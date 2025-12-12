import os

# ========== TELEGRAM CREDENTIALS (Render ke Environment Variables se) ==========
API_ID = int(os.environ.get("API_ID", 0))  # Apna Telegram API ID yahan daalen
API_HASH = os.environ.get("API_HASH", "")  # Apna Telegram API Hash yahan daalen
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")  # Apna Bot Token @BotFather se yahan daalen

# ========== DATABASE ==========
MONGO_DB_URL = os.environ.get("MONGO_DB_URL", "")  # Apna MongoDB connection string yahan daalen

# ========== CHANNEL & OWNER IDs ==========
# Logs bhejne ke liye channel ka ID (Example: -100xxxxxxxxxx)
LOG_CHANNEL_ID = int(os.environ.get("LOG_CHANNEL_ID", -1003286415377))
# Force subscribe channel ka link
FORCE_SUB_CHANNEL = os.environ.get("FORCE_SUB_CHANNEL", "https://t.me/serenaunzipbot")
# Owner ka channel/link
OWNER_CHANNEL = os.environ.get("OWNER_CHANNEL", "https://t.me/technicalserena")
# Owner ke Telegram User IDs (List mein daalen)
OWNER_IDS = [1598576202, 6518065496]  # Yahan apni ID bhi add kar len

# ========== BOT SETTINGS ==========
# Do messages ke beech ka delay (seconds)
SEND_DELAY = 12
# Ek batch mein maximum kitne messages bheje ja sakte hain
MAX_BATCH_LIMIT = 1000
# Session file ko store karne ka folder
SESSION_FOLDER = "user_sessions"
