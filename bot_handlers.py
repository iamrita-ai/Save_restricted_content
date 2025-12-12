# bot_handlers.py - PART 1 of 2
import os
import asyncio
import re
from datetime import datetime, timedelta
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from pyrogram.errors import FloodWait, RPCError
import pymongo
from tools import (
    save_user_session, get_user_session, delete_temp_file,
    save_log_to_channel, is_premium_user, add_premium_user,
    remove_premium_user, update_setting, get_setting
)

# ========== CONFIGURATION ==========
# These will be set as environment variables on Render
API_ID = int(os.environ.get("API_ID"))
API_HASH = os.environ.get("API_HASH")
BOT_TOKEN = os.environ.get("BOT_TOKEN")
MONGO_URL = os.environ.get("MONGO_URL")  # Use your first MongoDB URL
OWNER_IDS = [1598576202, 6518065496]  # Your Owner IDs
LOG_CHANNEL = -1003286415377  # Your Log Channel ID
FORCE_SUB_CHANNEL = "serenaunzipbot"  # Without '@'
OWNER_USERNAME = "technicalserena"  # Without '@'

# Initialize MongoDB Client
try:
    mongo_client = pymongo.MongoClient(MONGO_URL)
    db = mongo_client["serena_file_bot"]
    users_col = db["users"]
    premium_col = db["premium_users"]
    settings_col = db["settings"]
    batch_col = db["batch_tasks"]
    print("Connected to MongoDB successfully.")
except Exception as e:
    print(f"MongoDB Connection Error: {e}")
    # Exit if DB connection fails
    raise

# Initialize the Bot Client
bot = Client(
    "serena_file_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=50  # Increased for handling batch tasks
)

# Store active user tasks for cancellation
user_tasks = {}

# ========== HELPER FUNCTIONS ==========
async def check_force_sub(user_id):
    """Check if user is subscribed to the force channel."""
    try:
        user = await bot.get_chat_member(f"@{FORCE_SUB_CHANNEL}", user_id)
        if user.status in ["member", "administrator", "creator"]:
            return True
    except Exception:
        pass
    return False

async def send_log(message, log_type="INFO"):
    """Send logs to the log channel."""
    try:
        log_text = f"**{log_type}**\n"
        log_text += f"**User:** `{message.from_user.id}`\n"
        if message.from_user.username:
            log_text += f"**Username:** @{message.from_user.username}\n"
        log_text += f"**Command:** `{message.text}`\n"
        log_text += f"**Time:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`"
        await bot.send_message(LOG_CHANNEL, log_text)
        # Also save to MongoDB via tools
        await save_log_to_channel(bot, LOG_CHANNEL, log_text)
    except Exception as e:
        print(f"Log sending failed: {e}")

# ========== COMMAND HANDLERS ==========
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    """Handler for /start command."""
    user_id = message.from_user.id
    await send_log(message, "START_CMD")
    
    # Force subscription check
    if not await check_force_sub(user_id):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL}"),
            InlineKeyboardButton("🛠 Contact Owner", url=f"https://t.me/{OWNER_USERNAME}")
        ]])
        await message.reply_photo(
            photo="https://telegra.ph/file/1a72b6072e5c4c739e9c0.jpg",  # Default image
            caption="**👋 Welcome to SERENA File Recovery Bot!**\n\n"
                    "⚠️ **You must join our channel to use this bot.**\n"
                    "Join the channel below and then press /start again.",
            reply_markup=keyboard
        )
        return
    
    # Welcome message for subscribed users
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL}"),
        InlineKeyboardButton("🛠 Contact Owner", url=f"https://t.me/{OWNER_USERNAME}")
    ]])
    
    await message.reply_photo(
        photo="https://telegra.ph/file/1a72b6072e5c4c739e9c0.jpg",
        caption="**🤖 Welcome to SERENA File Recovery Bot!**\n\n"
                "**Brand:** SERENA\n"
                "**Purpose:** Recover files from your lost Telegram account's channels.\n\n"
                "**Available Commands:**\n"
                "• /login - Login with your phone number\n"
                "• /batch - Start batch file recovery\n"
                "• /setting - Configure bot settings\n"
                "• /status - Check current task status\n"
                "• /cancel - Cancel ongoing task\n"
                "• /help - Get detailed guide\n\n"
                "**Premium Features:**\n"
                "• Increased batch limits\n"
                "• Priority processing\n"
                "• Direct channel forwarding\n",
        reply_markup=keyboard
    )

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client, message: Message):
    """Handler for /help command."""
    help_text = """
**📖 SERENA Bot Guide**

**1. LOGIN PROCESS:**
   • Use /login to start
   • Enter your phone number (with country code, e.g., +91XXXXXXXXXX)
   • Enter the OTP received on Telegram
   • You're now logged in!

**2. RECOVER FILES:**
   • Use /batch with channel link
   • Example: `/batch https://t.me/channel_name/123`
   • Enter number of messages to fetch
   • Bot will send files to your DM

**3. SETTINGS:**
   • /setting - Configure options
   • Set default chat ID for direct forwarding
   • Change button texts
   • Reset settings if needed

**4. OTHER COMMANDS:**
   • /status - Check current task
   • /cancel - Stop ongoing task
   • /addpremium - Owner only: Add premium user
   • /removepremium - Owner only: Remove premium user

**⚠️ NOTES:**
   • Bot sleeps 12s between messages to avoid flood
   • Max batch limit: 1000 messages
   • Files are deleted from server after sending
   • All logs saved in log channel
   """
    await message.reply(help_text)
    await send_log(message, "HELP_CMD")

@bot.on_message(filters.command("login") & filters.private)
async def login_command(client, message: Message):
    """Handler for /login command to authenticate user."""
    user_id = message.from_user.id
    await send_log(message, "LOGIN_CMD")
    
    # Check if already logged in
    session = await get_user_session(user_id)
    if session:
        await message.reply("✅ You are already logged in!\n"
                          "Use /batch to start file recovery.")
        return
    
    # Ask for phone number
    await message.reply(
        "**📱 Login Process Started**\n\n"
        "Please send your phone number in international format:\n"
        "**Example:** `+91XXXXXXXXXX`\n\n"
        "Type /cancel to abort login."
    )
    
    # Store that user is in login state
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"login_state": "awaiting_phone"}},
        upsert=True
    )

@bot.on_message(filters.command("status") & filters.private)
async def status_command(client, message: Message):
    """Handler for /status command."""
    user_id = message.from_user.id
    task = user_tasks.get(user_id)
    
    if task and not task.done():
        status_msg = "**🔄 Task Status:** RUNNING\n"
        status_msg += "• Task is currently in progress\n"
        status_msg += "• Use /cancel to stop the task"
    else:
        status_msg = "**✅ Task Status:** IDLE\n"
        status_msg += "• No active tasks running\n"
        status_msg += "• Use /batch to start a new task"
    
    # Add premium status
    premium = await is_premium_user(user_id)
    status_msg += f"\n\n**👑 Premium Status:** {'ACTIVE' if premium else 'INACTIVE'}"
    
    await message.reply(status_msg)
    await send_log(message, "STATUS_CMD")
