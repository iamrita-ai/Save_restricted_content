import asyncio
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from config import Config
from database import *
from utils import *
import datetime

# User Bot Clients को store करने का dictionary (user_id: client)
user_clients = {}

bot = Client(
    "file_recovery_bot",
    api_id=Config.API_ID,
    api_hash=Config.API_HASH,
    bot_token=Config.BOT_TOKEN
)

# ==================== HELPER FUNCTIONS ====================
def get_force_sub_keyboard():
    """Force subscribe channel और owner contact के लिए inline keyboard बनाता है।"""
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Join Channel", url=Config.FORCE_SUB_CHANNEL)],
            [InlineKeyboardButton("Contact Owner", url=Config.OWNER_LINK)]
        ]
    )
    return keyboard

def check_premium(user_id):
    """Check करता है कि user premium है या नहीं।"""
    user = users_collection.find_one({"user_id": user_id})
    if user and user.get("is_premium"):
        expiry = user.get("premium_expiry")
        if expiry and expiry > datetime.datetime.now():
            return True
        else:
            # Premium expired, remove status
            remove_premium_user(user_id)
    return False

# ==================== COMMAND HANDLERS ====================
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client: Client, message: Message):
    """Welcome message और force subscribe buttons दिखाता है।"""
    user_id = message.from_user.id
    add_user(user_id, message.from_user.first_name)
    
    welcome_text = (
        "👋 **Welcome to File Recovery Bot!**\n\n"
        "This bot helps you recover files from your lost account's channels.\n\n"
        "**Available Commands:**\n"
        "• /login - Login with phone number\n"
        "• /batch - Start batch file recovery\n"
        "• /status - Check current task status\n"
        "• /cancel - Cancel ongoing task\n"
        "• /setting - Configure bot settings\n"
        "• /help - Show help guide\n\n"
        "Please join our channel and contact owner for support."
    )
    
    await message.reply_text(
        welcome_text,
        reply_markup=get_force_sub_keyboard(),
        disable_web_page_preview=True
    )

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client: Client, message: Message):
    """User को detailed guide दिखाता है।"""
    help_text = (
        "📖 **Bot Usage Guide**\n\n"
        "1. **Login Process**\n"
        "   Use /login to authenticate with your lost account's phone number and OTP.\n\n"
        "2. **Batch Recovery**\n"
        "   Use /batch with a channel message link to start recovering files.\n"
        "   Format: `/batch https://t.me/channel/123`\n\n"
        "3. **Settings**\n"
        "   Use /setting to configure:\n"
        "   • Set Chat ID for direct forwarding\n"
        "   • Change button text (Serena/Kumari)\n\n"
        "4. **Task Management**\n"
        "   • /status - Check ongoing task progress\n"
        "   • /cancel - Cancel current task\n\n"
        "5. **Premium Features**\n"
        "   Owners can add/remove premium users with /addpremium and /removepremium\n\n"
        "**Note:** The bot adds a 12-second delay between messages to avoid flooding."
    )
    await message.reply_text(help_text)

@bot.on_message(filters.command("login") & filters.private)
async def login_command(client: Client, message: Message):
    """User को phone number और OTP के माध्यम से login कराता है।"""
    user_id = message.from_user.id
    
    # Step 1: Phone number माँगो
    await message.reply_text(
        "Please enter your phone number in international format (e.g., +919876543210):"
    )
    
    try:
        # Phone number input का इंतजार करो
        phone_msg = await client.listen(user_id, filters.text, timeout=300)
        phone_number = phone_msg.text
        
        # User bot client create करो
        user_client = Client(
            f"user_{user_id}",
            api_id=Config.API_ID,
            api_hash=Config.API_HASH,
            in_memory=True
        )
        
        await user_client.connect()
        
        # Step 2: OTP request भेजो
        sent_code = await user_client.send_code(phone_number)
        await message.reply_text("OTP sent! Please enter the OTP you received:")
        
        # OTP input का इंतजार करो
        otp_msg = await client.listen(user_id, filters.text, timeout=300)
        otp_code = otp_msg.text
        
        # Step 3: User को sign in कराओ
        try:
            await user_client.sign_in(
                phone_number,
                sent_code.phone_code_hash,
                otp_code
            )
        except Exception as e:
            # Password की जरूरत हो सकती है
            if "password" in str(e).lower():
                await message.reply_text("Please enter your 2FA password:")
                password_msg = await client.listen(user_id, filters.text, timeout=300)
                await user_client.check_password(password_msg.text)
            else:
                raise e
        
        # Step 4: Session string save करो
        session_string = await user_client.export_session_string()
        save_user_session(user_id, session_string)
        
        # User client को dictionary में store करो
        user_clients[user_id] = user_client
        
        await message.reply_text("✅ Login successful! Your session has been saved.")
        
        # Log channel में notify करो
        log_msg = f"User {user_id} logged in successfully with phone: {phone_number[:5]}******"
        await send_log_to_channel(client, log_msg, "LOGIN")
        
    except asyncio.TimeoutError:
        await message.reply_text("Login timeout. Please try /login again.")
    except Exception as e:
        await message.reply_text(f"Login failed: {str(e)}")

@bot.on_message(filters.command("batch") & filters.private)
async def batch_command(client: Client, message: Message):
    """Batch file recovery process start करता है।"""
    user_id = message.from_user.id
    
    # Step 1: User के पास valid session है या नहीं check करो
    session_string = get_user_session(user_id)
    if not session_string:
        await message.reply_text(
            "You need to login first. Use /login to authenticate with your account."
        )
        return
    
    # Step 2: Channel link माँगो
    if len(message.command) < 2:
        await message.reply_text(
            "Please provide a channel message link.\n"
            "Format: `/batch https://t.me/channel/123`"
        )
        return
    
    # Link से chat_id और message_id extract करो
    try:
        link = message.command[1]
        parts = link.split("/")
        chat_id = parts[-2]
        start_msg_id = int(parts[-1])
    except:
        await message.reply_text("Invalid link format. Please provide a valid Telegram message link.")
        return
    
    # Step 3: Number of messages माँगो
    await message.reply_text(
        f"Starting from message ID: {start_msg_id}\n"
        f"How many messages do you want to recover? (Max: {Config.BATCH_LIMIT})"
    )
    
    try:
        count_msg = await client.listen(user_id, filters.text, timeout=60)
        count = int(count_msg.text)
        
        if count > Config.BATCH_LIMIT:
            await message.reply_text(f"Count exceeds maximum limit of {Config.BATCH_LIMIT}. Using maximum limit.")
            count = Config.BATCH_LIMIT
    except (asyncio.TimeoutError, ValueError):
        await message.reply_text("Invalid input or timeout. Please try /batch again.")
        return
    
    # Step 4: Task database में create करो
    from bson import ObjectId
    task_id = ObjectId()
    batch_tasks_collection.insert_one({
        "_id": task_id,
        "user_id": user_id,
        "chat_id": chat_id,
        "start_msg_id": start_msg_id,
        "count": count,
        "status": "processing",
        "progress": 0,
        "successful": 0,
        "failed": 0,
        "created_at": datetime.datetime.now()
    })
    
    # Step 5: User को confirmation दो
    await message.reply_text(
        f"✅ Batch task started!\n\n"
        f"**Details:**\n"
        f"• Chat: `{chat_id}`\n"
        f"• Start Message ID: `{start_msg_id}`\n"
        f"• Total Messages: `{count}`\n"
        f"• Status: Processing\n\n"
        f"Use /status to check progress or /cancel to stop."
    )
    
    # Step 6: Batch processing start करो (background में)
    # Note: Actual processing को separate async task में run करना चाहिए
    await message.reply_text("Starting batch processing... This may take some time.")
    
    # User client initialize करो
    user_client = user_clients.get(user_id)
    if not user_client:
        user_client = Client(
            f"user_{user_id}",
            session_string=session_string,
            api_id=Config.API_ID,
            api_hash=Config.API_HASH
        )
        await user_client.start()
        user_clients[user_id] = user_client
    
    # Target chat ID check करो (settings से)
    target_chat_id = get_user_setting(user_id, "set_chat_id", user_id)
    
    # Process batch (simplified example - actual implementation में background task use करो)
    asyncio.create_task(
        process_batch(user_client, chat_id, start_msg_id, count, target_chat_id, user_id, task_id)
    )

@bot.on_message(filters.command("status") & filters.private)
async def status_command(client: Client, message: Message):
    """Current task का status दिखाता है।"""
    user_id = message.from_user.id
    
    task = batch_tasks_collection.find_one(
        {"user_id": user_id, "status": {"$in": ["processing", "paused"]}},
        sort=[("created_at", -1)]
    )
    
    if not task:
        await message.reply_text("No active tasks found.")
        return
    
    status_text = (
        f"📊 **Task Status**\n\n"
        f"**Chat ID:** `{task['chat_id']}`\n"
        f"**Start Message ID:** `{task['start_msg_id']}`\n"
        f"**Total Messages:** `{task['count']}`\n"
        f"**Processed:** `{task['progress']}`\n"
        f"**Successful:** `{task.get('successful', 0)}`\n"
        f"**Failed:** `{task.get('failed', 0)}`\n"
        f"**Status:** {task['status'].title()}"
    )
    
    await message.reply_text(status_text)

@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_command(client: Client, message: Message):
    """Ongoing task को cancel करता है।"""
    user_id = message.from_user.id
    
    result = batch_tasks_collection.update_one(
        {"user_id": user_id, "status": "processing"},
        {"$set": {"status": "cancelled"}}
    )
    
    if result.modified_count > 0:
        await message.reply_text("✅ Current task has been cancelled.")
    else:
        await message.reply_text("No active task to cancel.")

@bot.on_message(filters.command("setting") & filters.private)
async def setting_command(client: Client, message: Message):
    """User settings configure करने का interface दिखाता है।"""
    user_id = message.from_user.id
    
    # Current settings fetch करो
    set_chat_id = get_user_setting(user_id, "set_chat_id", "Not Set")
    button_text = get_user_setting(user_id, "button_text", "Serena")
    
    # Inline keyboard create करो
    keyboard = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton(f"Set Chat ID: {set_chat_id}", callback_data="set_chat_id")],
            [InlineKeyboardButton(f"Button Text: {button_text}", callback_data="toggle_button")],
            [InlineKeyboardButton("Reset Settings", callback_data="reset_settings")]
        ]
    )
    
    settings_text = (
        "⚙️ **Bot Settings**\n\n"
        "1. **Set Chat ID** - Files will be directly sent to this chat\n"
        "2. **Button Text** - Toggle between 'Serena' and 'Kumari'\n"
        "3. **Reset Settings** - Restore default settings\n\n"
        "Click any option below to configure:"
    )
    
    await message.reply_text(settings_text, reply_markup=keyboard)

# ==================== ADMIN COMMANDS ====================
@bot.on_message(filters.command("addpremium") & filters.user(Config.OWNER_IDS))
async def add_premium_command(client: Client, message: Message):
    """Owner किसी user को premium add कर सकता है।"""
    if len(message.command) < 3:
        await message.reply_text("Format: `/addpremium user_id days`")
        return
    
    try:
        target_user_id = int(message.command[1])
        days = int(message.command[2])
        
        add_premium_user(target_user_id, days)
        await message.reply_text(f"✅ User {target_user_id} added as premium for {days} days.")
        
        # Log channel में notify करो
        log_msg = f"Premium added: User {target_user_id} for {days} days by {message.from_user.id}"
        await send_log_to_channel(client, log_msg, "PREMIUM")
    except ValueError:
        await message.reply_text("Invalid user ID or days format.")

@bot.on_message(filters.command("removepremium") & filters.user(Config.OWNER_IDS))
async def remove_premium_command(client: Client, message: Message):
    """Owner किसी user से premium status हटा सकता है।"""
    if len(message.command) < 2:
        await message.reply_text("Format: `/removepremium user_id`")
        return
    
    try:
        target_user_id = int(message.command[1])
        remove_premium_user(target_user_id)
        await message.reply_text(f"✅ User {target_user_id} removed from premium.")
        
        # Log channel में notify करो
        log_msg = f"Premium removed: User {target_user_id} by {message.from_user.id}"
        await send_log_to_channel(client, log_msg, "PREMIUM")
    except ValueError:
        await message.reply_text("Invalid user ID format.")

# ==================== CALLBACK QUERY HANDLER ====================
@bot.on_callback_query()
async def callback_handler(client: Client, callback_query):
    """Inline buttons के callback queries को handle करता है।"""
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    if data == "set_chat_id":
        await callback_query.message.reply_text(
            "Please send the Chat ID where you want files to be sent directly.\n"
            "You can use your own ID or a channel ID (e.g., -1001234567890):"
        )
        
        try:
            chat_id_msg = await client.listen(user_id, filters.text, timeout=60)
            chat_id = chat_id_msg.text
            
            # Validate chat ID
            try:
                chat_id_int = int(chat_id)
                update_user_setting(user_id, "set_chat_id", chat_id_int)
                await callback_query.message.reply_text(f"✅ Chat ID set to: `{chat_id_int}`")
            except ValueError:
                await callback_query.message.reply_text("Invalid Chat ID. Please send a numeric ID.")
                
        except asyncio.TimeoutError:
            await callback_query.message.reply_text("Timeout. Please try again.")
    
    elif data == "toggle_button":
        current_text = get_user_setting(user_id, "button_text", "Serena")
        new_text = "Kumari" if current_text == "Serena" else "Serena"
        update_user_setting(user_id, "button_text", new_text)
        
        await callback_query.message.edit_text(
            f"✅ Button text changed to: **{new_text}**\n\n"
            f"Use /setting to configure other options."
        )
    
    elif data == "reset_settings":
        # All settings reset करो
        settings_collection.delete_many({"user_id": user_id})
        await callback_query.message.edit_text("✅ All settings have been reset to defaults.")
    
    await callback_query.answer()
