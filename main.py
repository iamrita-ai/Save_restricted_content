# ===================== main.py (PART 1/3) =====================
import os
import re
import io
import time
import qrcode
import asyncio
import threading
import tempfile
import shutil
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List

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
    PhoneCodeExpired,
    SessionPasswordNeeded,
    FloodWait,
    RPCError,
    UserNotParticipant,
    ChannelPrivate,
    ChatAdminRequired,
    ChatWriteForbidden,
    ChatIdInvalid,
    PeerIdInvalid,
    QrCodeExpired,
)

from motor.motor_asyncio import AsyncIOMotorClient

# ---------- ENVIRONMENT ----------
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
MONGO_URI = os.environ["MONGO_URI"]

# Optional: /start banner image
START_IMAGE_URL = os.environ.get("START_IMAGE_URL")

# ---------- CONSTANTS ----------
LOGS_CHANNEL_ID = -1003286415377  # Logs channel
FORCE_SUB_CHANNEL = "serenaunzipbot"  # Force-sub link diya gaya
OWNER_IDS = {1598576202, 6518065496}

MAX_BATCH_LIMIT = 1000
SLEEP_SECONDS = 12

# ---------- MONGO ----------
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["serena_bot"]
users_coll = db["users"]  # user settings + sessions

# ---------- GLOBAL STATES ----------
# Phone + OTP login
pending_logins: Dict[int, Dict[str, Any]] = {}  # user_id -> {client, phone, phone_code_hash}
login_steps: Dict[int, str] = {}  # 'session_wait', 'phone_wait_number', 'phone_wait_code'

# QR login tasks
login_qr_tasks: Dict[int, asyncio.Task] = {}

# Batch
batch_states: Dict[int, Dict[str, Any]] = {}  # user_id -> {"step", "link", "task_id"}
batch_tasks: Dict[int, asyncio.Task] = {}

# Settings state
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


def humanbytes(num: float) -> str:
    """Bytes ko human-readable (MB, GB,...) me convert kare."""
    if num is None:
        return "0 B"
    num = float(num)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024 or unit == "TB":
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} TB"


def time_formatter(seconds: float) -> str:
    """Seconds ko 1d 2h 3m 4s jaise format me convert kare."""
    try:
        seconds = int(seconds)
    except Exception:
        return "0s"

    if seconds <= 0:
        return "0s"

    m, s = divmod(seconds, 60)
    h, m = divmod(m, 60)
    d, h = divmod(h, 24)
    parts = []
    if d:
        parts.append(f"{d}d")
    if h:
        parts.append(f"{h}h")
    if m:
        parts.append(f"{m}m")
    if s:
        parts.append(f"{s}s")
    return " ".join(parts)


def format_timedelta(td: timedelta) -> str:
    """timedelta ko readable remaining time me convert kare."""
    seconds = int(td.total_seconds())
    return time_formatter(seconds)


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


async def get_user_doc(user_id: int) -> Dict[str, Any]:
    """User ka document Mongo se lo, agar nahi to default banao."""
    doc = await users_coll.find_one({"_id": user_id})
    now = datetime.utcnow()
    if not doc:
        doc = {
            "_id": user_id,
            "session_string": None,
            "phone": None,
            "premium_until": None,
            "set_chat_id": None,
            "replace_serena": False,
            "created_at": now,
            "last_seen": now,
            "stats": {
                "batches_run": 0,
                "messages_downloaded": 0,
                "media_downloaded": 0,
            },
            "history": [],
        }
        await users_coll.insert_one(doc)
        return doc

    updates = {"last_seen": now}
    if "created_at" not in doc:
        updates["created_at"] = now
    if "stats" not in doc:
        updates["stats"] = {
            "batches_run": 0,
            "messages_downloaded": 0,
            "media_downloaded": 0,
        }
    if "history" not in doc:
        updates["history"] = []

    if updates:
        await users_coll.update_one({"_id": user_id}, {"$set": updates})
        doc.update(updates)

    return doc


async def set_user_field(user_id: int, field: str, value: Any):
    await users_coll.update_one(
        {"_id": user_id},
        {"$set": {field: value}},
        upsert=True,
    )


async def unset_user_fields(user_id: int, fields: List[str]):
    update = {"$unset": {f: "" for f in fields}}
    await users_coll.update_one({"_id": user_id}, update)


async def is_premium(user_id: int) -> bool:
    doc = await get_user_doc(user_id)
    exp = doc.get("premium_until")
    if not exp:
        return False
    if isinstance(exp, str):
        try:
            exp = datetime.fromisoformat(exp)
        except Exception:
            return False
    if not isinstance(exp, datetime):
        return False
    return datetime.utcnow() < exp


async def log_to_channel(text: str):
    """Sabhi important actions ko logs channel me bhejo."""
    try:
        await bot.send_message(LOGS_CHANNEL_ID, text)
    except Exception as e:
        # Render logs me error print karo
        print(f"[LOG ERROR] Can't send to logs channel: {e}")


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
    True => user joined (ya check nahi ho paaya, tab bhi allow).
    False => user ko join karne ke liye bolo.
    """
    if not FORCE_SUB_CHANNEL:
        return True

    user_id = msg.from_user.id
    try:
        try:
            member = await bot.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        except (ChannelPrivate, ChatAdminRequired, ChatWriteForbidden, ChatIdInvalid, PeerIdInvalid) as e:
            # Bot ko channel ka access hi nahi hai -> force-sub effectively disabled
            await log_to_channel(f"Force-sub access error for {user_id}: {e}")
            return True

        status = getattr(member, "status", "").lower()
        if status in ("kicked", "banned", "left"):
            raise UserNotParticipant

        # Member hai
        return True

    except UserNotParticipant:
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

    except Exception as e:
        # Koi unknown error aaya, user ko block nahi karenge
        await log_to_channel(f"Force-sub unknown error for {user_id}: {e}")
        return True

  # ===================== main.py (PART 2/3) =====================

# ---------- /start ----------
@bot.on_message(filters.command("start") & filters.private)
async def cmd_start(client: Client, msg: Message):
    user = msg.from_user
    await get_user_doc(user.id)  # ensure doc exists

    intro = (
        "*SERENA – Recovery Bot*\n\n"
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
        "*SERENA – Help*\n\n"
        "/start - Welcome message\n"
        "/help - Ye madad wala message\n"
        "/login - Login menu (Session / Phone+OTP / QR Code)\n"
        "/logout - Apne account ka session logout karna\n"
        "/batch - Kisi channel/chat ke message link se batch files nikaalo\n"
        "/status - Aapka login/premium/status dekhna\n"
        "/plan - Aapka plan, stats, history, remaining premium time\n"
        "/settings - Set Chat ID, text replace settings\n"
        "/cancel - Login ya batch jaise ongoing kaam cancel karna\n\n"
        "Login Methods:\n"
        "1) Session String: Pyrogram/Telethon session ko paste karke.\n"
        "2) Phone + OTP: 10-digit number + OTP (4 2 1 5 jaise) – "
        "Telegram kabhi-kabhi shared code block kar deta hai.\n"
        "3) QR Code Login: Recommended.\n\n"
        "Owner-only:\n"
        "/addpremium user_id days - Premium add karein (e.g. /addpremium 123456789 12)\n"
        "/remove user_id - Premium hata dein\n\n"
        "Note:\n"
        "- Login ke liye India number (10 digit, +91 auto add) use hota hai.\n"
        "- Saare logs (actions + files) logs channel me bhi jayenge."
    )
    await msg.reply_text(text)
    await log_to_channel(f"/help by {msg.from_user.id}")


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
        "*SERENA – Status*\n\n"
        f"👤 User ID: `{user_id}`\n"
        f"🔐 Logged in (user session): {'YES' if is_logged_in else 'NO'}\n"
        f"💎 Premium: {prem_text}\n"
        f"📡 Set Chat ID: `{set_chat}`\n"
        f"✏️ Replace 'Serena'→'Kumari': {'ON' if replace_flag else 'OFF'}\n"
        f"📦 Batch running: {'YES' if running_batch else 'NO'}"
    )
    await msg.reply_text(text)
    await log_to_channel(f"/status by {user_id}")


# ---------- /plan ----------
@bot.on_message(filters.command("plan") & filters.private)
async def cmd_plan(client: Client, msg: Message):
    user = msg.from_user
    user_id = user.id
    doc = await get_user_doc(user_id)

    phone = doc.get("phone") or "Not set"
    masked_phone = phone
    if isinstance(phone, str) and phone.startswith("+91") and len(phone) >= 10:
        masked_phone = "+91******" + phone[-4:]

    created_at = doc.get("created_at")
    if isinstance(created_at, str):
        try:
            created_at = datetime.fromisoformat(created_at)
        except Exception:
            created_at = None

    last_seen = doc.get("last_seen")
    if isinstance(last_seen, str):
        try:
            last_seen = datetime.fromisoformat(last_seen)
        except Exception:
            last_seen = None

    prem_until = doc.get("premium_until")
    prem_status = "Not premium"
    prem_remaining = "0s"
    if prem_until:
        if isinstance(prem_until, str):
            try:
                prem_until = datetime.fromisoformat(prem_until)
            except Exception:
                prem_until = None
        if isinstance(prem_until, datetime):
            now = datetime.utcnow()
            if prem_until > now:
                prem_status = "Premium active"
                prem_remaining = format_timedelta(prem_until - now)
            else:
                prem_status = "Premium expired"
                prem_remaining = "0s"

    stats = doc.get("stats") or {}
    batches_run = stats.get("batches_run", 0)
    msgs_downloaded = stats.get("messages_downloaded", 0)
    media_downloaded = stats.get("media_downloaded", 0)

    history = doc.get("history") or []
    last_tasks = list(reversed(history[-5:]))

    lines = []
    for idx, h in enumerate(last_tasks, start=1):
        status = h.get("status", "unknown")
        req = h.get("requested_count", 0)
        dl = h.get("downloaded", 0)
        start_time = h.get("start_time")
        if isinstance(start_time, str):
            try:
                start_time = datetime.fromisoformat(start_time)
            except Exception:
                start_time = None
        start_str = (
            start_time.strftime("%Y-%m-%d %H:%M:%S")
            if isinstance(start_time, datetime)
            else "N/A"
        )
        link = h.get("link", "")
        short_link = link
        if len(short_link) > 60:
            short_link = short_link[:57] + "..."

        lines.append(
            f"{idx}. `{status}` | {dl}/{req} msgs | {start_str}\n"
            f"   Link: `{short_link}`"
        )

    active_state = batch_states.get(user_id)
    active_info = "No"
    if user_id in batch_tasks and active_state and active_state.get("step") == "running":
        active_info = f"Yes (link: {active_state.get('link')}, count unknown)"

    text = "*SERENA – User Plan / History*\n\n"
    text += f"👤 User: `{user_id}`\n"
    if user.username:
        text += f"🔗 Username: @{user.username}\n"
    text += f"📞 Phone: `{masked_phone}`\n"
    if created_at:
        text += f"📅 First seen: `{created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC`\n"
    if last_seen:
        text += f"🕒 Last seen: `{last_seen.strftime('%Y-%m-%d %H:%M:%S')} UTC`\n"
    text += f"💎 Plan: {prem_status}\n"
    text += f"⏳ Premium remaining: `{prem_remaining}`\n\n"

    text += "📊 *Overall Stats:*\n"
    text += f"- Total batches run: `{batches_run}`\n"
    text += f"- Total messages downloaded: `{msgs_downloaded}`\n"
    text += f"- Total media files downloaded: `{media_downloaded}`\n"
    text += f"- Active batch: `{active_info}`\n\n"

    if lines:
        text += "🕘 *Last Tasks (max 5):*\n" + "\n".join(lines)
    else:
        text += "🕘 Abhi tak koi task history nahi mili."

    await msg.reply_text(text)
    await log_to_channel(f"/plan by {user_id}")


# ---------- /cancel ----------
@bot.on_message(filters.command("cancel") & filters.private)
async def cmd_cancel(client: Client, msg: Message):
    user_id = msg.from_user.id
    cancelled_any = False

    # Cancel login (phone/session)
    if login_steps.get(user_id):
        login_steps.pop(user_id, None)
        data = pending_logins.pop(user_id, None)
        if data and "client" in data:
            try:
                await data["client"].disconnect()
            except Exception:
                pass
        cancelled_any = True

    # Cancel QR login
    qr_task = login_qr_tasks.pop(user_id, None)
    if qr_task and not qr_task.done():
        qr_task.cancel()
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


# ---------- /logout ----------
@bot.on_message(filters.command("logout") & filters.private)
async def cmd_logout(client: Client, msg: Message):
    user_id = msg.from_user.id

    # Cancel login flows + batch
    if login_steps.get(user_id):
        login_steps.pop(user_id, None)
        data = pending_logins.pop(user_id, None)
        if data and "client" in data:
            try:
                await data["client"].disconnect()
            except Exception:
                pass

    qr_task = login_qr_tasks.pop(user_id, None)
    if qr_task and not qr_task.done():
        qr_task.cancel()

    task = batch_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()
    batch_states.pop(user_id, None)
    settings_states.pop(user_id, None)

    # Remove stored session & phone
    await unset_user_fields(user_id, ["session_string", "phone"])

    await msg.reply_text(
        "Aap successfully logout ho gaye.\n"
        "Ab dubara login karne ke liye /login use karein."
    )
    await log_to_channel(f"User {user_id} logged out.")


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


# ---------- /login (menu with 3 methods) ----------
@bot.on_message(filters.command("login") & filters.private)
async def cmd_login(client: Client, msg: Message):
    user_id = msg.from_user.id

    if not await require_premium(msg):
        return
    if not await check_force_sub_message(msg):
        return

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("Login Through Session", callback_data="login_session")],
            [InlineKeyboardButton("Login Through Phone + OTP", callback_data="login_phone")],
            [InlineKeyboardButton("QR Code Login", callback_data="login_qr")],
        ]
    )

    text = (
        "*SERENA – Login Menu*\n\n"
        "Koi ek method choose karein:\n\n"
        "1️⃣ Session String – Pyrogram/Telethon session paste karke.\n"
        "2️⃣ Phone + OTP – 10-digit number + OTP (e.g. `4 2 1 5`).\n"
        "   Note: Agar aap OTP kisi bot/chat me share karte ho, Telegram us code ko block kar sakta hai.\n"
        "3️⃣ QR Code Login – Recommended & safe.\n"
    )

    await msg.reply_text(text, reply_markup=kb)
    await log_to_channel(f"/login menu by {user_id}")


# ---------- CALLBACK QUERIES ----------
@bot.on_callback_query()
async def on_callback(client: Client, cq: CallbackQuery):
    data = cq.data
    user_id = cq.from_user.id

    # Force-sub re-check
    if data == "check_fsub":
        if not FORCE_SUB_CHANNEL:
            await cq.answer("Force-sub disabled hai, aap bot use kar sakte hain.", show_alert=True)
            return

        try:
            try:
                member = await client.get_chat_member(FORCE_SUB_CHANNEL, user_id)
            except (ChannelPrivate, ChatAdminRequired, ChatWriteForbidden, ChatIdInvalid, PeerIdInvalid):
                await cq.answer(
                    "Bot ko updates channel me add nahi kiya gaya ya channel private hai.\n"
                    "Owner ko bolo bot ko channel me add kare.",
                    show_alert=True,
                )
                return

            status = getattr(member, "status", "").lower()
            if status in ("kicked", "banned", "left"):
                await cq.answer("Abhi tak join nahi kiya.", show_alert=True)
            else:
                await cq.answer(
                    "Join verify ho gaya! Ab aap commands dubara run kar sakte hain.",
                    show_alert=True,
                )
                try:
                    await cq.message.edit_text("Subscription verified. Ab command dobara bhejiye.")
                except Exception:
                    pass

        except Exception as e:
            await cq.answer(
                "Channel check me error aa raha hai. Owner se contact kare.",
                show_alert=True,
            )
            await log_to_channel(f"Force-sub callback error for {user_id}: {e}")
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

    # ---------- Login method callbacks ----------
    if data == "login_session":
        # Purani states clear
        login_steps[user_id] = "session_wait"
        pending_logins.pop(user_id, None)
        qr_task = login_qr_tasks.pop(user_id, None)
        if qr_task and not qr_task.done():
            qr_task.cancel()

        await cq.message.reply_text(
            "Apna Pyrogram/Telethon session string yahan paste karein.\n"
            "Isse aapka user session direct use hoga.\n\n"
            "Note: Ye sirf tab use karein jab aapko pata ho session string kya hota hai."
        )
        await cq.answer("Session login selected.")
        return

    if data == "login_phone":
        login_steps[user_id] = "phone_wait_number"
        pending_logins.pop(user_id, None)
        qr_task = login_qr_tasks.pop(user_id, None)
        if qr_task and not qr_task.done():
            qr_task.cancel()

        await cq.message.reply_text(
            "Apna 10 digit Indian mobile number bhejiye (binā +91).\n"
            "Example: `9876543210`"
        )
        await cq.answer("Phone + OTP login selected.")
        return

    if data == "login_qr":
        # Do not start multiple QR tasks
        if user_id in login_qr_tasks and not login_qr_tasks[user_id].done():
            await cq.answer("QR login already running. /cancel bhej kar phir try karein.", show_alert=True)
            return

        # Purani login states clear
        login_steps.pop(user_id, None)
        pending_logins.pop(user_id, None)

        await cq.answer("QR login start ho raha hai...", show_alert=False)
        await cq.message.reply_text(
            "Ab QR login start ho raha hai.\n"
            "Aapko QR image milega, use Telegram app se scan karein."
        )

        # start_qr_login function PART 3 me defined hai
        task = asyncio.create_task(start_qr_login(user_id, cq.message.chat.id))
        login_qr_tasks[user_id] = task
        return

  # ===================== main.py (PART 3/3) =====================

# ---------- LOGIN HANDLERS (Session / Phone+OTP / QR) ----------

async def handle_session_login(msg: Message):
    user_id = msg.from_user.id
    session_str = (msg.text or "").strip()

    if not session_str:
        await msg.reply_text("Session string khali hai. Dubara paste karein.")
        return

    user_client = Client(
        name=f"user_session_{user_id}",
        api_id=API_ID,
        api_hash=API_HASH,
        session_string=session_str,
        in_memory=True,
    )

    try:
        await user_client.connect()
        await user_client.get_me()  # simple check

        new_session = await user_client.export_session_string()
        await set_user_field(user_id, "session_string", new_session)
        await set_user_field(user_id, "phone", None)

        await msg.reply_text(
            "Session login successful! Ab aap /batch aur /settings use kar sakte hain.\n"
            "Brand: SERENA"
        )
        await log_to_channel(f"User {user_id} login via SESSION string.")
        login_steps.pop(user_id, None)
    except Exception as e:
        await msg.reply_text(f"Session invalid ya login error: {e}")
    finally:
        try:
            await user_client.disconnect()
        except Exception:
            pass


async def handle_phone_number(msg: Message):
    user_id = msg.from_user.id
    text = (msg.text or "").strip()

    if not re.fullmatch(r"\d{10}", text):
        await msg.reply_text("Please valid 10-digit mobile number bhejiye (sirf digits).")
        return

    phone = "+91" + text
    user_client = Client(
        name=f"login_phone_{user_id}",
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
        login_steps[user_id] = "phone_wait_code"
        await msg.reply_text(
            "Telegram ne aapke number par OTP bheja hai.\n"
            "Wohi OTP (e.g. `4 2 1 5`) yahan bhejiye.\n\n"
            "Note: Agar aap ye code kisi bot/chat me share karenge to "
            "Telegram is code ko block kar sakta hai."
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


async def handle_phone_code(msg: Message):
    user_id = msg.from_user.id
    text = (msg.text or "").strip()
    code = text.replace(" ", "")  # "4 2 1 5" -> "4215"

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
    except PhoneCodeExpired:
        await msg.reply_text(
            "Ye OTP Telegram ne expire/block kar diya hai.\n"
            "Aksar aisa tab hota hai jab aap OTP kisi bot ya chat me share kar dete ho.\n"
            "Recommended: QR Code login ya Session login method use karein (/login)."
        )
        try:
            await user_client.disconnect()
        except Exception:
            pass
        pending_logins.pop(user_id, None)
        login_steps.pop(user_id, None)
        return
    except SessionPasswordNeeded:
        await msg.reply_text(
            "Aapke account par 2-step verification password laga hua hai.\n"
            "Ye bot password handle nahi karta. 2FA disable karke phir try karein "
            "ya QR/Session login use karein."
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

    await msg.reply_text(
        "Login (phone + OTP) successful! Ab aap /batch aur /settings use kar sakte hain.\n"
        "Future me OTP kisi ke sath share mat karein."
    )
    await log_to_channel(f"User {user_id} login success via PHONE+OTP.")

    try:
        await user_client.disconnect()
    except Exception:
        pass

    pending_logins.pop(user_id, None)
    login_steps.pop(user_id, None)


async def start_qr_login(user_id: int, chat_id: int):
    user_client = Client(
        name=f"user_qr_{user_id}",
        api_id=API_ID,
        api_hash=API_HASH,
        in_memory=True,
    )

    try:
        await user_client.connect()

        while True:
            qr_login = await user_client.qr_login(max_age=120)

            # QR image generate karein
            img = qrcode.make(qr_login.url)
            bio = io.BytesIO()
            img.save(bio, format="PNG")
            bio.seek(0)

            qr_msg = await bot.send_photo(
                chat_id=chat_id,
                photo=bio,
                caption=(
                    "Is QR ko apne official Telegram app se scan karein:\n\n"
                    "Telegram app → Settings → Devices → Link Desktop Device\n\n"
                    "Ye QR ~120 seconds me expire ho jayega,\n"
                    "agar kaam na kare to /login se QR login dobara choose karein."
                ),
            )

            try:
                await qr_login.wait()
                # Yaha aa gaye matlab scan + approve ho chuka
                break

            except QrCodeExpired:
                try:
                    await qr_msg.edit_caption(
                        "Ye QR expire ho gaya hai. Naya QR generate kar raha hoon..."
                    )
                except Exception:
                    pass
                continue

            except asyncio.CancelledError:
                # /cancel ya /logout ne cancel kiya
                try:
                    await bot.send_message(
                        chat_id, "QR login cancel kar diya gaya."
                    )
                except Exception:
                    pass
                raise

            except Exception as e:
                await bot.send_message(chat_id, f"QR login me error: {e}")
                return

        # Yaha user_client login ho chuka hai
        try:
            session_string = await user_client.export_session_string()
        except Exception as e:
            await bot.send_message(chat_id, f"Session export me error: {e}")
            return

        await set_user_field(user_id, "session_string", session_string)
        await set_user_field(user_id, "phone", None)

        await bot.send_message(
            chat_id,
            "QR login successful! Ab aap /batch aur /settings use kar sakte hain.\n"
            "Brand: SERENA",
        )
        await log_to_channel(f"User {user_id} login success via QR.")

    except asyncio.CancelledError:
        # Cancelled in outer layer
        try:
            await bot.send_message(chat_id, "QR login cancel kar diya gaya.")
        except Exception:
            pass
        raise
    except Exception as e:
        await bot.send_message(chat_id, f"QR login me error: {e}")
    finally:
        try:
            await user_client.disconnect()
        except Exception:
            pass
        login_qr_tasks.pop(user_id, None)


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
        parse_telegram_link(text)
    except Exception:
        await msg.reply_text("Ye valid Telegram message link nahi lag raha. Sahi link bhejiye.")
        return

    batch_states[user_id] = {"step": "wait_count", "link": text}
    await msg.reply_text(
        f"Kitne messages nikalne hain? (Maximum {MAX_BATCH_LIMIT})\n"
        "Sirf number bhejiye, example: `50`"
    )


async def add_history_entry(user_id: int, task_id: str, link: str, count: int):
    entry = {
        "task_id": task_id,
        "link": link,
        "requested_count": count,
        "start_time": datetime.utcnow(),
        "status": "running",
        "downloaded": 0,
        "errors": 0,
    }
    await users_coll.update_one(
        {"_id": user_id},
        {"$push": {"history": {"$each": [entry], "$slice": -10}}},
        upsert=True,
    )


async def finalize_batch_record(
    user_id: int,
    task_id: str,
    status: str,
    downloaded_count: int,
    error_count: int,
    media_count: int,
):
    await users_coll.update_one(
        {"_id": user_id, "history.task_id": task_id},
        {
            "$set": {
                "history.$.status": status,
                "history.$.end_time": datetime.utcnow(),
                "history.$.downloaded": downloaded_count,
                "history.$.errors": error_count,
            }
        },
    )
    await users_coll.update_one(
        {"_id": user_id},
        {
            "$inc": {
                "stats.batches_run": 1,
                "stats.messages_downloaded": downloaded_count,
                "stats.media_downloaded": media_count,
            }
        },
        upsert=True,
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

    task_id = datetime.utcnow().isoformat()
    batch_states[user_id] = {"step": "running", "link": link, "task_id": task_id}

    await add_history_entry(user_id, task_id, link, count)

    task = asyncio.create_task(batch_worker(user_id, link, count, task_id))
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


# ---------- MAIN TEXT ROUTER ----------
@bot.on_message(
    filters.private
    & ~filters.command(
        [
            "start",
            "help",
            "status",
            "plan",
            "cancel",
            "logout",
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

    # Login flows
    if login_steps.get(user_id) == "session_wait":
        await handle_session_login(msg)
        return
    if login_steps.get(user_id) == "phone_wait_number":
        await handle_phone_number(msg)
        return
    if login_steps.get(user_id) == "phone_wait_code":
        await handle_phone_code(msg)
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

    # No state: silent ignore


# ---------- PROGRESS TEXT HELPER ----------
async def update_progress_message(
    progress_msg: Message,
    file_name: str,
    current: int,
    total: int,
    start_time: float,
    last_update_holder: Dict[str, float],
):
    now = time.time()
    last = last_update_holder.get("time", 0)
    if now - last < 1:
        return
    last_update_holder["time"] = now

    if total == 0:
        percent = 0.0
    else:
        percent = current * 100 / total

    elapsed = now - start_time
    speed = current / elapsed if elapsed > 0 else 0
    remaining = (total - current) / speed if speed > 0 else 0

    filled = int(percent // 5)  # 20 chars bar
    filled = max(0, min(20, filled))
    bar = "●" * filled + "○" * (20 - filled)
    bar = "[" + bar + "]"

    text = (
        "Downloading\n\n"
        f"{file_name}\n"
        "to my server\n"
        f"{bar}\n"
        f"◌Progress😉:〘 {percent:.2f}% 〙\n"
        f"Done: 〘{humanbytes(current)} of {humanbytes(total)}〙\n"
        f"◌Speed🚀:〘 {humanbytes(speed)}/s  〙\n"
        f"◌Time Left⏳:〘 {time_formatter(remaining)} 〙"
    )

    try:
        await bot.edit_message_text(
            chat_id=progress_msg.chat.id,
            message_id=progress_msg.id,
            text=text,
        )
    except Exception:
        # Ignore edit failures
        pass


# ---------- BATCH WORKER ----------
async def batch_worker(user_id: int, link: str, count: int, task_id: str):
    temp_dir = tempfile.mkdtemp(prefix=f"serena_{user_id}_")
    downloaded_count = 0
    error_count = 0
    media_count = 0
    status = "completed"

    try:
        doc = await get_user_doc(user_id)
        session_string = doc.get("session_string")
        if not session_string:
            await bot.send_message(
                user_id, "Session nahi mila. Pehle /login karke dobara try karein."
            )
            status = "error"
            return

        set_chat_id = doc.get("set_chat_id")
        replace_flag = bool(doc.get("replace_serena", False))

        try:
            chat_identifier, start_msg_id = parse_telegram_link(link)
        except Exception as e:
            await bot.send_message(
                user_id, f"Link parse karte waqt error: {e}\n/batch se dobara try karein."
            )
            status = "error"
            return

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
                    error_count += 1
                    continue
            except Exception:
                error_count += 1
                continue

            if not src_msg:
                error_count += 1
                continue

            text = src_msg.text or src_msg.caption or ""
            text = replace_serena_text(text, replace_flag)

            sent: Optional[Message] = None

            if src_msg.media:
                # MEDIA DOWNLOAD WITH PROGRESS
                file_name = None
                if src_msg.document and src_msg.document.file_name:
                    file_name = src_msg.document.file_name
                elif src_msg.video and src_msg.video.file_name:
                    file_name = src_msg.video.file_name
                elif src_msg.audio and src_msg.audio.file_name:
                    file_name = src_msg.audio.file_name
                else:
                    file_name = "Media file"

                progress_msg = await bot.send_message(
                    user_id, f"Downloading\n\n{file_name}\nto my server\n[○○○○○○○○○○○○○○○○○○○○]"
                )

                start_time = time.time()
                last_holder = {"time": 0.0}

                def progress(current: int, total: int):
                    loop = asyncio.get_event_loop()
                    loop.create_task(
                        update_progress_message(
                            progress_msg,
                            file_name,
                            current,
                            total,
                            start_time,
                            last_holder,
                        )
                    )

                try:
                    file_path = await user_app.download_media(
                        src_msg, file_name=temp_dir, progress=progress
                    )
                except Exception:
                    error_count += 1
                    continue

                if not file_path:
                    error_count += 1
                    continue

                media_count += 1

                # Final progress 100% (best-effort)
                try:
                    size = os.path.getsize(file_path)
                    await update_progress_message(
                        progress_msg,
                        file_name,
                        size,
                        size,
                        start_time,
                        {"time": 0.0},
                    )
                except Exception:
                    pass

                try:
                    # User ko bhejo
                    try:
                        sent = await bot.send_document(
                            chat_id=user_id,
                            document=file_path,
                            caption=text or None,
                        )
                        downloaded_count += 1
                    except RPCError:
                        sent = None
                        error_count += 1

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
                    downloaded_count += 1
                except RPCError:
                    sent = None
                    error_count += 1

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
        await log_to_channel(
            f"Batch completed for user {user_id} | requested={count} | downloaded={downloaded_count} | errors={error_count}"
        )

    except asyncio.CancelledError:
        status = "cancelled"
        try:
            await bot.send_message(user_id, "Batch cancel kar diya gaya.")
        except Exception:
                  pass
    except Exception as e:
        status = "error"
        try:
            await bot.send_message(user_id, f"Batch me error aaya: {e}")
        except Exception:
            pass
        await log_to_channel(f"Batch error for user {user_id}: {e}")
    finally:
        await finalize_batch_record(
            user_id, task_id, status, downloaded_count, error_count, media_count
        )
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
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ---------- MAIN ----------
if __name__ == "__main__":
    # Flask ko alag thread me chalao (Render ko open port chahiye)
    threading.Thread(target=run_flask, daemon=True).start()

    print("Starting SERENA bot...")
    bot.run()

            
