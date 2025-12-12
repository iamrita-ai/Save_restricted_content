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

def format_time(seconds):
    """Format time in human readable format"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds//60}m {seconds%60}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"

# ==================== COMMAND HANDLERS ====================
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """Handle /start command"""
    user_id = message.from_user.id
    user_name = message.from_user.first_name
    
    # Add user to database
    add_user(user_id, user_name)
    
    # Check force subscription
    if not await force_sub_check(user_id):
        keyboard = await get_force_sub_keyboard()
        await message.reply_text(
            "⚠️ **Please join our channel first to use the bot!**\n\n"
            "Join the channel below and then click 'Check Again':",
            reply_markup=keyboard,
            disable_web_page_preview=True
        )
        return
    
    welcome_text = (
        f"👋 **Welcome {user_name}!**\n\n"
        f"**{Config.BOT_NAME} v{Config.VERSION}**\n\n"
        "I can help you recover files from Telegram channels.\n\n"
        "✨ **Main Features:**\n"
        "• 📦 Batch file recovery from channels\n"
        "• 🔑 Login with any Telegram account\n"
        "• ⚡ Fast forwarding with 12s delay\n"
        "• 📊 Progress tracking and status\n"
        "• ⚙️ Customizable settings\n\n"
        "📖 Use /help for detailed instructions\n"
        "🔧 Use /setting to configure bot\n\n"
        "👑 **Premium Benefits:**\n"
        "• Higher batch limits\n"
        "• Priority processing\n"
        "• No ads"
    )
    
    keyboard = await get_main_keyboard()
    
    await message.reply_text(
        welcome_text,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )
    
    # Log to channel
    await send_log_to_channel(bot, f"User {user_id} started bot", "START", user_id)

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    """Handle /help command"""
    help_text = (
        "📖 **COMPLETE USER GUIDE**\n\n"
        
        "🔑 **1. ACCOUNT LOGIN**\n"
        "   Use `/login` to authenticate with a Telegram account\n"
        "   • Enter phone number (with + country code)\n"
        "   • Enter OTP received\n"
        "   • Enter 2FA password if enabled\n\n"
        
        "📦 **2. BATCH FILE RECOVERY**\n"
        "   **Format:** `/batch https://t.me/channel/123`\n"
        "   • Provide channel message link\n"
        "   • Enter number of messages to recover\n"
        "   • Max limit: 1000 messages per batch\n"
        "   • Delay: 12 seconds between messages\n\n"
        
        "⚙️ **3. BOT SETTINGS**\n"
        "   Use `/setting` to configure:\n"
        "   • **Set Chat ID** - Where to send files\n"
        "   • **Button Text** - Toggle Serena/Kumari\n"
        "   • **Logout Session** - Remove saved session\n"
        "   • **Reset Settings** - Restore defaults\n\n"
        
        "🛠️ **4. TASK MANAGEMENT**\n"
        "   • `/status` - Check current task progress\n"
        "   • `/cancel` - Cancel ongoing task\n"
        "   • `/stats` - View your statistics\n\n"
        
        "👑 **5. PREMIUM FEATURES**\n"
        "   • Higher daily limits\n"
        "   • Faster processing\n"
        "   • Priority support\n"
        "   • Contact owner for premium\n\n"
        
        "📞 **SUPPORT & CONTACT**\n"
        "• Channel: @serenaunzipbot\n"
        "• Owner: @technicalserena\n"
        "• Logs Channel: Saved for security\n\n"
        
        "⚠️ **IMPORTANT NOTES**\n"
        "• Use accounts you have access to\n"
        "• Don't share session strings\n"
        "• Follow Telegram ToS\n"
        "• Respect channel policies"
    )
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 Start Recovery", callback_data="batch_menu")],
        [InlineKeyboardButton("🔑 Login Now", callback_data="login_now")],
        [InlineKeyboardButton("🌟 Get Premium", callback_data="get_premium")],
        [InlineKeyboardButton("📞 Contact Owner", url=Config.OWNER_LINK)]
    ])
    
    await message.reply_text(
        help_text,
        reply_markup=keyboard,
        disable_web_page_preview=True
    )

@bot.on_message(filters.command("login") & filters.private)
async def login_command(client: Client, message: Message):
    """Handle /login command"""
    user_id = message.from_user.id
    
    # Check force sub
    if not await force_sub_check(user_id):
        keyboard = await get_force_sub_keyboard()
        await message.reply_text("⚠️ Join channel first!", reply_markup=keyboard)
        return
    
    # Check if already logged in
    if get_user_session(user_id):
        await message.reply_text(
            "✅ **Already Logged In!**\n\n"
            "You have an active session.\n"
            "Use `/batch` to start recovery.\n\n"
            "Want to logout? Use /setting → Logout Session"
        )
        return
    
    # Start login process
    await message.reply_text(
        "🔑 **LOGIN PROCESS**\n\n"
        "Send the **phone number** with country code:\n"
        "**Example:** `+919876543210`\n\n"
        "⚠️ **Note:** This can be ANY Telegram account that has access to the target channel."
    )
    
    try:
        # Wait for phone number
        phone_msg = await client.wait_for(
            filters.text & filters.private & filters.user(user_id),
            timeout=120
        )
        phone_number = phone_msg.text.strip()
        
        # Validate phone
        if not re.match(r'^\+\d{10,15}$', phone_number):
            await message.reply_text(
                "❌ **Invalid Format!**\n\n"
                "Please use: `+919876543210`\n"
                "Country code + phone number\n\n"
                "Use `/login` to try again."
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
        
        # Send code
        try:
            sent_code = await user_client.send_code(phone_number)
        except Exception as e:
            await message.reply_text(
                f"❌ **Error:** {str(e)[:100]}\n\n"
                "Please check the phone number and try `/login` again."
            )
            await user_client.disconnect()
            return
        
        # Ask for OTP
        await message.reply_text(
            "📲 **OTP Sent!**\n\n"
            "Enter the **6-digit code** you received:\n"
            "**Example:** `123456`\n\n"
            "⏰ Timeout: 2 minutes"
        )
        
        # Wait for OTP
        try:
            otp_msg = await client.wait_for(
                filters.text & filters.private & filters.user(user_id),
                timeout=120
            )
            otp_code = otp_msg.text.strip()
        except asyncio.TimeoutError:
            await message.reply_text("⏰ Timeout! Use `/login` again.")
            await user_client.disconnect()
            return
        
        # Try sign in
        try:
            await user_client.sign_in(
                phone_number=phone_number,
                phone_code_hash=sent_code.phone_code_hash,
                phone_code=otp_code
            )
        except Exception as e:
            # Check for 2FA
            if "SESSION_PASSWORD_NEEDED" in str(e):
                await message.reply_text(
                    "🔐 **2FA Password Required**\n\n"
                    "Enter your Telegram **2FA password**:"
                )
                
                try:
                    password_msg = await client.wait_for(
                        filters.text & filters.private & filters.user(user_id),
                        timeout=120
                    )
                    await user_client.check_password(password_msg.text)
                except asyncio.TimeoutError:
                    await message.reply_text("⏰ Timeout! Use `/login` again.")
                    await user_client.disconnect()
                    return
                except Exception as pass_err:
                    await message.reply_text(
                        f"❌ Password error: {str(pass_err)[:100]}\n"
                        "Use `/login` to try again."
                    )
                    await user_client.disconnect()
                    return
            else:
                await message.reply_text(
                    f"❌ Login failed: {str(e)[:100]}\n"
                    "Use `/login` to try again."
                )
                await user_client.disconnect()
                return
        
        # Save session
        session_string = await user_client.export_session_string()
        save_user_session(user_id, session_string)
        
        # Get account info
        account = await user_client.get_me()
        account_name = account.first_name or "User"
        
        await message.reply_text(
            f"✅ **LOGIN SUCCESSFUL!**\n\n"
            f"**Account:** {account_name}\n"
            f"**Username:** @{account.username if account.username else 'N/A'}\n"
            f"**Phone:** {phone_number[:4]}******\n\n"
            "Your session has been saved securely.\n"
            "Now use `/batch` to start file recovery.\n\n"
            "⚠️ **Security:** Don't share your session!"
        )
        
        # Log successful login
        masked_phone = phone_number[:4] + "****" + phone_number[-3:]
        log_msg = f"Logged in: {account_name} ({masked_phone})"
        await send_log_to_channel(bot, log_msg, "LOGIN", user_id)
        
    except asyncio.TimeoutError:
        await message.reply_text(
            "⏰ **Login Timeout!**\n\n"
            "Please use `/login` to start again."
        )
    except Exception as e:
        await message.reply_text(
            f"❌ **Error:** {str(e)[:100]}\n\n"
            "Please try `/login` again."
        )
        logger.error(f"Login error: {e}")

@bot.on_message(filters.command("batch") & filters.private)
async def batch_command(client: Client, message: Message):
    """Handle /batch command"""
    user_id = message.from_user.id
    
    # Check force sub
    if not await force_sub_check(user_id):
        keyboard = await get_force_sub_keyboard()
        await message.reply_text("⚠️ Join channel first!", reply_markup=keyboard)
        return
    
    # Check if user is logged in
    session_string = get_user_session(user_id)
    if not session_string:
        await message.reply_text(
            "❌ **Login Required!**\n\n"
            "Please use `/login` first to authenticate with a Telegram account."
        )
        return
    
    # Check for active task
    active_task = get_active_task(user_id)
    if active_task:
        await message.reply_text(
            "⚠️ **You have an active task!**\n\n"
            "Please wait for it to complete or use `/cancel` first."
        )
        return
    
    # Check command format
    if len(message.command) < 2:
        await message.reply_text(
            "📝 **Usage:** `/batch <channel_link>`\n\n"
            "**Example:**\n"
            "`/batch https://t.me/serenaunzipbot/123`\n\n"
            "Provide a message link from the target channel."
        )
        return
    
    # Extract info from link
    link = message.command[1]
    chat_id, start_msg_id = extract_info_from_link(link)
    
    if not chat_id or not start_msg_id:
        await message.reply_text(
            "❌ **Invalid link!**\n\n"
            "Please provide a valid Telegram message link.\n"
            "Format: `https://t.me/channelname/123`"
        )
        return
    
    # Ask for count
    await message.reply_text(
        f"📊 **Batch Setup**\n\n"
        f"**Channel:** `{chat_id}`\n"
        f"**Start Message:** `{start_msg_id}`\n\n"
        f"How many messages to recover?\n"
        f"**Max:** {Config.BATCH_LIMIT} messages"
    )
    
    try:
        # Wait for count
        count_msg = await client.wait_for(
            filters.text & filters.private & filters.user(user_id),
            timeout=60
        )
        
        try:
            count = int(count_msg.text)
            if count <= 0:
                await message.reply_text("❌ Please enter positive number!")
                return
            if count > Config.BATCH_LIMIT:
                count = Config.BATCH_LIMIT
                await message.reply_text(f"⚠️ Using max limit: {count}")
        except ValueError:
            await message.reply_text("❌ Invalid number!")
            return
        
        # Get target chat ID
        target_chat_id = get_user_setting(user_id, "set_chat_id", user_id)
        
        # Create task
        task_id = create_batch_task(user_id, chat_id, start_msg_id, count, target_chat_id)
        
        # Send confirmation
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("📊 Status", callback_data=f"status_{task_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")]
        ])
        
        await message.reply_text(
            f"✅ **Task Created!**\n\n"
            f"**Task ID:** `{task_id}`\n"
            f"**Channel:** `{chat_id}`\n"
            f"**Start From:** `{start_msg_id}`\n"
            f"**Messages:** `{count}`\n"
            f"**Delay:** `{Config.SLEEP_TIME}s`\n\n"
            "Task starting... Use buttons below:",
            reply_markup=keyboard
        )
        
        # Start processing in background
        asyncio.create_task(
            process_batch_task(user_id, chat_id, start_msg_id, count, target_chat_id, task_id)
        )
        
        # Log
        await send_log_to_channel(bot, f"Started batch: {count} msgs", "BATCH", user_id)
        
    except asyncio.TimeoutError:
        await message.reply_text("⏰ Timeout! Use `/batch` again.")
    except Exception as e:
        await message.reply_text(f"❌ Error: {str(e)[:100]}")
        logger.error(f"Batch error: {e}")

async def process_batch_task(user_id, chat_id, start_msg_id, count, target_chat_id, task_id):
    """Process batch task in background"""
    try:
        # Update task status
        update_task_status(task_id, "processing")
        
        # Get user session
        session_string = get_user_session(user_id)
        if not session_string:
            update_task_status(task_id, "failed")
            await bot.send_message(user_id, "❌ Session expired! Please /login again.")
            return
        
        # Create user client
        user_client = Client(
            f"user_{user_id}_task",
            session_string=session_string,
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            in_memory=True
        )
        
        await user_client.start()
        
        # Check access
        has_access, chat_info = await check_user_access(user_client, chat_id)
        if not has_access:
            update_task_status(task_id, "failed")
            await bot.send_message(
                user_id,
                f"❌ Cannot access channel!\nError: {chat_info}"
            )
            await user_client.stop()
            return
        
        successful = 0
        failed = 0
        
        # Process messages
        for i in range(count):
            current_msg_id = start_msg_id + i
            
            # Check if cancelled
            task = get_active_task(user_id)
            if not task or task.get("status") == "cancelled":
                break
            
            try:
                # Forward message
                await user_client.forward_messages(
                    chat_id=target_chat_id,
                    from_chat_id=chat_id,
                    message_ids=current_msg_id
                )
                successful += 1
                
                # Delay between messages
                if i < count - 1:
                    await asyncio.sleep(Config.SLEEP_TIME)
                    
            except FloodWait as e:
                wait_time = e.value
                await bot.send_message(
                    user_id,
                    f"⚠️ Flood wait: {wait_time}s\nWaiting..."
                )
                await asyncio.sleep(wait_time)
                continue
            except Exception as e:
                failed += 1
                logger.error(f"Msg {current_msg_id} error: {e}")
            
            # Update progress
            if (i + 1) % 10 == 0 or i == count - 1:
                update_task_status(task_id, "processing", i + 1, successful, failed)
                await send_status_update(user_id, i + 1, count, successful, failed)
        
        # Final update
        final_status = "completed" if successful > 0 else "failed"
        update_task_status(task_id, final_status, count, successful, failed)
        
        # Send final message
        await bot.send_message(
            user_id,
            f"✅ **Task {final_status.upper()}!**\n\n"
            f"**Total:** {count}\n"
            f"✅ **Successful:** {successful}\n"
            f"❌ **Failed:** {failed}\n"
            f"⏱️ **Time:** ~{format_time(count * Config.SLEEP_TIME)}"
        )
        
        # Log
        await send_log_to_channel(
            bot, 
            f"Batch completed: {successful}/{count}", 
            "BATCH_COMPLETE", 
            user_id
        )
        
        await user_client.stop()
        
    except Exception as e:
        logger.error(f"Batch task error: {e}")
        update_task_status(task_id, "error")
        await bot.send_message(user_id, f"❌ Task error: {str(e)[:100]}")

  @bot.on_message(filters.command("status") & filters.private)
async def status_command(client: Client, message: Message):
    """Handle /status command"""
    user_id = message.from_user.id
    
    # Get active task
    task = get_active_task(user_id)
    if not task:
        # Get last task
        tasks = get_user_tasks(user_id)
        if tasks:
            task = tasks[0]
        else:
            await message.reply_text("📭 No tasks found. Use `/batch` to start.")
            return
    
    # Format status
    status_icons = {
        "queued": "⏳",
        "processing": "⚙️",
        "completed": "✅",
        "failed": "❌",
        "cancelled": "🚫",
        "error": "⚠️"
    }
    
    icon = status_icons.get(task.get("status", ""), "❓")
    
    status_text = (
        f"📊 **Task Status**\n\n"
        f"{icon} **Status:** {task.get('status', 'unknown').upper()}\n"
        f"📁 **Progress:** {task.get('progress', 0)}/{task.get('count', 0)}\n"
        f"✅ **Successful:** {task.get('successful', 0)}\n"
        f"❌ **Failed:** {task.get('failed', 0)}\n"
        f"⏱️ **Created:** {task.get('created_at').strftime('%Y-%m-%d %H:%M')}"
    )
    
    if task.get("status") in ["queued", "processing"]:
        # Add progress bar
        if task.get('count', 0) > 0:
            progress = create_progress_bar(task.get('progress', 0), task.get('count', 0))
            status_text += f"\n\n{progress}"
        
        # Add cancel button
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task['_id']}")]
        ])
        await message.reply_text(status_text, reply_markup=keyboard)
    else:
        await message.reply_text(status_text)

@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_command(client: Client, message: Message):
    """Handle /cancel command"""
    user_id = message.from_user.id
    
    cancelled = cancel_user_tasks(user_id)
    
    if cancelled > 0:
        await message.reply_text(f"✅ Cancelled {cancelled} task(s).")
    else:
        await message.reply_text("ℹ️ No active tasks to cancel.")

@bot.on_message(filters.command("setting") & filters.private)
async def setting_command(client: Client, message: Message):
    """Handle /setting command"""
    user_id = message.from_user.id
    
    keyboard = await get_settings_keyboard(user_id)
    
    await message.reply_text(
        "⚙️ **Settings Menu**\n\n"
        "Configure your bot preferences:",
        reply_markup=keyboard
    )

@bot.on_message(filters.command("addpremium") & filters.user(Config.OWNER_IDS))
async def add_premium_command(client: Client, message: Message):
    """Handle /addpremium command (owners only)"""
    if len(message.command) < 3:
        await message.reply_text("Usage: `/addpremium user_id days`")
        return
    
    try:
        target_id = int(message.command[1])
        days = int(message.command[2])
        
        add_premium_user(target_id, days)
        
        await message.reply_text(
            f"✅ Added premium to {target_id} for {days} days."
        )
        
        # Log
        await send_log_to_channel(
            bot,
            f"Premium added: {target_id} for {days} days",
            "ADMIN",
            message.from_user.id
        )
        
    except ValueError:
        await message.reply_text("❌ Invalid user_id or days!")

@bot.on_message(filters.command("removepremium") & filters.user(Config.OWNER_IDS))
async def remove_premium_command(client: Client, message: Message):
    """Handle /removepremium command (owners only)"""
    if len(message.command) < 2:
        await message.reply_text("Usage: `/removepremium user_id`")
        return
    
    try:
        target_id = int(message.command[1])
        remove_premium_user(target_id)
        
        await message.reply_text(f"✅ Removed premium from {target_id}")
        
        # Log
        await send_log_to_channel(
            bot,
            f"Premium removed: {target_id}",
            "ADMIN",
            message.from_user.id
        )
        
    except ValueError:
        await message.reply_text("❌ Invalid user_id!")

# ==================== CALLBACK QUERY HANDLERS ====================
@bot.on_callback_query()
async def callback_handler(client: Client, callback_query: CallbackQuery):
    """Handle all callback queries"""
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    try:
        # Check subscription
        if data == "check_sub":
            if await force_sub_check(user_id):
                await callback_query.message.delete()
                await start_command(client, callback_query.message)
            else:
                keyboard = await get_force_sub_keyboard()
                await callback_query.message.edit_text(
                    "⚠️ **Please join our channel first!**",
                    reply_markup=keyboard
                )
            await callback_query.answer()
            return
        
        # Main menu
        if data == "main_menu":
            keyboard = await get_main_keyboard()
            await callback_query.message.edit_text(
                "🏠 **Main Menu**\n\n"
                "Select an option below:",
                reply_markup=keyboard
            )
            await callback_query.answer()
            return
        
        # Settings menu
        if data == "settings_menu":
            keyboard = await get_settings_keyboard(user_id)
            await callback_query.message.edit_text(
                "⚙️ **Settings Menu**\n\n"
                "Configure your bot preferences:",
                reply_markup=keyboard
            )
            await callback_query.answer()
            return
        
        # Premium info
        if data == "premium_info":
            is_premium = check_premium(user_id)
            
            premium_text = "🌟 **PREMIUM FEATURES**\n\n"
            
            if is_premium:
                user_data = get_user(user_id)
                expiry = user_data.get("premium_expiry")
                if expiry:
                    expiry_str = expiry.strftime("%Y-%m-%d %H:%M")
                    premium_text += f"✅ **You are Premium!**\n"
                    premium_text += f"📅 Expires: {expiry_str}\n\n"
            else:
                premium_text += "✨ **Benefits:**\n"
                premium_text += "• Higher batch limits\n"
                premium_text += "• Priority processing\n"
                premium_text += "• No waiting time\n"
                premium_text += "• Advanced features\n\n"
                premium_text += "💎 **Pricing:** Contact owner\n\n"
                premium_text += "📞 Contact: @technicalserena"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 Contact Owner", url=Config.OWNER_LINK)],
                [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
            ])
            
            await callback_query.message.edit_text(premium_text, reply_markup=keyboard)
            await callback_query.answer()
            return
        
        # Get Premium
        if data == "get_premium":
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("👤 Contact for Premium", url=Config.OWNER_LINK)],
                [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
            ])
            
            await callback_query.message.edit_text(
                "🌟 **GET PREMIUM**\n\n"
                "Contact owner @technicalserena for premium access.\n\n"
                "**Benefits:**\n"
                "• Unlimited batches\n"
                "• Priority processing\n"
                "• No delays\n"
                "• Premium support",
                reply_markup=keyboard
            )
            await callback_query.answer()
            return
        
        # My Stats
        if data == "my_stats":
            stats = get_user_stats(user_id)
            
            stats_text = (
                f"📊 **YOUR STATISTICS**\n\n"
                f"📁 Total Tasks: {stats['total_tasks']}\n"
                f"✅ Completed: {stats['completed_tasks']}\n"
                f"📨 Total Messages: {stats['total_messages']}\n"
                f"✓ Successful: {stats['successful_messages']}\n"
                f"✗ Failed: {stats['failed_messages']}\n\n"
            )
            
            if check_premium(user_id):
                stats_text += "👑 **Status:** Premium User\n"
            else:
                stats_text += "👤 **Status:** Regular User\n"
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("📦 Start Batch", callback_data="batch_menu")],
                [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
            ])
            
            await callback_query.message.edit_text(stats_text, reply_markup=keyboard)
            await callback_query.answer()
            return
        
        # Set Chat ID
        if data == "set_chat_id":
            await callback_query.message.edit_text(
                "📨 **SET CHAT ID**\n\n"
                "Send the Chat ID where files should be sent:\n\n"
                "**Formats:**\n"
                "• Your User ID: `1234567890`\n"
                "• Channel ID: `-1001234567890`\n"
                "• Group ID: `-1234567890`\n\n"
                "**Note:** You must be admin in channels/groups."
            )
            
            try:
                response = await client.wait_for(
                    filters.text & filters.private & filters.user(user_id),
                    timeout=60
                )
                
                try:
                    chat_id = int(response.text)
                    update_user_setting(user_id, "set_chat_id", chat_id)
                    
                    await callback_query.message.edit_text(
                        f"✅ **Chat ID Set!**\n\n"
                        f"Files will be sent to: `{chat_id}`\n\n"
                        "You can change this anytime in settings."
                    )
                except ValueError:
                    await callback_query.message.edit_text(
                        "❌ **Invalid ID!**\n\n"
                        "Please send a valid numeric Chat ID."
                    )
                    
            except asyncio.TimeoutError:
                await callback_query.message.edit_text(
                    "⏰ **Timeout!**\n\n"
                    "Please use /setting again."
                )
            
            await callback_query.answer()
            return
        
        # Toggle Button Text
        if data == "toggle_button":
            current = get_user_setting(user_id, "button_text", "Serena")
            new_text = "Kumari" if current == "Serena" else "Serena"
            update_user_setting(user_id, "button_text", new_text)
            
            await callback_query.message.edit_text(
                f"✅ **Button Text Updated!**\n\n"
                f"Changed to: **{new_text}**\n\n"
                "This will be reflected in bot buttons."
            )
            await callback_query.answer()
            return
        
        # Logout Session
        if data == "logout_session":
            deleted = delete_user_session(user_id)
            
            if deleted:
                text = "✅ **Logged Out Successfully!**\n\nYour session has been removed."
            else:
                text = "ℹ️ **No Active Session**\n\nYou are not logged in."
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("🔙 Back to Settings", callback_data="settings_menu")]
            ])
            
            await callback_query.message.edit_text(text, reply_markup=keyboard)
            await callback_query.answer()
            return
        
        # Reset Settings
        if data == "reset_settings":
            # Delete session
            delete_user_session(user_id)
            # Delete settings
            delete_user_settings(user_id)
            
            await callback_query.message.edit_text(
                "🔄 **Settings Reset!**\n\n"
                "All settings have been restored to defaults:\n"
                "• Session cleared\n"
                "• Preferences reset\n"
                "• Chat ID removed\n\n"
                "You can now reconfigure the bot."
            )
            await callback_query.answer()
            return
        
        # Batch Menu
        if data == "batch_menu":
            # Check if logged in
            if not get_user_session(user_id):
                keyboard = InlineKeyboardMarkup([
                    [InlineKeyboardButton("🔑 Login Now", callback_data="login_now")],
                    [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
                ])
                
                await callback_query.message.edit_text(
                    "⚠️ **Login Required!**\n\n"
                    "You need to login first to use batch recovery.\n"
                    "Click 'Login Now' to start.",
                    reply_markup=keyboard
                )
                await callback_query.answer()
                return
            
            await callback_query.message.edit_text(
                "📦 **BATCH RECOVERY**\n\n"
                "Send a channel message link:\n\n"
                "**Format:**\n"
                "`https://t.me/channelname/123`\n\n"
                "or use command:\n"
                "`/batch https://t.me/channelname/123`"
            )
            await callback_query.answer()
            return
        
        # Login Now
        if data == "login_now":
            await callback_query.message.delete()
            await login_command(client, callback_query.message)
            await callback_query.answer()
            return
        
        # Help Menu
        if data == "help_menu":
            await callback_query.message.delete()
            await help_command(client, callback_query.message)
            await callback_query.answer()
            return
        
        # My Profile
        if data == "my_profile":
            user_data = get_user(user_id)
            
            profile_text = (
                f"👤 **YOUR PROFILE**\n\n"
                f"🆔 User ID: `{user_id}`\n"
                f"📛 Name: {user_data['name'] if user_data else 'N/A'}\n"
                f"📅 Joined: {user_data['join_date'].strftime('%Y-%m-%d') if user_data else 'N/A'}\n"
            )
            
            if check_premium(user_id):
                profile_text += f"👑 Status: **Premium User**\n"
                if user_data and user_data.get('premium_expiry'):
                    expiry = user_data['premium_expiry'].strftime('%Y-%m-%d')
                    profile_text += f"📅 Premium until: {expiry}\n"
            else:
                profile_text += "👤 Status: Regular User\n"
            
            # Check session
            has_session = bool(get_user_session(user_id))
            profile_text += f"🔐 Session: {'Active' if has_session else 'Not Logged In'}\n\n"
            
            profile_text += "Use /setting to manage your account."
            
            keyboard = InlineKeyboardMarkup([
                [InlineKeyboardButton("⚙️ Settings", callback_data="settings_menu")],
                [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
            ])
            
            await callback_query.message.edit_text(profile_text, reply_markup=keyboard)
            await callback_query.answer()
            return
        
        # Task Status
        if data.startswith("status_"):
            try:
                task_id = ObjectId(data.replace("status_", ""))
                await status_command(client, callback_query.message)
            except:
                await callback_query.answer("Task not found!", show_alert=True)
            await callback_query.answer()
            return
        
        # Cancel Task
        if data.startswith("cancel_"):
            try:
                task_id = ObjectId(data.replace("cancel_", ""))
                cancel_user_tasks(user_id)
                await callback_query.message.edit_text("✅ Task cancelled!")
            except:
                await callback_query.answer("Error cancelling task!", show_alert=True)
            await callback_query.answer()
            return
        
    except Exception as e:
        logger.error(f"Callback error: {e}")
        await callback_query.answer("Error occurred!", show_alert=True)

# ==================== MAIN FUNCTION ====================
async def main():
    """Main function to run the bot"""
    logger.info("🤖 Initializing Telegram File Recovery Bot...")
    
    # Check required environment variables
    required = ['API_ID', 'API_HASH', 'BOT_TOKEN']
    for var in required:
        if not getattr(Config, var, None):
            logger.error(f"Missing {var}")
            return
    
    try:
        # Start the bot
        await bot.start()
        
        # Get bot info
        me = await bot.get_me()
        logger.info(f"✅ Bot Started Successfully!")
        logger.info(f"🤖 Username: @{me.username}")
        logger.info(f"🆔 ID: {me.id}")
        logger.info(f"📛 Name: {me.first_name}")
        
        # Send startup log
        try:
            await send_log_to_channel(
                bot, 
                f"Bot Started\nUsername: @{me.username}\nID: {me.id}", 
                "STARTUP"
            )
        except:
            logger.warning("Could not send startup log")
        
        logger.info("🔄 Bot is now running and listening for messages...")
        
        # Keep bot running
        await idle()
        
    except Exception as e:
        logger.error(f"❌ Bot startup failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        try:
            await bot.stop()
            logger.info("Bot stopped gracefully")
        except:
            pass

# Export main function for main.py to use
if __name__ == "__main__":
    asyncio.run(main())
