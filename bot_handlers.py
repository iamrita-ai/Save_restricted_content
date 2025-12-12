# ========== PART 1: IMPORTS & SETUP ==========
import os
import asyncio
import logging
from datetime import datetime, timedelta
from pyrogram import Client, filters, idle
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message, CallbackQuery
from pyrogram.errors import FloodWait, UserNotParticipant, ChatAdminRequired
from pymongo import MongoClient
import config  # Apni config file import karen

# Logging setup karen
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# MongoDB se connect karen
mongo_client = MongoClient(config.MONGO_DB_URL)
db = mongo_client['serena_file_bot']
# Collections banayen
users_col = db['users']
premium_col = db['premium_users']
tasks_col = db['active_tasks']
settings_col = db['user_settings']

# Pyrogram Bot Client initialize karen
bot = Client(
    "serena_bot",
    api_id=config.API_ID,
    api_hash=config.API_HASH,
    bot_token=config.BOT_TOKEN,
    workers=50  # Simultaneous tasks ke liye
)

# ========== HELPER FUNCTIONS ==========
def is_owner(user_id):
    """Check kare user owner hai ya nahi"""
    return user_id in config.OWNER_IDS

def is_premium(user_id):
    """Check kare user premium hai ya nahi"""
    user = premium_col.find_one({"user_id": user_id})
    if not user:
        return False
    # Check kare premium expiry date abhi baki hai ya nahi
    expiry_date = user.get('expiry_date')
    if expiry_date and expiry_date < datetime.utcnow():
        premium_col.delete_one({"user_id": user_id})  # Expired premium hata de
        return False
    return True

async def force_sub_check(user_id):
    """Check kare user ne force channel join kiya hai ya nahi"""
    try:
        user = await bot.get_chat_member(config.FORCE_SUB_CHANNEL.strip("@"), user_id)
        if user.status in ["member", "administrator", "creator"]:
            return True
    except UserNotParticipant:
        return False
    except Exception as e:
        logger.error(f"Force sub check error: {e}")
        return True  # Error ki soorat mein allow kar de
    return False

async def send_log(message_text, photo=None, document=None):
    """Logs channel par message bheje"""
    try:
        if photo:
            await bot.send_photo(config.LOG_CHANNEL_ID, photo, caption=message_text[:1024])
        elif document:
            await bot.send_document(config.LOG_CHANNEL_ID, document, caption=message_text[:1024])
        else:
            await bot.send_message(config.LOG_CHANNEL_ID, message_text)
    except Exception as e:
        logger.error(f"Log bhejne mein error: {e}")

# ========== BASIC COMMANDS ==========
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    user_id = message.from_user.id
    
    # Force subscription check
    if not await force_sub_check(user_id):
        join_button = InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 Update Channel Join Karen", url=config.FORCE_SUB_CHANNEL),
            InlineKeyboardButton("👑 Owner", url=config.OWNER_CHANNEL)
        ]])
        await message.reply_photo(
            photo="https://telegra.ph/file/example.jpg",  # Apni start image ka URL daalen
            caption="**⚠️ Please join our channel to use this bot!**\n\n"
                    "Bot Brand: **SERENA**\n"
                    "Aapke loss hue account ki important files recover karega.",
            reply_markup=join_button
        )
        return
    
    # User ko database mein add/update kare
    users_col.update_one(
        {"user_id": user_id},
        {"$set": {"first_seen": datetime.utcnow(), "username": message.from_user.username}},
        upsert=True
    )
    
    welcome_buttons = InlineKeyboardMarkup([[
        InlineKeyboardButton("📂 Batch Start Karein", callback_data="batch_start"),
        InlineKeyboardButton("⚙️ Settings", callback_data="user_settings")
    ], [
        InlineKeyboardButton("📢 Channel", url=config.FORCE_SUB_CHANNEL),
        InlineKeyboardButton("👑 Owner", url=config.OWNER_CHANNEL)
    ]])
    
    await message.reply_photo(
        photo="https://telegra.ph/file/example.jpg",  # Apni start image ka URL daalen
        caption="**🤖 Welcome to SERENA File Recovery Bot!**\n\n"
                "Main aapke purane loss hue account ke important channels se "
                "files recover kar sakta hoon.\n\n"
                "**Available Commands:**\n"
                "`/batch` - Channel se files recover karein\n"
                "`/login` - Apne number se login karein\n"
                "`/setting` - Bot settings change karein\n"
                "`/status` - Current task ka status dekhein\n"
                "`/help` - Help guide dekhein\n\n"
                "Bot Brand: **SERENA**",
        reply_markup=welcome_buttons
    )
    
    # Log bheje
    await send_log(f"🆕 Naya user start kiya:\n"
                   f"User: {message.from_user.mention}\n"
                   f"ID: `{user_id}`")

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client, message: Message):
    help_text = """
**🆘 SERENA Bot Help Guide**

**📌 Basic Commands:**
• `/start` - Bot ko start karein
• `/help` - Yeh help message
• `/batch` - Channel se files recover karein
• `/login` - Phone number se login karein
• `/setting` - Apne settings change karein
• `/status` - Current task ka status
• `/cancel` - Running task cancel karein

**📂 Batch Process:**
1. `/batch` command use karein
2. Channel ka link paste karein
3. Kitni messages/files chahiye number mein daalen
4. Bot aapko files DM mein bhej dega

**🔐 Login Process:**
1. `/login` command use karein
2. Apna 10-digit number bhejein (+91 ke bagair)
3. Telegram se OTP code aayega
4. OTP bot ko bhejein
5. Aapka session create ho jayega

**⚙️ Settings:**
• **Set Chat ID** - Files directly kis channel mein jaayein
• **Reset Settings** - Sabhi settings reset karein
• Text replace: "Serena" → "Kumari"

**👑 Premium Features:**
• `/addpremium user_id days` - User ko premium banayein
• `/removepremium user_id` - User se premium hataein

**⚠️ Important:**
• Har 2 messages ke beech 12 seconds ka delay hota hai
• Ek batch mein maximum 1000 messages nikal sakte hain
• Saari logs hamare channel mein save hoti hain
"""
    await message.reply(help_text, disable_web_page_preview=True)

# ========== CANCEL COMMAND ==========
@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_command(client, message: Message):
    user_id = message.from_user.id
    
    # Active task check kare
    task = tasks_col.find_one({"user_id": user_id, "status": "processing"})
    if not task:
        await message.reply("ℹ️ Aapka koi active task nahi chalta hua hai.")
        return
    
    # Task cancel kare
    tasks_col.update_one(
        {"_id": task["_id"]},
        {"$set": {"status": "cancelled", "cancelled_at": datetime.utcnow()}}
    )
    
    await message.reply("✅ Aapka current task successfully cancel kar diya gaya hai.")
    await send_log(f"❌ Task cancelled by user:\nUser ID: `{user_id}`\nTask ID: `{task['_id']}`")

# ========== STATUS COMMAND ==========
@bot.on_message(filters.command("status") & filters.private)
async def status_command(client, message: Message):
    user_id = message.from_user.id
    
    # User ka active task check kare
    task = tasks_col.find_one({"user_id": user_id, "status": "processing"})
    if task:
        status_msg = (
            f"**📊 Current Task Status**\n\n"
            f"• **Task ID:** `{task['_id']}`\n"
            f"• **Start Time:** `{task.get('started_at', 'N/A')}`\n"
            f"• **Messages Processed:** `{task.get('processed', 0)}`\n"
            f"• **Total Messages:** `{task.get('total', 'N/A')}`\n"
            f"• **Status:** `Processing...`\n\n"
            f"`/cancel` se task cancel kar sakte hain."
        )
    else:
        # Agar koi active task nahi hai to general status bataye
        user_data = users_col.find_one({"user_id": user_id})
        premium_status = "✅ Premium" if is_premium(user_id) else "❌ Regular"
        
        status_msg = (
            f"**👤 Your Status**\n\n"
            f"• **User ID:** `{user_id}`\n"
            f"• **Premium Status:** {premium_status}\n"
            f"• **First Seen:** `{user_data.get('first_seen', 'N/A') if user_data else 'N/A'}`\n"
            f"• **Active Tasks:** `0`\n\n"
            f"Aapka koi active task nahi chalta hua hai.\n"
            f"`/batch` se naya task start kar sakte hain."
        )
    
    await message.reply(status_msg)

# ========== PART 2: BATCH PROCESSING & LOGIN ==========

# ========== BATCH COMMAND ==========
@bot.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message: Message):
    user_id = message.from_user.id
    
    # Force subscription check
    if not await force_sub_check(user_id):
        await message.reply("⚠️ Bot use karne se pehle hamara channel join karein!")
        return
    
    # Premium check (agar aap premium feature enable karna chaahen)
    if not is_premium(user_id) and not is_owner(user_id):
        # Regular users ke liye limit lagayein (optional)
        pass
    
    # Pehle se koi active task to nahi chal raha
    active_task = tasks_col.find_one({"user_id": user_id, "status": "processing"})
    if active_task:
        await message.reply("⚠️ Aapka ek task already process ho raha hai!\n"
                           "`/status` se check karein ya `/cancel` se cancel karein.")
        return
    
    # User se channel link maange
    await message.reply(
        "**📥 Batch Process Start**\n\n"
        "Please mujhe uss channel ka link bhejein jahan se aap files recover karna chahte hain.\n\n"
        "**Format:**\n"
        "• `https://t.me/channel_username`\n"
        "• `@channel_username`\n\n"
        "Ya phir forward koi bhi message ussi channel se.",
        disable_web_page_preview=True
    )
    
    # User ka response wait kare
    try:
        response = await client.listen.Message(filters.text | filters.forwarded, id=user_id, timeout=300)
        
        # Channel ID/username extract kare
        channel_identifier = None
        
        if response.forward_from_chat:
            # Agar message forwarded hai
            channel_identifier = response.forward_from_chat.id
            channel_name = response.forward_from_chat.title
        elif response.text:
            # Agar link/text diya hai
            text = response.text.strip()
            if text.startswith("https://t.me/"):
                channel_identifier = text.split("/")[-1]
            elif text.startswith("@"):
                channel_identifier = text[1:]
            else:
                channel_identifier = text
            
            # Channel ka info get kare
            try:
                chat = await client.get_chat(channel_identifier)
                channel_name = chat.title
                channel_identifier = chat.id
            except Exception as e:
                await message.reply(f"❌ Channel access nahi kar paaye: {e}\n"
                                   "Kripya firse try karein.")
                return
        
        if not channel_identifier:
            await message.reply("❌ Valid channel link nahi mila. Firse try karein.")
            return
        
        # Number of messages maange
        await message.reply(
            f"**✅ Channel Found:** `{channel_name}`\n\n"
            f"Ab please bataein:\n"
            f"**Kitni messages/files recover karni hain?**\n\n"
            f"Maximum limit: `{config.MAX_BATCH_LIMIT}` messages\n"
            f"(Sirf number type karein, jaise: 50)"
        )
        
        count_response = await client.listen.Message(filters.text, id=user_id, timeout=300)
        
        try:
            msg_count = int(count_response.text.strip())
            if msg_count <= 0:
                await message.reply("❌ Please 1 se bada number daalein.")
                return
            if msg_count > config.MAX_BATCH_LIMIT:
                await message.reply(f"❌ Maximum limit {config.MAX_BATCH_LIMIT} hai. Chota number daalein.")
                return
        except ValueError:
            await message.reply("❌ Invalid number. Please sirf digits daalein.")
            return
        
        # User ka session check kare (login kiya hai ya nahi)
        user_session = users_col.find_one({"user_id": user_id})
        if not user_session or "phone_number" not in user_session:
            await message.reply("⚠️ Pehle aapko login karna hoga!\n"
                               "`/login` command use karein apna phone number verify karne ke liye.")
            return
        
        # Task create kare database mein
        task_id = tasks_col.insert_one({
            "user_id": user_id,
            "channel_id": channel_identifier,
            "channel_name": channel_name,
            "message_count": msg_count,
            "status": "processing",
            "processed": 0,
            "started_at": datetime.utcnow(),
            "last_update": datetime.utcnow()
        }).inserted_id
        
        # Confirmation message
        confirm_buttons = InlineKeyboardMarkup([[
            InlineKeyboardButton("✅ Start Processing", callback_data=f"process_{task_id}"),
            InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_{task_id}")
        ]])
        
        await message.reply(
            f"**📋 Task Created Successfully!**\n\n"
            f"• **Task ID:** `{task_id}`\n"
            f"• **Channel:** `{channel_name}`\n"
            f"• **Messages:** `{msg_count}`\n"
            f"• **Estimated Time:** `{msg_count * config.SEND_DELAY / 60:.1f} minutes`\n\n"
            f"Start karne ke liye button dabayein:",
            reply_markup=confirm_buttons
        )
        
        # Log bheje
        await send_log(
            f"🔄 Naya batch task create hua:\n"
            f"User: `{user_id}`\n"
            f"Channel: `{channel_name}`\n"
            f"Messages: `{msg_count}`\n"
            f"Task ID: `{task_id}`"
        )
        
    except asyncio.TimeoutError:
        await message.reply("⏰ Timeout ho gaya! Firse `/batch` command try karein.")

# ========== LOGIN COMMAND ==========
@bot.on_message(filters.command("login") & filters.private)
async def login_command(client, message: Message):
    user_id = message.from_user.id
    
    await message.reply(
        "**🔐 Telegram Login**\n\n"
        "Aapke phone number se login karke main aapke loss hue account ki files recover kar sakta hoon.\n\n"
        "**Please apna 10-digit mobile number bhejein:**\n"
        "(Example: `9876543210`)\n\n"
        "Note: +91 automatically add ho jayega."
    )
    
    try:
        # Phone number input le
        phone_msg = await client.listen.Message(filters.text, id=user_id, timeout=300)
        phone_number = phone_msg.text.strip()
        
        # Validate phone number
        if not phone_number.isdigit() or len(phone_number) != 10:
            await message.reply("❌ Invalid phone number. 10 digits hona chahiye.\nFirse try karein.")
            return
        
        full_phone = "+91" + phone_number
        
        # Telethon se session banaye (separate implementation)
        # Yeh part aapko alag se implement karna hoga
        # Ya phir pyrogram user session use karein
        
        # Database mein save kare
        users_col.update_one(
            {"user_id": user_id},
            {"$set": {
                "phone_number": full_phone,
                "login_date": datetime.utcnow(),
                "has_session": True
            }},
            upsert=True
        )
        
        await message.reply(
            f"✅ **Login Successful!**\n\n"
            f"Phone number saved: `{full_phone}`\n\n"
            f"Ab aap `/batch` command use kar sakte hain files recover karne ke liye."
        )
        
        # Log bheje
        await send_log(f"🔑 Naya login:\nUser ID: `{user_id}`\nPhone: `{full_phone}`")
        
    except asyncio.TimeoutError:
        await message.reply("⏰ Timeout ho gaya! Firse `/login` command try karein.")
    except Exception as e:
        await message.reply(f"❌ Error: {e}\nPlease firse try karein.")

# ========== PREMIUM COMMANDS (OWNER ONLY) ==========
@bot.on_message(filters.command("addpremium") & filters.private)
async def add_premium(client, message: Message):
    user_id = message.from_user.id
    
    # Check if owner
    if not is_owner(user_id):
        await message.reply("❌ Ye command sirf owner ke liye hai!")
        return
    
    try:
        # Command format: /addpremium user_id days
        args = message.text.split()
        if len(args) != 3:
            await message.reply("❌ Format: `/addpremium user_id days`")
            return
        
        target_id = int(args[1])
        days = int(args[2])
        
        expiry_date = datetime.utcnow() + timedelta(days=days)
        
        premium_col.update_one(
            {"user_id": target_id},
            {"$set": {
                "user_id": target_id,
                "added_by": user_id,
                "added_date": datetime.utcnow(),
                "expiry_date": expiry_date,
                "days": days
            }},
            upsert=True
        )
        
        await message.reply(
            f"✅ **Premium Added Successfully!**\n\n"
            f"• **User ID:** `{target_id}`\n"
            f"• **Days:** `{days}`\n"
            f"• **Expiry Date:** `{expiry_date}`\n\n"
            f"User ab premium features use kar sakta hai."
        )
        
        # Log bheje
        await send_log(
            f"⭐ Premium user add hua:\n"
            f"User ID: `{target_id}`\n"
            f"Days: `{days}`\n"
            f"Added by: `{user_id}`"
        )
        
        # User ko notify kare (agar possible ho)
        try:
            await bot.send_message(
                target_id,
                f"🎉 **Congratulations!**\n\n"
                f"Aapko {days} din ke liye premium access mil gaya hai!\n"
                f"Expiry: {expiry_date}\n\n"
                f"Ab aap premium features use kar sakte hain."
            )
        except:
            pass
            
    except ValueError:
        await message.reply("❌ Invalid user_id ya days. Please check karein.")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

@bot.on_message(filters.command("removepremium") & filters.private)
async def remove_premium(client, message: Message):
    user_id = message.from_user.id
    
    # Check if owner
    if not is_owner(user_id):
        await message.reply("❌ Ye command sirf owner ke liye hai!")
        return
    
    try:
        # Command format: /removepremium user_id
        args = message.text.split()
        if len(args) != 2:
            await message.reply("❌ Format: `/removepremium user_id`")
            return
        
        target_id = int(args[1])
        
        result = premium_col.delete_one({"user_id": target_id})
        
        if result.deleted_count > 0:
            await message.reply(f"✅ User `{target_id}` se premium access hata diya gaya.")
            
            # Log bheje
            await send_log(f"🗑️ Premium remove hua:\nUser ID: `{target_id}`\nRemoved by: `{user_id}`")
            
            # User ko notify kare
            try:
                await bot.send_message(
                    target_id,
                    "ℹ️ **Premium Access Ended**\n\n"
                    "Aapka premium access khatam ho gaya hai.\n"
                    "Agar phir se premium lena ho to owner se contact karein."
                )
            except:
                pass
        else:
            await message.reply(f"ℹ️ User `{target_id}` premium list mein nahi tha.")
            
    except ValueError:
        await message.reply("❌ Invalid user_id. Please check karein.")
    except Exception as e:
        await message.reply(f"❌ Error: {e}")

  # ========== PART 3: SETTINGS & CALLBACK HANDLERS ==========

# ========== SETTINGS COMMAND ==========
@bot.on_message(filters.command("setting") & filters.private)
async def settings_command(client, message: Message):
    user_id = message.from_user.id
    
    # User ki current settings get kare
    user_settings = settings_col.find_one({"user_id": user_id})
    if not user_settings:
        user_settings = {"user_id": user_id, "set_chat_id": None, "text_replace": True}
        settings_col.insert_one(user_settings)
    
    set_chat_id = user_settings.get("set_chat_id", "Not Set")
    text_replace = user_settings.get("text_replace", True)
    
    # Settings buttons
    buttons = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"📝 Set Chat ID: {set_chat_id}", callback_data="set_chat_id")],
        [InlineKeyboardButton(f"🔄 Text Replace: {'On' if text_replace else 'Off'}", callback_data="toggle_replace")],
        [InlineKeyboardButton("🗑️ Reset Settings", callback_data="reset_settings")],
        [InlineKeyboardButton("❌ Close", callback_data="close_settings")]
    ])
    
    await message.reply(
        f"**⚙️ User Settings**\n\n"
        f"• **Set Chat ID:** `{set_chat_id}`\n"
        f"  (Yahan files directly forward ho jayengi)\n\n"
        f"• **Text Replace:** `{'Serena → Kumari' if text_replace else 'Off'}`\n\n"
        f"**Instructions:**\n"
        f"1. **Set Chat ID** - Kisi channel/group ka ID daalein\n"
        f"2. **Text Replace** - 'Serena' ko 'Kumari' se replace kare\n"
        f"3. **Reset** - Sab settings default par kare",
        reply_markup=buttons
    )

# ========== CALLBACK QUERY HANDLERS ==========
@bot.on_callback_query()
async def handle_callbacks(client, callback_query: CallbackQuery):
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    # Process callback button actions
    if data == "user_settings":
        await settings_command(client, callback_query.message)
    
    elif data == "batch_start":
        await batch_command(client, callback_query.message)
    
    elif data.startswith("process_"):
        # Task processing start kare
        task_id = data.split("_")[1]
        
        # Task status update kare
        task = tasks_col.find_one({"_id": task_id})
        if not task or task["status"] != "processing":
            await callback_query.answer("❌ Task nahi mila ya cancel ho gaya!")
            return
        
        await callback_query.answer("🔄 Processing started...")
        
        # Aapko yahan actual message fetching aur sending ka logic implement karna hoga
        # Yeh sample hai:
        await callback_query.message.edit_text(
            f"**🔄 Processing Task...**\n\n"
            f"Task ID: `{task_id}`\n"
            f"Messages: `0/{task['message_count']}` processed\n"
            f"Status: Starting..."
        )
        
        # Yahan aapka actual processing code aayega
        # Messages fetch kare, send kare, delay de, etc.
        
    elif data.startswith("cancel_"):
        task_id = data.split("_")[1]
        
        tasks_col.update_one(
            {"_id": task_id},
            {"$set": {"status": "cancelled", "cancelled_at": datetime.utcnow()}}
        )
        
        await callback_query.answer("✅ Task cancelled!")
        await callback_query.message.edit_text(
            f"**❌ Task Cancelled**\n\n"
            f"Task ID: `{task_id}`\n"
            f"Cancelled at: `{datetime.utcnow()}`"
        )
    
    elif data == "set_chat_id":
        await callback_query.message.edit_text(
            "**📝 Set Chat ID**\n\n"
            "Please mujhe uss channel/group ka ID bhejein\n"
            "jahan aap files directly forward karna chahte hain.\n\n"
            "**Format:**\n"
            "• Channel ID: `-100xxxxxxxxxx`\n"
            "• Ya channel ka @username\n\n"
            "`/cancel` type karke cancel kar sakte hain."
        )
        
        try:
            response = await client.listen.Message(filters.text, id=user_id, timeout=300)
            
            if response.text == "/cancel":
                await callback_query.message.edit_text("❌ Chat ID setting cancelled.")
                return
            
            chat_id = response.text.strip()
            
            # Validate chat ID
            try:
                chat = await client.get_chat(chat_id)
                valid_chat_id = chat.id
                
                settings_col.update_one(
                    {"user_id": user_id},
                    {"$set": {"set_chat_id": valid_chat_id}},
                    upsert=True
                )
                
                await callback_query.message.edit_text(
                    f"✅ **Chat ID Set Successfully!**\n\n"
                    f"• **Chat:** {chat.title}\n"
                    f"• **ID:** `{valid_chat_id}`\n\n"
                    f"Ab saari files isi chat mein directly forward ho jayengi."
                )
                
                await send_log(
                    f"⚙️ User ne chat ID set kiya:\n"
                    f"User: `{user_id}`\n"
                    f"Chat ID: `{valid_chat_id}`\n"
                    f"Chat: {chat.title}"
                )
                
            except Exception as e:
                await callback_query.message.edit_text(f"❌ Invalid Chat ID: {e}")
                
        except asyncio.TimeoutError:
            await callback_query.message.edit_text("⏰ Timeout! Firse try karein.")
    
    elif data == "toggle_replace":
        user_settings = settings_col.find_one({"user_id": user_id})
        current = user_settings.get("text_replace", True) if user_settings else True
        
        settings_col.update_one(
            {"user_id": user_id},
            {"$set": {"text_replace": not current}},
            upsert=True
        )
        
        status = "OFF" if current else "ON"
        await callback_query.answer(f"Text Replace {status} ho gaya!")
        await settings_command(client, callback_query.message)
    
    elif data == "reset_settings":
        settings_col.update_one(
            {"user_id": user_id},
            {"$set": {"set_chat_id": None, "text_replace": True}},
            upsert=True
        )
        
        await callback_query.answer("✅ Settings reset ho gaye!")
        await callback_query.message.edit_text(
            "**🔄 Settings Reset Successfully!**\n\n"
            "Saari settings default values par reset ho gayi hain.\n\n"
            "• Set Chat ID: `Not Set`\n"
            "• Text Replace: `ON`"
        )
    
    elif data == "close_settings":
        await callback_query.message.delete()
    
    # Always answer callback query
    await callback_query.answer()

# ========== MAIN BOT RUNNER ==========
async def main():
    await bot.start()
    print("✅ Serena Bot started successfully!")
    
    # Bot information print kare
    me = await bot.get_me()
    print(f"🤖 Bot Username: @{me.username}")
    print(f"🆔 Bot ID: {me.id}")
    print(f"👑 Owner IDs: {config.OWNER_IDS}")
    
    # Idle mode - bot running rahe
    await idle()
    
    await bot.stop()
    print("👋 Bot stopped!")

if __name__ == "__main__":
    # Session folder create kare (agar nahi hai)
    os.makedirs(config.SESSION_FOLDER, exist_ok=True)
    
    # Main function run kare
    asyncio.run(main())
