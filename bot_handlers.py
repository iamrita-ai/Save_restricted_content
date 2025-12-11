import asyncio
import os
import logging
import re
from datetime import datetime, timedelta
from bson import ObjectId

from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from pyrogram.errors import FloodWait, UserNotParticipant

from config import Config
from database import (
    add_user, get_user_session, save_user_session, 
    get_user_setting, update_user_setting, add_premium_user, 
    remove_premium_user, users_collection, sessions_collection,
    settings_collection, batch_tasks_collection
)
from utils import send_message_with_delay, process_batch, send_log_to_channel

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

# Store user clients in memory
user_clients = {}

# ==================== HELPER FUNCTIONS ====================
async def check_force_sub(user_id: int):
    """Check if user is subscribed to force channel"""
    try:
        # Remove @ from channel username if present
        channel = Config.FORCE_SUB_CHANNEL.replace("@", "")
        user = await bot.get_chat_member(channel, user_id)
        if user.status in ["left", "kicked"]:
            return False
        return True
    except Exception as e:
        logger.error(f"Force sub check error: {e}")
        return True  # Return True if check fails

async def get_force_sub_keyboard():
    """Create inline keyboard for force subscribe"""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Join Channel", url=Config.FORCE_SUB_CHANNEL)],
            [InlineKeyboardButton("👤 Contact Owner", url=Config.OWNER_LINK)],
            [InlineKeyboardButton("🔄 Try Again", callback_data="check_force_sub")]
        ]
    )
    return keyboard

async def check_premium(user_id: int):
    """Check if user has premium access"""
    try:
        user = users_collection.find_one({"user_id": user_id})
        if user and user.get("is_premium", False):
            expiry = user.get("premium_expiry")
            if expiry and expiry > datetime.now():
                return True
            else:
                # Premium expired
                remove_premium_user(user_id)
        return False
    except Exception as e:
        logger.error(f"Premium check error: {e}")
        return False

async def extract_chat_id_and_message(link: str):
    """Extract chat_id and message_id from Telegram link"""
    try:
        # Handle different link formats
        patterns = [
            r"https?://t\.me/([^/]+)/(\d+)",
            r"https?://telegram\.me/([^/]+)/(\d+)",
            r"https?://telegram\.dog/([^/]+)/(\d+)"
        ]
        
        for pattern in patterns:
            match = re.match(pattern, link)
            if match:
                username, message_id = match.groups()
                return username, int(message_id)
        
        return None, None
    except Exception as e:
        logger.error(f"Link extraction error: {e}")
        return None, None

async def get_user_client(user_id: int):
    """Get or create user client from session string"""
    if user_id in user_clients:
        client = user_clients[user_id]
        if not client.is_connected:
            await client.connect()
        return client
    
    session_string = get_user_session(user_id)
    if not session_string:
        return None
    
    try:
        client = Client(
            f"user_{user_id}",
            session_string=session_string,
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            in_memory=True
        )
        await client.start()
        user_clients[user_id] = client
        return client
    except Exception as e:
        logger.error(f"User client creation error: {e}")
        return None

# ==================== COMMAND HANDLERS ====================
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """Handle /start command"""
    user_id = message.from_user.id
    add_user(user_id, message.from_user.first_name)
    
    # Check force subscription
    if not await check_force_sub(user_id):
        keyboard = await get_force_sub_keyboard()
        await message.reply_text(
            "⚠️ **Please join our channel first to use the bot!**\n\n"
            "Join the channel below and then click 'Try Again':",
            reply_markup=keyboard
        )
        return
    
    welcome_text = (
        "👋 **Welcome to File Recovery Bot!**\n\n"
        "I can help you recover files from your lost Telegram account.\n\n"
        "📋 **Available Commands:**\n"
        "• /login - Login with phone number\n"
        "• /batch - Start batch file recovery\n"
        "• /status - Check current task status\n"
        "• /cancel - Cancel ongoing task\n"
        "• /setting - Configure bot settings\n"
        "• /help - Show detailed guide\n\n"
        "⚠️ **Note:** Please make sure you have access to the phone number of your lost account."
    )
    
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("📢 Join Channel", url=Config.FORCE_SUB_CHANNEL)],
            [InlineKeyboardButton("👤 Contact Owner", url=Config.OWNER_LINK)],
            [InlineKeyboardButton("🆘 Help", callback_data="help")]
        ]
    )
    
    await message.reply_text(welcome_text, reply_markup=keyboard)
    
    # Send log to channel
    log_msg = f"User {user_id} started the bot"
    await send_log_to_channel(bot, log_msg, "START")

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    """Handle /help command"""
    help_text = (
        "📖 **Bot Usage Guide**\n\n"
        "🔑 **1. Login Process**\n"
        "   Use `/login` to authenticate with your lost account's phone number and OTP.\n\n"
        "📦 **2. Batch Recovery**\n"
        "   Format: `/batch https://t.me/channel/123`\n"
        "   • You'll be asked for number of messages\n"
        "   • Maximum limit: 1000 messages\n"
        "   • Delay: 12 seconds between messages\n\n"
        "⚙️ **3. Settings**\n"
        "   Use `/setting` to configure:\n"
        "   • Set Chat ID for direct forwarding\n"
        "   • Toggle button text (Serena/Kumari)\n\n"
        "🛠 **4. Task Management**\n"
        "   • `/status` - Check task progress\n"
        "   • `/cancel` - Cancel current task\n\n"
        "👑 **5. Premium Features**\n"
        "   Owners can manage premium users with:\n"
        "   • `/addpremium user_id days`\n"
        "   • `/removepremium user_id`\n\n"
        "📞 **Support:** Contact @technicalserena for help."
    )
    
    await message.reply_text(help_text, disable_web_page_preview=True)

@bot.on_message(filters.command("login") & filters.private)
async def login_command(client: Client, message: Message):
    """Handle /login command"""
    user_id = message.from_user.id
    
    # Check if already logged in
    if get_user_session(user_id):
        await message.reply_text(
            "✅ You are already logged in!\n"
            "Use `/batch` to start recovering files."
        )
        return
    
    # Ask for phone number
    await message.reply_text(
        "📱 **Login Process**\n\n"
        "Please send your phone number in international format:\n"
        "Example: `+919876543210`\n\n"
        "⚠️ **Note:** This should be the phone number of your lost Telegram account."
    )
    
    try:
        # Wait for phone number
        phone_msg = await client.listen(
            user_id, 
            filters.text & filters.private, 
            timeout=300
        )
        phone_number = phone_msg.text.strip()
        
        # Validate phone number
        if not phone_number.startswith("+"):
            await message.reply_text(
                "❌ Invalid format! Please use international format with + sign.\n"
                "Example: `+919876543210`\n"
                "Try `/login` again."
            )
            return
        
        # Create user client
        user_client = Client(
            f"user_{user_id}",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            in_memory=True
        )
        
        await user_client.connect()
        
        # Send code request
        try:
            sent_code = await user_client.send_code(phone_number)
        except Exception as e:
            await message.reply_text(
                f"❌ Error sending code: {str(e)}\n"
                "Please check the phone number and try again."
            )
            await user_client.disconnect()
            return
        
        # Ask for OTP
        await message.reply_text(
            "✅ Verification code sent!\n\n"
            "Please enter the **OTP** you received (like `12345`):\n\n"
            "⚠️ **Note:** If you have 2FA enabled, you'll be asked for password after OTP."
        )
        
        # Wait for OTP
        otp_msg = await client.listen(
            user_id, 
            filters.text & filters.private, 
            timeout=300
        )
        otp_code = otp_msg.text.strip()
        
        # Try to sign in
        try:
            await user_client.sign_in(
                phone_number=phone_number,
                phone_code_hash=sent_code.phone_code_hash,
                phone_code=otp_code
            )
        except Exception as e:
            # Check if password is needed
            if "SESSION_PASSWORD_NEEDED" in str(e):
                await message.reply_text(
                    "🔐 **2FA Password Required**\n\n"
                    "Please enter your Telegram 2FA password:"
                )
                
                # Wait for password
                password_msg = await client.listen(
                    user_id, 
                    filters.text & filters.private, 
                    timeout=300
                )
                
                try:
                    await user_client.check_password(password_msg.text)
                except Exception as pass_err:
                    await message.reply_text(
                        f"❌ Password error: {str(pass_err)}\n"
                        "Please try `/login` again."
                    )
                    await user_client.disconnect()
                    return
            else:
                await message.reply_text(
                    f"❌ Login failed: {str(e)}\n"
                    "Please try `/login` again."
                )
                await user_client.disconnect()
                return
        
        # Save session string
        session_string = await user_client.export_session_string()
        save_user_session(user_id, session_string)
        
        # Store client in memory
        user_clients[user_id] = user_client
        
        await message.reply_text(
            "✅ **Login Successful!**\n\n"
            "Your session has been saved.\n"
            "You can now use `/batch` to recover files.\n\n"
            "⚠️ **Note:** Don't share your session string with anyone!"
        )
        
        # Send log to channel (masked phone number)
        masked_phone = phone_number[:4] + "****" + phone_number[-3:]
        log_msg = f"User {user_id} logged in with phone: {masked_phone}"
        await send_log_to_channel(bot, log_msg, "LOGIN")
        
    except asyncio.TimeoutError:
        await message.reply_text(
            "⏰ Login timeout!\n"
            "Please try `/login` again."
        )
    except Exception as e:
        await message.reply_text(
            f"❌ Login error: {str(e)}\n"
            "Please try `/login` again."
        )
        logger.error(f"Login error: {e}")

@bot.on_message(filters.command("batch") & filters.private)
async def batch_command(client: Client, message: Message):
    """Handle /batch command"""
    user_id = message.from_user.id
    
    # Check force subscription
    if not await check_force_sub(user_id):
        keyboard = await get_force_sub_keyboard()
        await message.reply_text(
            "⚠️ **Please join our channel first to use this feature!**",
            reply_markup=keyboard
        )
        return
    
    # Check if user is logged in
    user_client = await get_user_client(user_id)
    if not user_client:
        await message.reply_text(
            "❌ **You need to login first!**\n\n"
            "Use `/login` to authenticate with your lost account."
        )
        return
    
    # Check if user has active task
    active_task = batch_tasks_collection.find_one({
        "user_id": user_id,
        "status": {"$in": ["processing", "started"]}
    })
    
    if active_task:
        await message.reply_text(
            "⚠️ **You have an active task!**\n\n"
            "Please wait for it to complete or use `/cancel` to stop it."
        )
        return
    
    # Check command format
    if len(message.command) < 2:
        await message.reply_text(
            "📝 **Usage:** `/batch <channel_link>`\n\n"
            "**Example:**\n"
            "`/batch https://t.me/serenaunzipbot/123`\n\n"
            "The link should be from the channel where you want to recover files."
        )
        return
    
    # Extract chat ID and message ID from link
    link = message.command[1]
    chat_id, start_msg_id = await extract_chat_id_and_message(link)
    
    if not chat_id or not start_msg_id:
        await message.reply_text(
            "❌ **Invalid link format!**\n\n"
            "Please provide a valid Telegram message link.\n"
            "Example: `https://t.me/serenaunzipbot/123`"
        )
        return
    
    # Ask for number of messages
    await message.reply_text(
        f"📊 **Batch Setup**\n\n"
        f"**Channel:** `{chat_id}`\n"
        f"**Start Message ID:** `{start_msg_id}`\n\n"
        f"How many messages do you want to recover?\n"
        f"**Maximum:** {Config.BATCH_LIMIT} messages"
    )
    
    try:
        # Wait for count input
        count_msg = await client.listen(
            user_id, 
            filters.text & filters.private, 
            timeout=60
        )
        
        try:
            count = int(count_msg.text)
            if count <= 0:
                await message.reply_text("❌ Please enter a positive number!")
                return
                
            if count > Config.BATCH_LIMIT:
                count = Config.BATCH_LIMIT
                await message.reply_text(
                    f"⚠️ Limit exceeded! Using maximum: {Config.BATCH_LIMIT}"
                )
                
        except ValueError:
            await message.reply_text("❌ Please enter a valid number!")
            return
        
        # Get target chat ID from settings
        target_chat_id = get_user_setting(user_id, "set_chat_id", user_id)
        
        # Create task in database
        task_id = ObjectId()
        batch_tasks_collection.insert_one({
            "_id": task_id,
            "user_id": user_id,
            "chat_id": chat_id,
            "target_chat_id": target_chat_id,
            "start_msg_id": start_msg_id,
            "count": count,
            "status": "queued",
            "progress": 0,
            "successful": 0,
            "failed": 0,
            "created_at": datetime.now()
        })
        
        # Send confirmation
        keyboard = InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📊 Status", callback_data=f"status_{task_id}")],
                [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]
            ]
        )
        
        await message.reply_text(
            f"✅ **Batch Task Created!**\n\n"
            f"**Task ID:** `{task_id}`\n"
            f"**Channel:** `{chat_id}`\n"
            f"**Start From:** `{start_msg_id}`\n"
            f"**Total Messages:** `{count}`\n"
            f"**Delay:** `{Config.SLEEP_TIME}` seconds\n\n"
            f"Task will start shortly. Use buttons below to manage:",
            reply_markup=keyboard
        )
        
        # Start processing in background
        asyncio.create_task(
            process_batch_task(user_client, user_id, chat_id, start_msg_id, count, target_chat_id, task_id)
        )
        
        # Log to channel
        log_msg = (
            f"User {user_id} started batch task\n"
            f"Task ID: {task_id}\n"
            f"Chat: {chat_id}\n"
            f"Messages: {count}"
        )
        await send_log_to_channel(bot, log_msg, "BATCH_START")
        
    except asyncio.TimeoutError:
        await message.reply_text("⏰ Timeout! Please use `/batch` again.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")
        logger.error(f"Batch command error: {e}")

async def process_batch_task(user_client, user_id, chat_id, start_msg_id, count, target_chat_id, task_id):
    """Process batch task in background"""
    try:
        # Update task status
        batch_tasks_collection.update_one(
            {"_id": task_id},
            {"$set": {"status": "processing"}}
        )
        
        successful = 0
        failed = 0
        
        # Process each message
        for i in range(count):
            # Check if task was cancelled
            task = batch_tasks_collection.find_one({"_id": task_id})
            if task and task.get("status") == "cancelled":
                break
            
            current_msg_id = start_msg_id + i
            
            try:
                # Forward message with delay
                await user_client.forward_messages(
                    chat_id=target_chat_id,
                    from_chat_id=chat_id,
                    message_ids=current_msg_id
                )
                successful += 1
                
                # Add delay (except for last message)
                if i < count - 1:
                    await asyncio.sleep(Config.SLEEP_TIME)
                    
            except FloodWait as e:
                # Handle flood wait
                wait_time = e.value
                await bot.send_message(
                    user_id,
                    f"⚠️ Flood wait detected! Waiting {wait_time} seconds..."
                )
                await asyncio.sleep(wait_time)
                continue
            except Exception as e:
                failed += 1
                logger.error(f"Message {current_msg_id} failed: {e}")
            
            # Update progress every 10 messages
            if i % 10 == 0 or i == count - 1:
                batch_tasks_collection.update_one(
                    {"_id": task_id},
                    {"$set": {
                        "progress": i + 1,
                        "successful": successful,
                        "failed": failed
                    }}
                )
        
        # Mark task as completed
        final_status = "completed" if successful > 0 else "failed"
        batch_tasks_collection.update_one(
            {"_id": task_id},
            {"$set": {
                "status": final_status,
                "progress": count,
                "successful": successful,
                "failed": failed,
                "completed_at": datetime.now()
            }}
        )
        
        # Notify user
        await bot.send_message(
            user_id,
            f"✅ **Batch Task Completed!**\n\n"
            f"**Task ID:** `{task_id}`\n"
            f"**Status:** {final_status.upper()}\n"
            f"**Successful:** {successful}\n"
            f"**Failed:** {failed}\n"
            f"**Total:** {count}"
        )
        
        # Log to channel
        log_msg = (
            f"Batch task completed\n"
            f"Task ID: {task_id}\n"
            f"User: {user_id}\n"
            f"Successful: {successful}\n"
            f"Failed: {failed}"
        )
        await send_log_to_channel(bot, log_msg, "BATCH_COMPLETE")
        
    except Exception as e:
        logger.error(f"Batch task error: {e}")
        batch_tasks_collection.update_one(
            {"_id": task_id},
            {"$set": {"status": "error", "error": str(e)}}
        )
        await bot.send_message(
            user_id,
            f"❌ **Task Error!**\n\nError: {str(e)}"
        )

@bot.on_message(filters.command("status") & filters.private)
async def status_command(client: Client, message: Message):
    """Handle /status command"""
    user_id = message.from_user.id
    
    # Get latest task
    task = batch_tasks_collection.find_one(
        {"user_id": user_id},
        sort=[("created_at", -1)]
    )
    
    if not task:
        await message.reply_text(
            "📭 **No tasks found!**\n\n"
            "Use `/batch` to start a new task."
        )
        return
    
    # Format status
    status_emoji = {
        "queued": "⏳",
        "processing": "⚙️",
        "completed": "✅",
        "failed": "❌",
        "cancelled": "🚫",
        "error": "⚠️"
    }.get(task.get("status", "unknown"), "❓")
    
    status_text = (
        f"📊 **Task Status**\n\n"
        f"**Task ID:** `{task['_id']}`\n"
        f"**Status:** {status_emoji} {task.get('status', 'unknown').upper()}\n"
        f"**Channel:** `{task.get('chat_id', 'N/A')}`\n"
        f"**Progress:** {task.get('progress', 0)} / {task.get('count', 0)}\n"
        f"**Successful:** {task.get('successful', 0)}\n"
        f"**Failed:** {task.get('failed', 0)}\n"
        f"**Created:** {task.get('created_at', '').strftime('%Y-%m-%d %H:%M') if task.get('created_at') else 'N/A'}"
    )
    
    if task.get("completed_at"):
        status_text += f"\n**Completed:** {task['completed_at'].strftime('%Y-%m-%d %H:%M')}"
    
    keyboard = None
    if task.get("status") in ["queued", "processing"]:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task['_id']}")]
        ])
    
    await message.reply_text(status_text, reply_markup=keyboard)

@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_command(client: Client, message: Message):
    """Handle /cancel command"""
    user_id = message.from_user.id
    
    # Find active task
    task = batch_tasks_collection.find_one({
        "user_id": user_id,
        "status": {"$in": ["queued", "processing"]}
    })
    
    if not task:
        await message.reply_text(
            "ℹ️ **No active task to cancel!**\n\n"
            "Use `/batch` to start a new task."
        )
        return
    
    # Cancel the task
    batch_tasks_collection.update_one(
        {"_id": task["_id"]},
        {"$set": {"status": "cancelled"}}
    )
    
    await message.reply_text(
        f"✅ **Task Cancelled!**\n\n"
        f"Task ID: `{task['_id']}`\n"
        f"Progress: {task.get('progress', 0)} / {task.get('count', 0)}"
    )
    
    # Log to channel
    log_msg = f"User {user_id} cancelled task {task['_id']}"
    await send_log_to_channel(bot, log_msg, "TASK_CANCELLED")

@bot.on_message(filters.command("setting") & filters.private)
async def setting_command(client: Client, message: Message):
    """Handle /setting command"""
    user_id = message.from_user.id
    
    # Get current settings
    set_chat_id = get_user_setting(user_id, "set_chat_id", "Not set")
    button_text = get_user_setting(user_id, "button_text", "Serena")
    
    # Create settings text
    settings_text = (
        "⚙️ **Bot Settings**\n\n"
        "Configure your bot preferences:\n\n"
        f"📨 **Set Chat ID:** `{set_chat_id}`\n"
        f"   • Files will be sent to this chat\n\n"
        f"🔘 **Button Text:** `{button_text}`\n"
        f"   • Toggle between Serena/Kumari"
    )
    
    # Create inline keyboard
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("📨 Set Chat ID", callback_data="set_chat_id"),
            InlineKeyboardButton(f"🔘 {button_text}", callback_data="toggle_button")
        ],
        [
            InlineKeyboardButton("🔄 Reset", callback_data="reset_settings"),
            InlineKeyboardButton("❌ Close", callback_data="close_settings")
        ]
    ])
    
    await message.reply_text(settings_text, reply_markup=keyboard)

# ==================== ADMIN COMMANDS ====================
@bot.on_message(filters.command("addpremium") & filters.private)
async def add_premium_command(client: Client, message: Message):
    """Handle /addpremium command (owner only)"""
    user_id = message.from_user.id
    
    # Check if user is owner
    if user_id not in Config.OWNER_IDS:
        await message.reply_text("❌ This command is for owners only!")
        return
    
    # Check command format
    if len(message.command) < 3:
        await message.reply_text(
            "📝 **Usage:** `/addpremium <user_id> <days>`\n\n"
            "**Example:** `/addpremium 1234567890 12`"
        )
        return
    
    try:
        target_user_id = int(message.command[1])
        days = int(message.command[2])
        
        add_premium_user(target_user_id, days)
        
        await message.reply_text(
            f"✅ **Premium Added!**\n\n"
            f"**User ID:** `{target_user_id}`\n"
            f"**Days:** `{days}`\n"
            f"**Expiry:** `{(datetime.now() + timedelta(days=days)).strftime('%Y-%m-%d %H:%M')}`"
        )
        
        # Log to channel
        log_msg = (
            f"Premium user added\n"
            f"By: {user_id}\n"
            f"User: {target_user_id}\n"
            f"Days: {days}"
        )
        await send_log_to_channel(bot, log_msg, "PREMIUM_ADD")
        
    except ValueError:
        await message.reply_text("❌ Invalid user ID or days format!")
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")

@bot.on_message(filters.command("removepremium") & filters.private)
async def remove_premium_command(client: Client, message: Message):
    """Handle /removepremium command (owner only)"""
    user_id = message.from_user.id
    
    # Check if user is owner
    if user_id not in Config.OWNER_IDS:
        await message.reply_text("❌ This command is for owners only!")
        return
    
    # Check command format
    if len(message.command) < 2:
        await message.reply_text(
            "📝 **Usage:** `/removepremium <user_id>`\n\n"
            "**Example:** `/removepremium 1234567890`"
        )
        return
    
    try:
        target_user_id = int(message.command[1])
        
        remove_premium_user(target_user_id)
        
        await message.reply_text(
            f"✅ **Premium Removed!**\n\n"
            f"**User ID:** `{target_user_id}`"
        )
        
        # Log to channel
        log_msg = (
            f"Premium user removed\n"
            f"By: {user_id}\n"
            f"User: {target_user_id}"
        )
        await send_log_to_channel(bot, log_msg, "PREMIUM_REMOVE")
        
    except ValueError:
        await message.reply_text("❌ Invalid user ID format!")
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)}")

# ==================== CALLBACK QUERY HANDLERS ====================
@bot.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    """Handle inline keyboard callbacks"""
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    try:
        # Check force subscription
        if data == "check_force_sub":
            if await check_force_sub(user_id):
                await callback_query.message.delete()
                await start_command(client, callback_query.message)
            else:
                keyboard = await get_force_sub_keyboard()
                await callback_query.message.edit_text(
                    "⚠️ **Please join our channel first!**\n\n"
                    "Join the channel and click 'Try Again':",
                    reply_markup=keyboard
                )
            await callback_query.answer()
            return
        
        # Help callback
        if data == "help":
            await help_command(client, callback_query.message)
            await callback_query.answer()
            return
        
        # Set Chat ID
        if data == "set_chat_id":
            await callback_query.message.edit_text(
                "📨 **Set Chat ID**\n\n"
                "Send the Chat ID where you want files to be sent:\n\n"
                "**Format:**\n"
                "• Your User ID: `1234567890`\n"
                "• Channel ID: `-1001234567890`\n\n"
                "**Note:** Use your own ID or a channel you manage."
            )
            
            try:
                chat_id_msg = await client.listen(
                    user_id, 
                    filters.text & filters.private, 
                    timeout=60
                )
                
                try:
                    chat_id = int(chat_id_msg.text)
                    update_user_setting(user_id, "set_chat_id", chat_id)
                    
                    await callback_query.message.edit_text(
                        f"✅ **Chat ID Set!**\n\n"
                        f"Files will now be sent to: `{chat_id}`"
                    )
                    
                except ValueError:
                    await callback_query.message.edit_text(
                        "❌ **Invalid Chat ID!**\n\n"
                        "Please send a numeric Chat ID."
                    )
                    
            except asyncio.TimeoutError:
                await callback_query.message.edit_text(
                    "⏰ **Timeout!**\n\n"
                    "Please use `/setting` again."
                )
            
            await callback_query.answer()
            return
        
        # Toggle button text
        if data == "toggle_button":
            current_text = get_user_setting(user_id, "button_text", "Serena")
            new_text = "Kumari" if current_text == "Serena" else "Serena"
            update_user_setting(user_id, "button_text", new_text)
            
            await callback_query.message.edit_text(
                f"✅ **Button Text Updated!**\n\n"
                f"Changed to: **{new_text}**\n\n"
                "Use `/setting` to configure other options."
            )
            await callback_query.answer()
            return
        
        # Reset settings
        if data == "reset_settings":
            settings_collection.delete_many({"user_id": user_id})
            
            await callback_query.message.edit_text(
                "✅ **Settings Reset!**\n\n"
                "All settings have been reset to defaults."
            )
            await callback_query.answer()
            return
        
        # Close settings
        if data == "close_settings":
            await callback_query.message.delete()
            await callback_query.answer("Settings closed")
            return
        
        # Task status
        if data.startswith("status_"):
            task_id = ObjectId(data.replace("status_", ""))
            task = batch_tasks_collection.find_one({"_id": task_id})
            
            if task and task["user_id"] == user_id:
                status_emoji = {
                    "queued": "⏳",
                    "processing": "⚙️",
                    "completed": "✅",
                    "failed": "❌",
                    "cancelled": "🚫"
                }.get(task.get("status", "unknown"), "❓")
                
                status_text = (
                    f"📊 **Task Status**\n\n"
                    f"**ID:** `{task_id}`\n"
                    f"**Status:** {status_emoji} {task.get('status', 'unknown').upper()}\n"
                    f"**Progress:** {task.get('progress', 0)} / {task.get('count', 0)}\n"
                    f"**Successful:** {task.get('successful', 0)}\n"
                    f"**Failed:** {task.get('failed', 0)}"
                )
                
                await callback_query.message.edit_text(status_text)
            else:
                await callback_query.answer("Task not found!", show_alert=True)
            
            await callback_query.answer()
            return
        
        # Cancel task
        if data.startswith("cancel_"):
            task_id = ObjectId(data.replace("cancel_", ""))
            task = batch_tasks_collection.find_one({"_id": task_id})
            
            if task and task["user_id"] == user_id:
                if task.get("status") in ["queued", "processing"]:
                    batch_tasks_collection.update_one(
                        {"_id": task_id},
                        {"$set": {"status": "cancelled"}}
                    )
                    
                    await callback_query.message.edit_text(
                        f"✅ **Task Cancelled!**\n\n"
                        f"Task ID: `{task_id}`"
                    )
                    
                    # Log to channel
                    log_msg = f"User {user_id} cancelled task {task_id}"
                    await send_log_to_channel(bot, log_msg, "TASK_CANCELLED")
                else:
                    await callback_query.answer("Task cannot be cancelled!", show_alert=True)
            else:
                await callback_query.answer("Task not found!", show_alert=True)
            
            await callback_query.answer()
            return
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        await callback_query.answer("Error occurred!", show_alert=True)

# ==================== MESSAGE HANDLERS ====================
@bot.on_message(filters.private & ~filters.command())
async def handle_private_messages(client: Client, message: Message):
    """Handle non-command private messages"""
    user_id = message.from_user.id
    
    # Ignore if message is from bot itself
    if message.from_user.is_self:
        return
    
    # Send generic response
    await message.reply_text(
        "🤖 **I'm a file recovery bot!**\n\n"
        "Use /help to see available commands.\n"
        "Use /start to begin.\n\n"
        "📞 **Support:** @technicalserena"
    )

# ==================== ERROR HANDLER ====================
@bot.on_error()
async def error_handler(client: Client, error: Exception):
    """Handle errors"""
    logger.error(f"Bot error: {error}")
    
    # Log error to channel
    try:
        await send_log_to_channel(
            bot, 
            f"Bot Error: {str(error)[:200]}", 
            "ERROR"
        )
    except:
        pass

# ==================== BOT STARTUP ====================
async def main():
    """Main function to run the bot"""
    logger.info("Starting bot...")
    
    # Check environment variables
    required_vars = ['API_ID', 'API_HASH', 'BOT_TOKEN', 'MONGO_URL']
    missing_vars = [var for var in required_vars if not getattr(Config, var, None)]
    
    if missing_vars:
        logger.error(f"Missing environment variables: {missing_vars}")
        return
    
    try:
        await bot.start()
        logger.info("✅ Bot started successfully!")
        
        # Get bot info
        me = await bot.get_me()
        logger.info(f"🤖 Bot Username: @{me.username}")
        logger.info(f"🆔 Bot ID: {me.id}")
        
        # Send startup message to log channel
        await send_log_to_channel(
            bot,
            f"Bot started!\nUsername: @{me.username}\nID: {me.id}",
            "STARTUP"
        )
        
        # Keep bot running
        await idle()
        
    except Exception as e:
        logger.error(f"Bot startup failed: {e}")
    finally:
        await bot.stop()
        logger.info("Bot stopped")

# This allows the bot to be imported without automatically running
if __name__ == "__main__":
    asyncio.run(main())


    
