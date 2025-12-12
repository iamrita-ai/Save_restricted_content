# ===================== main.py (PART 1/3) =====================
import os
import re
import asyncio
import threading
import tempfile
import shutil
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any

from flask import Flask

from pyrogram import Client, filters
from pyrogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    Message,
    CallbackQuery,
)
from pyrogram.errors import (
    PhoneNumberInvalid,
    PhoneCodeInvalid,
    SessionPasswordNeeded,
    FloodWait,
    RPCError,
)

from motor.motor_asyncio import AsyncIOMotorClient

# ---------- ENVIRONMENT (Render par set karo) ----------
# Render ke "Environment" section me set karo:
# API_ID, API_HASH, BOT_TOKEN, MONGO_URI, (optional) START_IMAGE_URL
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
MONGO_URI = os.environ["MONGO_URI"]

START_IMAGE_URL = os.environ.get("START_IMAGE_URL")  # optional banner image URL

# ---------- CONSTANTS ----------
LOGS_CHANNEL_ID = -1003286415377  # logs channel
FORCE_SUB_CHANNEL = "serenaunzipbot"  # force-sub channel username ya ID
OWNER_IDS = {1598576202, 6518065496}  # owners

MAX_BATCH_LIMIT = 1000
SLEEP_SECONDS = 12

# ---------- MONGO ----------
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["serena_bot"]
users_coll = db["users"]  # user settings + sessions

# ---------- GLOBAL STATES (RAM) ----------
# login state
pending_logins: Dict[int, Dict[str, Any]] = {}  # user_id -> {client, phone, phone_code_hash}
login_steps: Dict[int, str] = {}  # "await_phone" / "await_code"

# batch state
batch_states: Dict[int, Dict[str, Any]] = {}  # user_id -> {"step", "link"}
batch_tasks: Dict[int, asyncio.Task] = {}     # running batch tasks

# settings state (Set Chat ID)
settings_states: Dict[int, str] = {}  # user_id -> "await_chat_id"

# ---------- BOT CLIENT ----------
bot = Client(
    "serena_main_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
)


# ---------- UTILS ----------

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


async def get_user_doc(user_id: int) -> Dict[str, Any]:
    doc = await users_coll.find_one({"_id": user_id})
    if not doc:
        doc = {
            "_id": user_id,
            "session_string": None,
            "phone": None,
            "premium_until": None,
            "set_chat_id": None,
            "replace_serena": False,
        }
        await users_coll.insert_one(doc)
    return doc


async def set_user_field(user_id: int, field: str, value: Any):
    await users_coll.update_one(
        {"_id": user_id},
        {"$set": {field: value}},
        upsert=True,
    )


async def unset_user_fields(user_id: int, fields: list[str]):
    update = {"$unset": {f: "" for f in fields}}
    await users_coll.update_one({"_id": user_id}, update)


async def is_premium(user_id: int) -> bool:
    doc = await get_user_doc(user_id)
    exp = doc.get("premium_until")
    if not exp:
        return False
    # Mongo se datetime ISO string bhi aa sakta hai, handle karein
    if isinstance(exp, str):
        try:
            exp = datetime.fromisoformat(exp)
        except Exception:
            return False
    return datetime.utcnow() < exp


async def log_to_channel(text: str):
    """Sabhi important actions ko logs channel me bhejo."""
    try:
        await bot.send_message(LOGS_CHANNEL_ID, text)
    except Exception:
        # logs channel unavailable / bot removed etc.
        pass


async def require_premium(msg: Message) -> bool:
    """Premium check. Owner hamesha allowed."""
    user_id = msg.from_user.id
    if is_owner(user_id):
        return True
    if await is_premium(user_id):
        return True
    await msg.reply_text(
        "Ye bot premium hai.\n"
        "Aapke paas premium access nahi hai.\n"
        "Owner se contact kare: @technicalserena"
    )
    return False


async def check_force_sub_message(msg: Message) -> bool:
    """
    Force-sub channel membership check.
    True => user joined; False => command ko yahin rok do.
    """
    user_id = msg.from_user.id
    try:
        member = await bot.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        status = getattr(member, "status", "").lower()
        if status in ("kicked", "banned", "left"):
            raise ValueError("Not member")
        return True
    except Exception:
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton(
                        "Join Updates", url="https://t.me/serenaunzipbot"
                    ),
                    InlineKeyboardButton(
                        "Check", callback_data="check_fsub"
                    ),
                ]
            ]
        )
        await msg.reply_text(
            "Bot use karne ke liye pehle update channel join karein.\n"
            "Join karne ke baad 'Check' dabayen.",
            reply_markup=kb,
        )
        return False


def parse_telegram_link(link: str) -> Tuple[Any, int]:
    """
    t.me link se chat identifier aur starting message id nikalta hai.
    Return: (chat_identifier, message_id)
    - Public channel: ('username', msg_id)
    - Private /c link: (-100xxxx, msg_id)
    """
    link = link.strip()

    if not link.startswith("http"):
        link = "https://" + link.lstrip("/")

    # /c/ private link: https://t.me/c/123456789/456
    m = re.search(r"t\.me/c/(\d+)/(\d+)", link)
    if m:
        internal_id = int(m.group(1))
        msg_id = int(m.group(2))
        chat_id = int("-100" + str(internal_id))
        return chat_id, msg_id

    # Public: https://t.me/username/123
    m = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)", link)
    if m:
        username = m.group(1)
        msg_id = int(m.group(2))
        return username, msg_id

    raise ValueError("Invalid Telegram message link")


def replace_serena_text(text: Optional[str], enabled: bool) -> Optional[str]:
    if not text or not enabled:
        return text
    out = text.replace("Serena", "Kumari").replace("SERENA", "KUMARI")
    return out

# ===================== main.py (PART 2/3) =====================

# ---------- /start ----------
@bot.on_message(filters.command("start") & filters.private)
async def cmd_start(client: Client, msg: Message):
    user = msg.from_user
    await get_user_doc(user.id)  # ensure doc exists

    intro = (
        "👋 Welcome to *SERENA* Recovery Bot.\n\n"
        "Ye bot aapke Telegram account (user session) se login karke "
        "aapke channels / chats se important files, photos, videos, "
        "wagairah nikal kar aapko bhej sakta hai.\n\n"
        "⚠️ Is bot ka istemal sirf apne hi accounts / channels ke liye karein.\n"
        "Brand Name: *SERENA*"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Join Updates", url="https://t.me/serenaunzipbot"
                ),
                InlineKeyboardButton(
                    "Contact Owner", url="https://t.me/technicalserena"
                ),
            ]
        ]
    )

    if START_IMAGE_URL:
        await client.send_photo(
            chat_id=msg.chat.id,
            photo=START_IMAGE_URL,
            caption=intro,
            reply_markup=kb,
        )
    else:
        await msg.reply_text(intro, reply_markup=kb)

    await log_to_channel(f"/start by {user.id} (@{user.username})")


# ---------- /help ----------
@bot.on_message(filters.command("help") & filters.private)
async def cmd_help(client: Client, msg: Message):
    text = (
        "/start - Welcome message\n"
        "/help - Ye madad wala message\n"
        "/login - Apne Telegram number se login (OTP se)\n"
        "/batch - Kisi channel/chat ke message link se batch files nikaalo\n"
        "/status - Aapka login/premium/status dekhna\n"
        "/settings - Set Chat ID, text replace settings\n"
        "/cancel - Login ya batch jaise ongoing kaam cancel karna\n\n"
        "Owner-only:\n"
        "/addpremium user_id days - Premium add karein (e.g. /addpremium 123456789 12)\n"
        "/remove user_id - Premium hata dein\n\n"
        "Note:\n"
        "- Login ke liye +91 se Indian number use hoga, aap sirf 10 digit bhejoge.\n"
        "- Saare logs (actions + files) logs channel me bhi jayenge."
    )
    await msg.reply_text(text)


# ---------- /status ----------
@bot.on_message(filters.command("status") & filters.private)
async def cmd_status(client: Client, msg: Message):
    user_id = msg.from_user.id
    doc = await get_user_doc(user_id)

    is_logged_in = bool(doc.get("session_string"))
    prem = await is_premium(user_id)
    prem_text = "NO"
    if prem:
        exp = doc.get("premium_until")
        if isinstance(exp, str):
            try:
                exp = datetime.fromisoformat(exp)
            except Exception:
                pass
        if isinstance(exp, datetime):
            prem_text = f"YES (till {exp.strftime('%Y-%m-%d %H:%M:%S')} UTC)"
        else:
            prem_text = "YES"

    set_chat = doc.get("set_chat_id")
    replace_flag = bool(doc.get("replace_serena", False))
    running_batch = user_id in batch_tasks

    text = (
        f"👤 User ID: `{user_id}`\n"
        f"🔐 Logged in (user session): {'YES' if is_logged_in else 'NO'}\n"
        f"💎 Premium: {prem_text}\n"
        f"📡 Set Chat ID: `{set_chat}`\n"
        f"✏️ Replace 'Serena'→'Kumari': {'ON' if replace_flag else 'OFF'}\n"
        f"📦 Batch running: {'YES' if running_batch else 'NO'}"
    )
    await msg.reply_text(text)
    await log_to_channel(f"/status by {user_id}")


# ---------- /cancel ----------
@bot.on_message(filters.command("cancel") & filters.private)
async def cmd_cancel(client: Client, msg: Message):
    user_id = msg.from_user.id
    cancelled_any = False

    # Cancel login flow
    if login_steps.get(user_id):
        login_steps.pop(user_id, None)
        data = pending_logins.pop(user_id, None)
        if data and "client" in data:
            try:
                await data["client"].disconnect()
            except Exception:
                pass
        cancelled_any = True

    # Cancel settings state
    if settings_states.get(user_id):
        settings_states.pop(user_id, None)
        cancelled_any = True

    # Cancel batch task
    task = batch_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()
        cancelled_any = True

    batch_states.pop(user_id, None)

    if cancelled_any:
        await msg.reply_text("Ongoing task cancel kar diya gaya hai.")
        await log_to_channel(f"/cancel used by {user_id}")
    else:
        await msg.reply_text("Koi active task nahi mila jise cancel kar sakun.")


# ---------- /settings ----------
@bot.on_message(filters.command("settings") & filters.private)
async def cmd_settings(client: Client, msg: Message):
    user_id = msg.from_user.id

    if not await require_premium(msg):
        return
    if not await check_force_sub_message(msg):
        return

    doc = await get_user_doc(user_id)
    replace_flag = bool(doc.get("replace_serena", False))

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "Set Chat ID", callback_data="set_chat_id"
                ),
                InlineKeyboardButton(
                    "Reset", callback_data="reset_settings"
                ),
            ],
            [
                InlineKeyboardButton(
                    f"Replace 'Serena'→'Kumari': {'ON' if replace_flag else 'OFF'}",
                    callback_data="toggle_replace",
                )
            ],
        ]
    )

    await msg.reply_text("Settings:", reply_markup=kb)


# ---------- Owner: /addpremium ----------
@bot.on_message(filters.command("addpremium") & filters.private)
async def cmd_addpremium(client: Client, msg: Message):
    user_id = msg.from_user.id
    if not is_owner(user_id):
        await msg.reply_text("Sirf owner is command ka use kar sakta hai.")
        return

    parts = msg.text.strip().split()
    if len(parts) < 3:
        await msg.reply_text("Use: /addpremium user_id days\nExample: /addpremium 123456789 12")
        return

    try:
        target_id = int(parts[1])
        days = int(parts[2])
    except ValueError:
        await msg.reply_text("user_id aur days dono integer hone chahiye.")
        return

    expires = datetime.utcnow() + timedelta(days=days)
    await users_coll.update_one(
        {"_id": target_id},
        {"$set": {"premium_until": expires}},
        upsert=True,
    )
    await msg.reply_text(
        f"User `{target_id}` ko {days} din ke liye premium de diya gaya hai.",
        quote=True,
    )
    await log_to_channel(
        f"Owner {user_id} added premium for {target_id} for {days} days (till {expires})."
    )


# ---------- Owner: /remove ----------
@bot.on_message(filters.command("remove") & filters.private)
async def cmd_remove_premium(client: Client, msg: Message):
    user_id = msg.from_user.id
    if not is_owner(user_id):
        await msg.reply_text("Sirf owner is command ka use kar sakta hai.")
        return

    parts = msg.text.strip().split()
    if len(parts) < 2:
        await msg.reply_text("Use: /remove user_id\nExample: /remove 123456789")
        return

    try:
        target_id = int(parts[1])
    except ValueError:
        await msg.reply_text("user_id integer hona chahiye.")
        return

    await users_coll.update_one(
        {"_id": target_id},
        {"$unset": {"premium_until": ""}},
    )
    await msg.reply_text(f"User `{target_id}` se premium hata diya gaya hai.")
    await log_to_channel(f"Owner {user_id} removed premium for {target_id}")


# ---------- CALLBACK QUERIES (/settings buttons + force-sub check) ----------
@bot.on_callback_query()
async def on_callback(client: Client, cq: CallbackQuery):
    data = cq.data
    user_id = cq.from_user.id

    # Force-sub re-check
    if data == "check_fsub":
        try:
            member = await client.get_chat_member(FORCE_SUB_CHANNEL, user_id)
            status = getattr(member, "status", "").lower()
            if status in ("kicked", "banned", "left"):
                await cq.answer("Abhi tak join nahi kiya.", show_alert=True)
            else:
                await cq.answer("Joined detected! Ab aap bot use kar sakte hain.", show_alert=True)
        except Exception:
            await cq.answer("Channel join check me error. Thodi der baad try karein.", show_alert=True)
        return

    # Settings callbacks
    if data == "set_chat_id":
        settings_states[user_id] = "await_chat_id"
        await cq.message.reply_text(
            "Jis chat/channel me files bhejni hain uska chat ID bhejiye.\n"
            "Example: `-1001234567890`",
            quote=True,
        )
        await cq.answer("Please send chat ID now.")
        return

    if data == "reset_settings":
        await unset_user_fields(user_id, ["set_chat_id", "replace_serena"])
        await cq.message.reply_text("Settings reset kar di gayi hain.")
        await cq.answer("Reset done.")
        return

    if data == "toggle_replace":
        doc = await get_user_doc(user_id)
        current = bool(doc.get("replace_serena", False))
        new_val = not current
        await set_user_field(user_id, "replace_serena", new_val)
        await cq.message.reply_text(
            f"Replace 'Serena'→'Kumari' ab: {'ON' if new_val else 'OFF'}"
        )
        await cq.answer("Updated.")
        return

  # ===================== main.py (PART 3/3) =====================

# ---------- /login ----------
@bot.on_message(filters.command("login") & filters.private)
async def cmd_login(client: Client, msg: Message):
    user_id = msg.from_user.id

    # Premium + force-sub check
    if not await require_premium(msg):
        return
    if not await check_force_sub_message(msg):
        return

    login_steps[user_id] = "await_phone"
    await msg.reply_text(
        "Apna 10 digit Indian mobile number bhejiye (binā +91).\n"
        "Example: `9876543210`"
    )
    await log_to_channel(f"/login started by {user_id}")


async def handle_login_phone(msg: Message):
    user_id = msg.from_user.id
    text = (msg.text or "").strip()

    if not re.fullmatch(r"\d{10}", text):
        await msg.reply_text("Please valid 10-digit mobile number bhejiye (sirf digits).")
        return

    phone = "+91" + text
    # Pyrogram client for this login
    user_client = Client(
        name=f"login_{user_id}",
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True,
    )

    try:
        await user_client.connect()
        sent = await user_client.send_code(phone)
        pending_logins[user_id] = {
            "client": user_client,
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
        }
        login_steps[user_id] = "await_code"
        await msg.reply_text(
            "Telegram ne aapke number par OTP bheja hai.\n"
            "Wohi OTP yahan bhejiye."
        )
    except PhoneNumberInvalid:
        await msg.reply_text("Ye phone number invalid hai. Sahi number try karein.")
        try:
            await user_client.disconnect()
        except Exception:
            pass
        pending_logins.pop(user_id, None)
        login_steps.pop(user_id, None)
    except FloodWait as e:
        await msg.reply_text(f"Telegram flood wait: {e.value} seconds. Thodi der baad try karein.")
        try:
            await user_client.disconnect()
        except Exception:
            pass
        pending_logins.pop(user_id, None)
        login_steps.pop(user_id, None)
    except Exception as e:
        await msg.reply_text(f"Login start me error: {e}")
        try:
            await user_client.disconnect()
        except Exception:
            pass
        pending_logins.pop(user_id, None)
        login_steps.pop(user_id, None)


async def handle_login_code(msg: Message):
    user_id = msg.from_user.id
    code = (msg.text or "").strip()

    data = pending_logins.get(user_id)
    if not data:
        await msg.reply_text("Login session mil nahin raha. /login se dobara start karein.")
        login_steps.pop(user_id, None)
        return

    user_client: Client = data["client"]
    phone = data["phone"]
    phone_code_hash = data["phone_code_hash"]

    try:
        await user_client.sign_in(
            phone_number=phone,
            phone_code_hash=phone_code_hash,
            phone_code=code,
        )
    except PhoneCodeInvalid:
        await msg.reply_text("OTP galat hai, sahi OTP bhejiye.")
        return
    except SessionPasswordNeeded:
        await msg.reply_text(
            "Aapke account par 2-step verification password laga hua hai.\n"
            "Ye bot password handle nahi karta. 2FA disable karke phir try karein."
        )
        try:
            await user_client.disconnect()
        except Exception:
            pass
        pending_logins.pop(user_id, None)
        login_steps.pop(user_id, None)
        return
    except FloodWait as e:
        await msg.reply_text(f"Flood wait: {e.value} seconds. Thodi der baad try karein.")
        return
    except Exception as e:
        await msg.reply_text(f"Sign-in error: {e}")
        try:
            await user_client.disconnect()
        except Exception:
            pass
        pending_logins.pop(user_id, None)
        login_steps.pop(user_id, None)
        return

    # Success -> export session string
    try:
        session_string = await user_client.export_session_string()
    except Exception as e:
        await msg.reply_text(f"Session export me error: {e}")
        try:
            await user_client.disconnect()
        except Exception:
            pass
        pending_logins.pop(user_id, None)
        login_steps.pop(user_id, None)
        return

    await set_user_field(user_id, "session_string", session_string)
    await set_user_field(user_id, "phone", phone)

    await msg.reply_text("Login successful! Ab aap /batch aur /settings use kar sakte hain.")
    await log_to_channel(f"User {user_id} login success with phone {phone} (masked).")

    try:
        await user_client.disconnect()
    except Exception:
        pass

    pending_logins.pop(user_id, None)
    login_steps.pop(user_id, None)


# ---------- /batch ----------
@bot.on_message(filters.command("batch") & filters.private)
async def cmd_batch(client: Client, msg: Message):
    user_id = msg.from_user.id

    if not await require_premium(msg):
        return
    if not await check_force_sub_message(msg):
        return

    doc = await get_user_doc(user_id)
    if not doc.get("session_string"):
        await msg.reply_text("Pehle /login karke apne Telegram account se login karein.")
        return

    if user_id in batch_tasks:
        await msg.reply_text("Pehle ka batch chal raha hai. /cancel se cancel karein.")
        return

    batch_states[user_id] = {"step": "wait_link", "link": None}
    await msg.reply_text(
        "Batch mode start.\n"
        "Ab us channel/chat ka *message link* bhejiye jahan se files nikalni hain.\n"
        "Example: `https://t.me/channel_username/123` ya `https://t.me/c/123456789/123`"
    )
    await log_to_channel(f"/batch started by {user_id}")


async def handle_batch_link(msg: Message):
    user_id = msg.from_user.id
    text = (msg.text or "").strip()

    try:
        # sirf validation, values abhi store nahi kar rahe
        parse_telegram_link(text)
    except Exception:
        await msg.reply_text("Ye valid Telegram message link nahi lag raha. Sahi link bhejiye.")
        return

    batch_states[user_id] = {"step": "wait_count", "link": text}
    await msg.reply_text(
        f"Kitne messages nikalne hain? (Maximum {MAX_BATCH_LIMIT})\n"
        "Sirf number bhejiye, example: `50`"
    )


async def handle_batch_count(msg: Message):
    user_id = msg.from_user.id
    text = (msg.text or "").strip()

    try:
        count = int(text)
    except ValueError:
        await msg.reply_text("Please sirf integer number bhejiye.")
        return

    if count <= 0:
        await msg.reply_text("Number 1 se zyada hona chahiye.")
        return

    if count > MAX_BATCH_LIMIT:
        await msg.reply_text(
            f"Max limit {MAX_BATCH_LIMIT} hai. {MAX_BATCH_LIMIT} messages liye jayenge."
        )
        count = MAX_BATCH_LIMIT

    state = batch_states.get(user_id)
    if not state or not state.get("link"):
        await msg.reply_text("Link wali step missing hai. /batch se dobara start karein.")
        batch_states.pop(user_id, None)
        return

    link = state["link"]
    batch_states[user_id]["step"] = "running"

    # Run worker as background task
    task = asyncio.create_task(batch_worker(user_id, link, count))
    batch_tasks[user_id] = task

    await msg.reply_text(
        f"Batch start ho gaya. {count} messages fetch karne ki koshish hogi.\n"
        f"Har message ke beech ~{SLEEP_SECONDS} second wait hoga.\n"
        "Cancel ke liye /cancel bhejiye."
    )


# ---------- Settings: Set Chat ID text handler ----------
async def handle_settings_chat_id(msg: Message):
    user_id = msg.from_user.id
    text = (msg.text or "").strip()

    try:
        chat_id = int(text)
    except ValueError:
        await msg.reply_text("Chat ID integer hona chahiye (example: -1001234567890).")
        return

    await set_user_field(user_id, "set_chat_id", chat_id)
    settings_states.pop(user_id, None)
    await msg.reply_text(f"Set Chat ID saved: `{chat_id}`")


# ---------- MAIN TEXT ROUTER (for login, batch, settings flows) ----------
@bot.on_message(
    filters.private
    & ~filters.command(
        [
            "start",
            "help",
            "status",
            "cancel",
            "settings",
            "login",
            "batch",
            "addpremium",
            "remove",
        ]
    )
)
async def on_plain_text(client: Client, msg: Message):
    user_id = msg.from_user.id

    # Login flow
    if login_steps.get(user_id) == "await_phone":
        await handle_login_phone(msg)
        return
    if login_steps.get(user_id) == "await_code":
        await handle_login_code(msg)
        return

    # Settings: set chat id
    if settings_states.get(user_id) == "await_chat_id":
        await handle_settings_chat_id(msg)
        return

    # Batch flow
    state = batch_states.get(user_id)
    if state:
        if state.get("step") == "wait_link":
            await handle_batch_link(msg)
            return
        if state.get("step") == "wait_count":
            await handle_batch_count(msg)
            return

    # Koi state nahi -> ignore ya simple reply
    # Yahan kuch bhi nahi kar rahe, taki bot silent rahe
    # Agar chahein to yahan ek message bhi bhej sakte hain.


# ---------- BATCH WORKER ----------
async def batch_worker(user_id: int, link: str, count: int):
    temp_dir = tempfile.mkdtemp(prefix=f"serena_{user_id}_")
    try:
        doc = await get_user_doc(user_id)
        session_string = doc.get("session_string")
        if not session_string:
            await bot.send_message(
                user_id, "Session nahi mila. Pehle /login karke dobara try karein."
            )
            return

        set_chat_id = doc.get("set_chat_id")
        replace_flag = bool(doc.get("replace_serena", False))

        try:
            chat_identifier, start_msg_id = parse_telegram_link(link)
        except Exception as e:
            await bot.send_message(
                user_id, f"Link parse karte waqt error: {e}\n/batch se dobara try karein."
            )
            return

        # User session client
        user_app = Client(
            name=f"user_{user_id}",
            api_id=API_ID,
            api_hash=API_HASH,
            session_string=session_string,
            in_memory=True,
        )

        await user_app.start()

        for i in range(count):
            msg_id = start_msg_id + i

            try:
                src_msg = await user_app.get_messages(chat_identifier, msg_id)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                try:
                    src_msg = await user_app.get_messages(chat_identifier, msg_id)
                except Exception:
                    continue
            except Exception:
                # message fetch fail (deleted / no access etc.)
                continue

            if not src_msg:
                continue

            text = src_msg.text or src_msg.caption or ""
            text = replace_serena_text(text, replace_flag)

            sent: Optional[Message] = None

            if src_msg.media:
                # Media download
                try:
                    file_path = await user_app.download_media(
                        src_msg, file_name=temp_dir
                    )
                except Exception:
                    continue

                if not file_path:
                    continue

                try:
                    # User ko bhejo
                    try:
                        sent = await bot.send_document(
                            chat_id=user_id,
                            document=file_path,
                            caption=text or None,
                        )
                    except RPCError:
                        # Agar document fail hua to as photo try kar sakte hain,
                        # but yahan simple hi rakhte hain.
                        sent = None

                    # Agar set_chat_id hai to wahan forward karo
                    if sent and set_chat_id:
                        try:
                            await bot.forward_messages(
                                chat_id=set_chat_id,
                                from_chat_id=user_id,
                                message_ids=sent.id,
                            )
                        except RPCError:
                            pass

                    # Logs channel me bhi
                    if sent:
                        try:
                            await bot.forward_messages(
                                chat_id=LOGS_CHANNEL_ID,
                                from_chat_id=user_id,
                                message_ids=sent.id,
                            )
                        except RPCError:
                            pass
                finally:
                    # File delete from disk
                    try:
                        os.remove(file_path)
                    except OSError:
                        pass
            else:
                # Sirf text
                if not text:
                    text = "(empty message)"
                try:
                    sent = await bot.send_message(user_id, text)
                except RPCError:
                    sent = None

                if sent and set_chat_id:
                    try:
                        await bot.forward_messages(
                            chat_id=set_chat_id,
                            from_chat_id=user_id,
                            message_ids=sent.id,
                        )
                    except RPCError:
                        pass

                if sent:
                    try:
                        await bot.forward_messages(
                            chat_id=LOGS_CHANNEL_ID,
                            from_chat_id=user_id,
                            message_ids=sent.id,
                        )
                    except RPCError:
                        pass

            # Next message se pehle sleep
            if i < count - 1:
                await asyncio.sleep(SLEEP_SECONDS)

        await bot.send_message(user_id, "Batch complete ho gaya.")
    except asyncio.CancelledError:
        # /cancel ki wajah se
        try:
            await bot.send_message(user_id, "Batch cancel kar diya gaya.")
        except Exception:
            pass
        raise
    except Exception as e:
        try:
            await bot.send_message(user_id, f"Batch me error aaya: {e}")
        except Exception:
            pass
    finally:
        batch_tasks.pop(user_id, None)
        batch_states.pop(user_id, None)
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------- FLASK (Render healthcheck) ----------
flask_app = Flask(__name__)


@flask_app.route("/")
def index():
    return "SERENA Bot is running.", 200


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    # debug=False, use_reloader=False otherwise thread me double start hoga
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ---------- MAIN ----------
if __name__ == "__main__":
    # Flask ko alag thread me chalao (Render ko open port chahiye)
    threading.Thread(target=run_flask, daemon=True).start()

    print("Starting SERENA bot...")
    bot.run()
