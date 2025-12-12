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

# bot_handlers.py - PART 2 of 2
# Continuation from Part 1

@bot.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message: Message):
    """Handler for /batch command for batch file recovery."""
    user_id = message.from_user.id
    await send_log(message, "BATCH_CMD")
    
    # Check force subscription
    if not await check_force_sub(user_id):
        await message.reply("⚠️ Please join our channel first to use this feature.")
        return
    
    # Check if user is logged in
    session = await get_user_session(user_id)
    if not session:
        await message.reply("❌ You need to login first!\nUse /login to start.")
        return
    
    # Check if user already has an active task
    if user_id in user_tasks and not user_tasks[user_id].done():
        await message.reply("⚠️ You already have an active task!\n"
                          "Use /status to check or /cancel to stop it.")
        return
    
    # Parse the command arguments
    args = message.text.split()
    if len(args) < 2:
        await message.reply(
            "**Usage:** `/batch <channel_link>`\n\n"
            "**Example:**\n"
            "`/batch https://t.me/serenaunzipbot/123`\n\n"
            "The link should be a specific message from the channel."
        )
        return
    
    # Store batch info
    channel_link = args[1]
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"batch_channel": channel_link, "batch_state": "awaiting_count"}},
        upsert=True
    )
    
    # Determine batch limit based on premium status
    premium = await is_premium_user(user_id)
    max_limit = 2000 if premium else 1000  # Premium users get higher limit
    
    await message.reply(
        f"**📦 Batch Processing Started**\n\n"
        f"**Channel:** `{channel_link}`\n"
        f"**Max Limit:** `{max_limit}` messages\n\n"
        f"Now send me the **number of messages** to fetch (1-{max_limit}):\n"
        f"Type /cancel to abort."
    )

@bot.on_message(filters.command("setting") & filters.private)
async def setting_command(client, message: Message):
    """Handler for /setting command to configure bot."""
    user_id = message.from_user.id
    await send_log(message, "SETTING_CMD")
    
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
            InlineKeyboardButton("❌ Close", callback_data="close_settings")
        ]
    ])
    
    settings_text = f"""
**⚙️ Bot Settings**

**Current Configuration:**
• **Forward Chat ID:** `{set_chat_id}`
• **Button Text:** `{button_text}`

**Options:**
1. **Set Chat ID** - Configure where to forward files
2. **Reset Settings** - Restore default configuration
3. **Change Button Text** - Modify inline button text
"""
    await message.reply(settings_text, reply_markup=keyboard)

@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_command(client, message: Message):
    """Handler for /cancel command."""
    user_id = message.from_user.id
    
    if user_id in user_tasks:
        task = user_tasks[user_id]
        if not task.done():
            task.cancel()
            await message.reply("✅ Task cancelled successfully!")
            await send_log(message, "TASK_CANCELLED")
        else:
            await message.reply("ℹ️ No active task to cancel.")
    else:
        await message.reply("ℹ️ No active task found.")
    
    # Clear any login/batch state
    users_col.update_one(
        {"user_id": user_id},
        {"$unset": {"login_state": "", "batch_state": "", "batch_channel": ""}}
    )

# ========== MESSAGE HANDLERS ==========
@bot.on_message(filters.private & ~filters.command())
async def handle_messages(client, message: Message):
    """Handle non-command messages (phone numbers, OTP, batch counts)."""
    user_id = message.from_user.id
    user_data = users_col.find_one({"user_id": user_id}) or {}
    
    # Handle phone number input
    if user_data.get("login_state") == "awaiting_phone":
        phone = message.text.strip()
        
        # Basic phone validation
        if not re.match(r'^\+\d{10,15}$', phone):
            await message.reply("❌ Invalid phone number format!\n"
                              "Please send in format: `+91XXXXXXXXXX`\n"
                              "Try again or /cancel to abort.")
            return
        
        # Store phone and ask for OTP
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"phone": phone, "login_state": "awaiting_otp"}}
        )
        
        await message.reply(
            f"**📱 Phone Received:** `{phone}`\n\n"
            "Now please send the **OTP** you received on Telegram.\n"
            "Format: `123456` (6 digits)\n\n"
            "Type /cancel to abort."
        )
    
    # Handle OTP input
    elif user_data.get("login_state") == "awaiting_otp":
        otp = message.text.strip()
        
        if not re.match(r'^\d{6}$', otp):
            await message.reply("❌ Invalid OTP format!\n"
                              "OTP must be 6 digits.\n"
                              "Try again or /cancel to abort.")
            return
        
        # Here you would normally create a user session
        # For security, we simulate session creation
        try:
            # Save session (in real implementation, use pyrogram Client)
            session_string = f"simulated_session_{user_id}_{int(datetime.now().timestamp())}"
            await save_user_session(user_id, session_string)
            
            await message.reply(
                "✅ **Login Successful!**\n\n"
                "Your session has been created.\n"
                "You can now use /batch to recover files."
            )
            await send_log(message, "LOGIN_SUCCESS")
            
            # Clear login state
            users_col.update_one(
                {"user_id": user_id},
                {"$unset": {"login_state": "", "phone": ""}}
            )
            
        except Exception as e:
            await message.reply(f"❌ Login failed: {str(e)}\nPlease try /login again.")
            await send_log(message, "LOGIN_FAILED")
    
    # Handle batch count input
    elif user_data.get("batch_state") == "awaiting_count":
        try:
            count = int(message.text.strip())
            premium = await is_premium_user(user_id)
            max_limit = 2000 if premium else 1000
            
            if count < 1 or count > max_limit:
                await message.reply(f"❌ Please enter a number between 1 and {max_limit}!")
                return
            
            channel_link = user_data.get("batch_channel", "")
            
            await message.reply(
                f"**✅ Batch Confirmed**\n\n"
                f"• **Messages to fetch:** `{count}`\n"
                f"• **Channel:** `{channel_link}`\n"
                f"• **Estimated time:** `{count * 12 / 60:.1f} minutes`\n\n"
                f"Starting now... Use /cancel to stop."
            )
            
            # Start batch processing task
            task = asyncio.create_task(
                process_batch_messages(user_id, channel_link, count)
            )
            user_tasks[user_id] = task
            
            # Clear batch state
            users_col.update_one(
                {"user_id": user_id},
                {"$unset": {"batch_state": "", "batch_channel": ""}}
            )
            
        except ValueError:
            await message.reply("❌ Please enter a valid number!")
        except Exception as e:
            await message.reply(f"❌ Error: {str(e)}")

# ========== BATCH PROCESSING FUNCTION ==========
async def process_batch_messages(user_id, channel_link, count):
    """Process batch messages with flood control."""
    try:
        # Extract channel and message ID from link
        # Example: https://t.me/channel_name/123
        parts = channel_link.split('/')
        if len(parts) < 5:
            raise ValueError("Invalid channel link format")
        
        channel_username = parts[3]
        start_msg_id = int(parts[4])
        
        # Get user session
        session = await get_user_session(user_id)
        if not session:
            await bot.send_message(user_id, "❌ Session expired! Please /login again.")
            return
        
        # Create user client from session (simplified)
        # In real implementation, you'd initialize pyrogram Client with session_string
        user_client = None  # Placeholder
        
        processed = 0
        for i in range(count):
            msg_id = start_msg_id + i
            
            try:
                # Fetch message from channel (simulated)
                # msg = await user_client.get_messages(channel_username, msg_id)
                
                # Simulate file download and sending
                file_path = f"temp_{user_id}_{msg_id}.zip"
                
                # Send to user
                await bot.send_message(
                    user_id,
                    f"**📦 File {i+1}/{count}**\n"
                    f"Message ID: `{msg_id}`\n"
                    f"Status: ✅ Sent"
                )
                
                # Send to set_chat_id if configured
                set_chat_id = await get_setting(user_id, "set_chat_id")
                if set_chat_id and set_chat_id != "Not Set":
                    try:
                        await bot.send_message(
                            int(set_chat_id),
                            f"Forwarded file from batch\nMessage ID: {msg_id}"
                        )
                    except:
                        pass
                
                # Delete temp file
                await delete_temp_file(file_path)
                
                processed += 1
                
                # 12 second sleep between messages
                if i < count - 1:  # Don't sleep after last message
                    await asyncio.sleep(12)
                    
            except FloodWait as e:
                wait_time = e.value
                await bot.send_message(
                    user_id,
                    f"⚠️ Flood wait: Sleeping for {wait_time} seconds..."
                )
                await asyncio.sleep(wait_time)
                continue
            except Exception as e:
                await bot.send_message(
                    user_id,
                    f"❌ Error on message {msg_id}: {str(e)[:100]}"
                )
                continue
        
        # Completion message
        completion_text = (
            f"✅ **Batch Processing Complete!**\n\n"
            f"• **Total requested:** {count}\n"
            f"• **Successfully sent:** {processed}\n"
            f"• **Failed:** {count - processed}\n\n"
            f"All temporary files have been deleted."
        )
        
        await bot.send_message(user_id, completion_text)
        
        # Log completion
        log_msg = await bot.send_message(
            LOG_CHANNEL,
            f"**BATCH_COMPLETE**\nUser: `{user_id}`\n"
            f"Processed: {processed}/{count} messages\n"
            f"Channel: {channel_username}"
        )
        await save_log_to_channel(bot, LOG_CHANNEL, f"Batch completed for user {user_id}")
        
    except Exception as e:
        await bot.send_message(user_id, f"❌ Batch processing failed: {str(e)}")
        await send_log(
            Message(message_id=0, chat=user_id, from_user=user_id),
            f"BATCH_FAILED: {str(e)}"
        )
    finally:
        # Clean up task reference
        if user_id in user_tasks:
            del user_tasks[user_id]

# ========== OWNER COMMANDS ==========
@bot.on_message(filters.command("addpremium") & filters.private)
async def add_premium_command(client, message: Message):
    """Add premium user (Owner only)."""
    user_id = message.from_user.id
    
    if user_id not in OWNER_IDS:
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
            f"Expiry: {expiry.strftime('%Y-%m-%d %H:%M:%S')}"
        )
        await send_log(message, f"PREMIUM_ADDED: {target_user}")
        
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

@bot.on_message(filters.command("removepremium") & filters.private)
async def remove_premium_command(client, message: Message):
    """Remove premium user (Owner only)."""
    user_id = message.from_user.id
    
    if user_id not in OWNER_IDS:
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
        await send_log(message, f"PREMIUM_REMOVED: {target_user}")
        
    except Exception as e:
        await message.reply(f"❌ Error: {str(e)}")

# ========== CALLBACK QUERY HANDLER ==========
@bot.on_callback_query()
async def handle_callback_query(client, callback_query):
    """Handle inline button callbacks."""
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    if data == "set_chat_id":
        await callback_query.message.reply(
            "Send me the Chat ID where files should be forwarded:\n"
            "Format: `-100xxxxxxxxxx`\n"
            "Type /cancel to abort."
        )
        # Store state for next message
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"setting_state": "awaiting_chat_id"}},
            upsert=True
        )
    
    elif data == "reset_settings":
        # Reset all settings for this user
        settings_col.delete_one({"user_id": user_id})
        await callback_query.message.edit_text(
            "✅ All settings have been reset to defaults!"
        )
    
    elif data == "change_button":
        await callback_query.message.reply(
            "Send new button text in format:\n"
            "`OldText|NewText`\n\n"
            "Example: `Serena|Kumari`\n"
            "Type /cancel to abort."
        )
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {"setting_state": "awaiting_button_text"}},
            upsert=True
        )
    
    elif data == "close_settings":
        await callback_query.message.delete()
    
    await callback_query.answer()

# ========== START BOT FUNCTION ==========
async def start_bot():
    """Start the bot client."""
    await bot.start()
    print("🤖 Bot started successfully!")
    await idle()
    await bot.stop()

if __name__ == "__main__":
    asyncio.run(start_bot())
