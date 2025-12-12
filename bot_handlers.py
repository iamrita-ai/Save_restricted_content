import asyncio
import os
import logging
import re
import time
from datetime import datetime, timedelta
from bson import ObjectId

from pyrogram import Client, filters, idle
from pyrogram.types import (
    Message, InlineKeyboardMarkup, 
    InlineKeyboardButton, CallbackQuery
)
from pyrogram.errors import FloodWait, UserNotParticipant

from config import Config
from database import (
    add_user, get_user, get_user_session, save_user_session,
    delete_user_session, get_user_setting, update_user_setting,
    add_premium_user, remove_premium_user, check_premium,
    create_batch_task, get_user_tasks, get_active_task,
    update_task_status, cancel_user_tasks, get_user_stats,
    delete_user_settings, get_premium_users
)
from utils import (
    process_batch_messages, send_log_to_channel,
    check_user_access, create_progress_bar, extract_info_from_link
)

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize the bot
bot = Client(
    "file_recovery_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN,
    sleep_threshold=30
)

# Store active user clients
user_clients = {}
active_batch_tasks = {}

# ==================== HELPER FUNCTIONS ====================
async def force_sub_check(user_id):
    """Check if user is in force sub channel"""
    try:
        channel = Config.FORCE_SUB_CHANNEL.replace("https://t.me/", "")
        member = await bot.get_chat_member(channel, user_id)
        return member.status not in ["left", "kicked", None]
    except Exception as e:
        logger.error(f"Force sub check error: {e}")
        return True  # Allow if check fails

async def get_force_sub_keyboard():
    """Keyboard for force subscribe"""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📢 Join Channel", url=Config.FORCE_SUB_CHANNEL)],
        [InlineKeyboardButton("👤 Contact Owner", url=Config.OWNER_LINK)],
        [InlineKeyboardButton("🔄 Check Again", callback_data="check_sub")]
    ])

async def get_premium_keyboard(user_id):
    """Keyboard for premium features"""
    is_premium = check_premium(user_id)
    
    buttons = []
    if not is_premium:
        buttons.append([InlineKeyboardButton("🌟 Get Premium", callback_data="get_premium")])
    
    buttons.append([InlineKeyboardButton("📊 My Stats", callback_data="my_stats")])
    buttons.append([InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu")])
    
    return InlineKeyboardMarkup(buttons)

async def get_main_keyboard():
    """Main menu keyboard"""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📦 Batch Recovery", callback_data="batch_menu"),
            InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu")
        ],
        [
            InlineKeyboardButton("📊 My Stats", callback_data="my_stats"),
            InlineKeyboardButton("🌟 Premium", callback_data="premium_info")
        ],
        [
            InlineKeyboardButton("🆘 Help", callback_data="help_menu"),
            InlineKeyboardButton("👤 Profile", callback_data="my_profile")
        ]
    ])

async def get_settings_keyboard(user_id):
    """Settings menu keyboard"""
    set_chat_id = get_user_setting(user_id, "set_chat_id", "Not Set")
    button_text = get_user_setting(user_id, "button_text", "Serena")
    has_session = bool(get_user_session(user_id))
    
    keyboard = [
        [InlineKeyboardButton(f"📨 Set Chat ID: {set_chat_id}", callback_data="set_chat_id")],
        [InlineKeyboardButton(f"🔘 Button Text: {button_text}", callback_data="toggle_button")],
    ]
    
    if has_session:
        keyboard.append([InlineKeyboardButton("🚪 Logout Session", callback_data="logout_session")])
    
    keyboard.append([InlineKeyboardButton("🔄 Reset Settings", callback_data="reset_settings")])
    keyboard.append([InlineKeyboardButton("🔙 Back to Main", callback_data="main_menu")])
    
    return InlineKeyboardMarkup(keyboard)

async def send_status_update(user_id, current, total, successful, failed):
    """Send progress update to user"""
    try:
        progress_bar = create_progress_bar(current, total)
        status_text = (
            f"📊 **Batch Progress**\n\n"
            f"{progress_bar}\n"
            f"✅ Successful: {successful}\n"
            f"❌ Failed: {failed}\n"
            f"📁 Processed: {current}/{total}\n"
            f"⏱️ Remaining: ~{format_time((total-current)*Config.SLEEP_TIME)}"
        )
        
        await bot.send_message(user_id, status_text)
    except Exception as e:
        logger.error(f"Status update error: {e}")
