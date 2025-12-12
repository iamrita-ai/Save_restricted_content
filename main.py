# ===================== main.py (PART 1/4) =====================
import os
import re
import io
import time
import qrcode
import asyncio
import threading
import tempfile
import shutil
from datetime import datetime, timedelta, timezone
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
)

# QrCodeExpired kuch versions me nahi hota, isliye safe import:
try:
    from pyrogram.errors import QrCodeExpired
except ImportError:
    class QrCodeExpired(Exception):
        """Fallback dummy error if pyrogram.errors.QrCodeExpired not available."""
        pass

from motor.motor_asyncio import AsyncIOMotorClient

# ---------- ENVIRONMENT ----------
API_ID = int(os.environ["API_ID"])
API_HASH = os.environ["API_HASH"]
BOT_TOKEN = os.environ["BOT_TOKEN"]
MONGO_URI = os.environ["MONGO_URI"]

START_IMAGE_URL = os.environ.get("START_IMAGE_URL")  # optional /start image

# ---------- CONSTANTS ----------
LOGS_CHANNEL_ID = -1003286415377
FORCE_SUB_CHANNEL = "serenaunzipbot"
OWNER_IDS = {1598576202, 6518065496}

MAX_BATCH_LIMIT = 1000       # premium/owner
FREE_BATCH_LIMIT = 50        # free users
SLEEP_SECONDS = 12

# ---------- MONGO ----------
mongo_client = AsyncIOMotorClient(MONGO_URI)
db = mongo_client["serena_bot"]
users_coll = db["users"]

# ---------- GLOBAL STATES ----------
pending_logins: Dict[int, Dict[str, Any]] = {}   # phone+otp login temp
login_steps: Dict[int, str] = {}                 # 'session_wait' / 'phone_wait_number' / 'phone_wait_code'
login_qr_tasks: Dict[int, asyncio.Task] = {}     # QR login tasks

batch_states: Dict[int, Dict[str, Any]] = {}     # 'step', 'link', 'task_id'
batch_tasks: Dict[int, asyncio.Task] = {}

settings_states: Dict[int, str] = {}             # 'await_chat_id'

# ---------- BOT ----------
bot = Client(
    "serena_main_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    in_memory=True,
)


# ---------- HELPER FUNCTIONS ----------

def is_owner(user_id: int) -> bool:
    return user_id in OWNER_IDS


def humanbytes(num: float) -> str:
    if num is None:
        return "0 B"
    num = float(num)
    for unit in ["B", "KB", "MB", "GB", "TB"]:
        if num < 1024 or unit == "TB":
            return f"{num:.2f} {unit}"
        num /= 1024.0
    return f"{num:.2f} TB"


def time_formatter(seconds: float) -> str:
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
    return time_formatter(int(td.total_seconds()))


def parse_telegram_link(link: str) -> Tuple[Any, int]:
    """
    t.me link -> (chat_identifier, message_id)
    - Public: https://t.me/username/123  => ("username", 123)
    - Private: https://t.me/c/123456789/123 => (-100123456789, 123)
    """
    link = link.strip()
    if not link.startswith("http"):
        link = "https://" + link.lstrip("/")

    m = re.search(r"t\.me/c/(\d+)/(\d+)", link)
    if m:
        internal_id = int(m.group(1))
        msg_id = int(m.group(2))
        chat_id = int("-100" + str(internal_id))
        return chat_id, msg_id

    m = re.search(r"t\.me/([A-Za-z0-9_]+)/(\d+)", link)
    if m:
        username = m.group(1)
        msg_id = int(m.group(2))
        return username, msg_id

    raise ValueError("Invalid Telegram message link")


def replace_serena_text(text: Optional[str], enabled: bool) -> Optional[str]:
    if not text or not enabled:
        return text
    return text.replace("Serena", "Kumari").replace("SERENA", "KUMARI")


async def get_user_doc(user_id: int) -> Dict[str, Any]:
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
    await users_coll.update_one({"_id": user_id}, {"$set": {field: value}}, upsert=True)


async def unset_user_fields(user_id: int, fields: List[str]):
    await users_coll.update_one(
        {"_id": user_id},
        {"$unset": {f: "" for f in fields}},
    )


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


async def get_max_batch_limit(user_id: int) -> int:
    if is_owner(user_id):
        return MAX_BATCH_LIMIT
    if await is_premium(user_id):
        return MAX_BATCH_LIMIT
    return FREE_BATCH_LIMIT


async def log_to_channel(text: str):
    try:
        await bot.send_message(LOGS_CHANNEL_ID, text)
    except Exception as e:
        print(f"[LOG ERROR] {e}")


async def require_premium(msg: Message) -> bool:
    user_id = msg.from_user.id
    if is_owner(user_id):
        return True
    if await is_premium(user_id):
        return True
    await msg.reply_text(
        "💎 Premium Required\n\n"
        "Ye SERENA bot sirf premium users ke liye hai.\n"
        "Access chahiye to owner se pyaar se baat karein: @technicalserena 💕"
    )
    return False


async def check_force_sub_message(msg: Message) -> bool:
    if not FORCE_SUB_CHANNEL:
        return True

    user_id = msg.from_user.id
    try:
        try:
            member = await bot.get_chat_member(FORCE_SUB_CHANNEL, user_id)
        except (ChannelPrivate, ChatAdminRequired, ChatWriteForbidden, ChatIdInvalid, PeerIdInvalid) as e:
            await log_to_channel(f"Force-sub access error for {user_id}: {e}")
            return True

        status = getattr(member, "status", "").lower()
        if status in ("kicked", "banned", "left"):
            raise UserNotParticipant

        return True

    except UserNotParticipant:
        kb = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("✨ Join Updates", url="https://t.me/serenaunzipbot"),
                    InlineKeyboardButton("✅ Check", callback_data="check_fsub"),
                ]
            ]
        )
        await msg.reply_text(
            "💕 Pehle humari updates channel se mil lijiye.\n"
            "Join karne ke baad 'Check' dabayen, fir hum aage badhenge. 💌",
            reply_markup=kb,
        )
        return False
    except Exception as e:
        await log_to_channel(f"Force-sub unknown error for {user_id}: {e}")
        return True

  # ===================== main.py (PART 2/4) =====================

# ---------- /start ----------
@bot.on_message(filters.command("start") & filters.private)
async def cmd_start(client: Client, msg: Message):
    user = msg.from_user
    await get_user_doc(user.id)

    intro = (
        "✨ SERENA – Your Personal Recovery Angel ✨\n\n"
        "Main SERENA hoon, tumhari lost memories wapas lane ke liye bani ek pyaari si bot. 💖\n\n"
        "🔐 Apne Telegram account se login karo,\n"
        "📂 apni important files, photos, videos wapas pao,\n"
        "📦 kisi bhi private / public channel & group se safely sab kuch recover karo.\n\n"
        "Bas yaad rakho…\n"
        "👉 Ye magic sirf tumhare hi accounts/channels ke liye use karo.\n"
        "Brand Name: SERENA 💘"
    )

    kb = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🌸 Join Updates", url="https://t.me/serenaunzipbot"),
                InlineKeyboardButton("💌 Contact Owner", url="https://t.me/technicalserena"),
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
        "🌹 SERENA – Help Menu 🌹\n\n"
        "Commands:\n"
        "• /start – Romantic welcome & intro 💌\n"
        "• /help – Ye help menu\n"
        "• /login – Login menu (Session / Phone+OTP / QR Code)\n"
        "• /logout – Session logout\n"
        "• /batch – Channel/chat link se batch me messages & media nikaalo\n"
        "• /status – Login, premium aur current status ❤️\n"
        "• /plan – History, stats, premium remaining time\n"
        "• /settings – Set Chat ID, 'Serena' → 'Kumari' rename option (premium)\n"
        "• /cancel – Ongoing task cancel (login/batch etc.)\n"
        "• /clear – (Owner only) Mongo DB user data clear kare\n\n"
        "Login Methods:\n"
        "1) Session String – Pyrogram/Telethon session paste\n"
        "2) Phone + OTP – 10-digit number + OTP (e.g. 4 2 1 5)\n"
        "3) QR Code – Recommended & safe\n\n"
        "Limits:\n"
        f"• Free: max {FREE_BATCH_LIMIT} messages per batch\n"
        f"• Premium/Owner: max {MAX_BATCH_LIMIT} messages per batch\n\n"
        "Owner-only:\n"
        "• /addpremium user_id days\n"
        "• /remove user_id\n"
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
    prem_text = "❌ NO"
    if prem:
        exp = doc.get("premium_until")
        if isinstance(exp, str):
            try:
                exp = datetime.fromisoformat(exp)
            except Exception:
                pass
        if isinstance(exp, datetime):
            prem_text = f"✅ YES (till {exp.strftime('%Y-%m-%d %H:%M:%S')} UTC)"
        else:
            prem_text = "✅ YES"

    set_chat = doc.get("set_chat_id")
    replace_flag = bool(doc.get("replace_serena", False))
    running_batch = user_id in batch_tasks

    text = (
        "💖 SERENA – Your Current Status 💖\n\n"
        f"👤 User ID: {user_id}\n"
        f"🔐 Logged in (user session): {'✅ YES' if is_logged_in else '❌ NO'}\n"
        f"💎 Premium: {prem_text}\n"
        f"📡 Set Chat ID: {set_chat}\n"
        f"✏️ Replace 'Serena' → 'Kumari': {'✅ ON' if replace_flag else '❌ OFF'}\n"
        f"📦 Batch running: {'🔥 YES' if running_batch else '❄️ NO'}"
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
                prem_status = "Premium active 💎"
                prem_remaining = format_timedelta(prem_until - now)
            else:
                prem_status = "Premium expired 💔"
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
        short_link = link if len(link) <= 60 else link[:57] + "..."

        lines.append(
            f"{idx}. {status} | {dl}/{req} msgs | {start_str}\n"
            f"   Link: {short_link}"
        )

    active_state = batch_states.get(user_id)
    active_info = "No"
    if user_id in batch_tasks and active_state and active_state.get("step") == "running":
        active_info = f"Yes (link: {active_state.get('link')})"

    text = "🌙 SERENA – Tumhara Love Plan & History 🌙\n\n"
    text += f"👤 User: {user_id}"
    if user.username:
        text += f" (@{user.username})"
    text += "\n"
    text += f"📞 Phone: {masked_phone}\n"
    if created_at:
        text += f"📅 First seen: {created_at.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
    if last_seen:
        text += f"🕒 Last seen: {last_seen.strftime('%Y-%m-%d %H:%M:%S')} UTC\n"
    text += f"💎 Plan: {prem_status}\n"
    text += f"⏳ Premium remaining: {prem_remaining}\n\n"

    text += "📊 Overall Stats:\n"
    text += f"• Total batches run: {batches_run}\n"
    text += f"• Total messages downloaded: {msgs_downloaded}\n"
    text += f"• Total media files downloaded: {media_downloaded}\n"
    text += f"• Active batch: {active_info}\n\n"

    if lines:
        text += "🕘 Last 5 Tasks:\n" + "\n".join(lines)
    else:
        text += "🕘 Abhi tak koi batch history nahi mili. Chalo kuch yaadein wapas laate hain. 💕"

    await msg.reply_text(text)
    await log_to_channel(f"/plan by {user_id}")


# ---------- /cancel ----------
@bot.on_message(filters.command("cancel") & filters.private)
async def cmd_cancel(client: Client, msg: Message):
    user_id = msg.from_user.id
    cancelled_any = False

    if login_steps.get(user_id):
        login_steps.pop(user_id, None)
        data = pending_logins.pop(user_id, None)
        if data and "client" in data:
            try:
                await data["client"].disconnect()
            except Exception:
                pass
        cancelled_any = True

    qr_task = login_qr_tasks.pop(user_id, None)
    if qr_task and not qr_task.done():
        qr_task.cancel()
        cancelled_any = True

    if settings_states.get(user_id):
        settings_states.pop(user_id, None)
        cancelled_any = True

    task = batch_tasks.pop(user_id, None)
    if task and not task.done():
        task.cancel()
        cancelled_any = True

    batch_states.pop(user_id, None)

    if cancelled_any:
        await msg.reply_text("❌ Jo kaam chal raha tha, maine pyaar se rok diya hai. 💞")
        await log_to_channel(f"/cancel used by {user_id}")
    else:
        await msg.reply_text("Abhi koi active task nahi chal raha hai jise cancel karu. 🌸")


# ---------- /logout ----------
@bot.on_message(filters.command("logout") & filters.private)
async def cmd_logout(client: Client, msg: Message):
    user_id = msg.from_user.id

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

    await unset_user_fields(user_id, ["session_string", "phone"])

    await msg.reply_text(
        "🔓 Aap successfully logout ho gaye.\n"
        "Jab mann kare, wapas aakar /login se phir humse jud sakte hain. 💖"
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
                InlineKeyboardButton("📡 Set Chat ID", callback_data="set_chat_id"),
                InlineKeyboardButton("🧹 Reset", callback_data="reset_settings"),
            ],
            [
                InlineKeyboardButton(
                    f"✏️ Replace 'Serena' → 'Kumari': {'ON ✅' if replace_flag else 'OFF ❌'}",
                    callback_data="toggle_replace",
                )
            ],
        ]
    )

    await msg.reply_text("⚙️ SERENA – Settings ⚙️", reply_markup=kb)


# ---------- /addpremium ----------
@bot.on_message(filters.command("addpremium") & filters.private)
async def cmd_addpremium(client: Client, msg: Message):
    user_id = msg.from_user.id
    if not is_owner(user_id):
        await msg.reply_text("👑 Sirf owner is command ka use kar sakta hai.")
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
        f"User {target_id} ko {days} din ke liye premium de diya gaya hai. 💎",
        quote=True,
    )
    await log_to_channel(
        f"Owner {user_id} added premium for {target_id} for {days} days (till {expires})."
    )


# ---------- /remove ----------
@bot.on_message(filters.command("remove") & filters.private)
async def cmd_remove_premium(client: Client, msg: Message):
    user_id = msg.from_user.id
    if not is_owner(user_id):
        await msg.reply_text("👑 Sirf owner is command ka use kar sakta hai.")
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
    await msg.reply_text(f"User {target_id} se premium hata diya gaya hai. 💔")
    await log_to_channel(f"Owner {user_id} removed premium for {target_id}")


# ---------- /clear (Mongo reset) ----------
@bot.on_message(filters.command("clear") & filters.private)
async def cmd_clear(client: Client, msg: Message):
    user_id = msg.from_user.id
    if not is_owner(user_id):
        await msg.reply_text("Ye command sirf owner ke liye hai. 👑")
        return

    await users_coll.drop()
    await msg.reply_text("MongoDB users data clear kar diya gaya hai. ⚠️")
    await log_to_channel(f"Owner {user_id} cleared MongoDB users collection.")


# ---------- /login (menu) ----------
@bot.on_message(filters.command("login") & filters.private)
async def cmd_login(client: Client, msg: Message):
    print(f"[DEBUG] /login from {msg.from_user.id}")
    user_id = msg.from_user.id

    # /login ab free + premium dono ke liye hai
    if not await check_force_sub_message(msg):
        return

    kb = InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("1️⃣ Session String Login", callback_data="login_session")],
            [InlineKeyboardButton("2️⃣ Phone + OTP Login", callback_data="login_phone")],
            [InlineKeyboardButton("3️⃣ QR Code Login", callback_data="login_qr")],
        ]
    )

    text = (
        "💘 SERENA – Login Menu 💘\n\n"
        "Apne hisaab se ek method choose karo:\n\n"
        "1) Session String – Pyrogram/Telethon session paste karo (advanced users).\n"
        "2) Phone + OTP – 10-digit number + OTP (e.g. 4 2 1 5).\n"
        "3) QR Code Login – Sabse safe & romantic method. 💞\n\n"
        "Note: Kisi bhi channel/group se clone karne ke liye sirf itna zaruri hai ki\n"
        "aapka account us channel/group me joined ho. Bot ko member/admin hone ki zarurat nahi. ✨"
    )

    await msg.reply_text(text, reply_markup=kb)
    await log_to_channel(f"/login menu by {user_id}")


# ---------- Callback Query Handler ----------
@bot.on_callback_query()
async def on_callback(client: Client, cq: CallbackQuery):
    data = cq.data
    user_id = cq.from_user.id

    # Force-sub re-check
    if data == "check_fsub":
        if not FORCE_SUB_CHANNEL:
            await cq.answer("Force-sub disabled hai, tum directly bot use kar sakte ho. 💕", show_alert=True)
            return

        try:
            try:
                member = await client.get_chat_member(FORCE_SUB_CHANNEL, user_id)
            except (ChannelPrivate, ChatAdminRequired, ChatWriteForbidden, ChatIdInvalid, PeerIdInvalid):
                await cq.answer(
                    "Bot ko updates channel me add nahi kiya gaya ya channel private hai.\n"
                    "Owner se bolo bot ko channel me pyaar se add kare. 💌",
                    show_alert=True,
                )
                return

            status = getattr(member, "status", "").lower()
            if status in ("kicked", "banned", "left"):
                await cq.answer("Abhi tak join nahi kiya, pehle join karlo jaan. 💔", show_alert=True)
            else:
                await cq.answer(
                    "Join verify ho gaya! Ab aaram se commands use kar sakte ho. 💖",
                    show_alert=True,
                )
                try:
                    await cq.message.edit_text("Subscription verified. Ab command dobara bhejiye. 🌸")
                except Exception:
                    pass

        except Exception as e:
            await cq.answer(
                "Channel check me error aa raha hai. Owner se contact karein. 💬",
                show_alert=True,
            )
            await log_to_channel(f"Force-sub callback error for {user_id}: {e}")
        return

    # Settings callbacks
    if data == "set_chat_id":
        settings_states[user_id] = "await_chat_id"
        await cq.message.reply_text(
            "📡 Jis chat/channel me files bhejni hain uska chat ID bhejiye.\n"
            "Example: -1001234567890",
            quote=True,
        )
        await cq.answer("Chat ID bhejiye meri jaan. 💕")
        return

    if data == "reset_settings":
        await unset_user_fields(user_id, ["set_chat_id", "replace_serena"])
        await cq.message.reply_text("🧹 Settings reset ho gayi hain. Naya start, nayi kahani. ✨")
        await cq.answer("Reset done. 💖")
        return

    if data == "toggle_replace":
        doc = await get_user_doc(user_id)
        current = bool(doc.get("replace_serena", False))
        new_val = not current
        await set_user_field(user_id, "replace_serena", new_val)
        await cq.message.reply_text(
            f"✏️ Replace 'Serena' → 'Kumari' ab: {'ON ✅' if new_val else 'OFF ❌'}"
        )
        await cq.answer("Updated. 🌸")
        return

    # Login callbacks
    if data == "login_session":
        login_steps[user_id] = "session_wait"
        pending_logins.pop(user_id, None)
        qr_task = login_qr_tasks.pop(user_id, None)
        if qr_task and not qr_task.done():
            qr_task.cancel()

        await cq.message.reply_text(
            "🔐 Apna Pyrogram/Telethon session string yahan paste karein.\n"
            "Isse aapka user session direct connect ho jayega.\n"
            "Ye option sirf tab use karein jab aapko session string ka concept pata ho."
        )
        await cq.answer("Session login selected. 💖")
        return

    if data == "login_phone":
        login_steps[user_id] = "phone_wait_number"
        pending_logins.pop(user_id, None)
        qr_task = login_qr_tasks.pop(user_id, None)
        if qr_task and not qr_task.done():
            qr_task.cancel()

        await cq.message.reply_text(
            "📲 Apna 10 digit Indian mobile number bhejiye (binā +91).\n"
            "Example: 9876543210"
        )
        await cq.answer("Phone + OTP login selected. 💕")
        return

    if data == "login_qr":
        if hasattr(Client, "qr_login"):
            if user_id in login_qr_tasks and not login_qr_tasks[user_id].done():
                await cq.answer("QR login already running. /cancel bhej kar phir try karein. 💫", show_alert=True)
                return

            login_steps.pop(user_id, None)
            pending_logins.pop(user_id, None)

            await cq.answer("QR login start ho raha hai... 💘", show_alert=False)
            await cq.message.reply_text(
                "📷 QR login start ho raha hai.\n"
                "Main tumhe ek QR image bhejungi, use Telegram app se scan karna:\n"
                "Settings → Devices → Link Desktop Device 💞"
            )

            task = asyncio.create_task(start_qr_login(user_id, cq.message.chat.id))
            login_qr_tasks[user_id] = task
        else:
            await cq.answer(
                "Is server ke Pyrogram version me QR login supported nahi hai. 😔\n"
                "Please Session ya Phone+OTP method use karein.",
                show_alert=True,
            )
        return

# ===================== main.py (PART 3/4) =====================

# ---------- LOGIN HANDLERS ----------

async def handle_session_login(msg: Message):
    user_id = msg.from_user.id
    session_str = (msg.text or "").strip()

    if not session_str:
        await msg.reply_text("Session string khali hai. Dubara pyaar se paste karo na. 💌")
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
        await user_client.get_me()

        new_session = await user_client.export_session_string()
        await set_user_field(user_id, "session_string", new_session)
        await set_user_field(user_id, "phone", None)

        await msg.reply_text(
            "✨ Session login successful!\n"
            "Ab hum milkar /batch aur /settings ke through tumhari yaadein wapas layenge.\n"
            "Brand: SERENA 💖"
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
        await msg.reply_text("Please valid 10-digit mobile number bhejiye (sirf digits). 💕")
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
            "Telegram ne aapke number par OTP bheja hai. 💌\n"
            "Wohi OTP (e.g. 4 2 1 5) yahan bhejiye.\n\n"
            "Dhyaan rahe: OTP kisi aur bot/chat me share karoge to Telegram code block kar sakta hai."
        )
    except PhoneNumberInvalid:
        await msg.reply_text("Ye phone number invalid hai. Thoda check karke dobara bhejo na. 💔")
        try:
            await user_client.disconnect()
        except Exception:
            pass
        pending_logins.pop(user_id, None)
        login_steps.pop(user_id, None)
    except FloodWait as e:
        await msg.reply_text(f"Telegram flood wait: {e.value} seconds. Thodi der baad try karein. ⏳")
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
    code = text.replace(" ", "")

    data = pending_logins.get(user_id)
    if not data:
        await msg.reply_text("Login session mil nahi raha. /login se dobara start karein, jaan. 💕")
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
        await msg.reply_text("OTP galat hai, sahi OTP bhejo na sweetheart. 💔")
        return
    except PhoneCodeExpired:
        await msg.reply_text(
            "Ye OTP Telegram ne expire/block kar diya hai. 😔\n"
            "Ye tab hota hai jab OTP share ho jata hai.\n"
            "Best: QR Code login ya Session login use karein (/login)."
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
            "Tumhare account par 2-step verification password laga hai. 🔐\n"
            "Ye bot password handle nahi karta.\n"
            "2FA disable karke ya QR/Session login use karke phir try karo. 💖"
        )
        try:
            await user_client.disconnect()
        except Exception:
            pass
        pending_logins.pop(user_id, None)
        login_steps.pop(user_id, None)
        return
    except FloodWait as e:
        await msg.reply_text(f"Flood wait: {e.value} seconds. Thodi der baad try karein. ⏳")
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
        "💫 Phone + OTP login successful!\n"
        "Ab hum /batch ke through tumhari files ko pyaar se wapas la sakte hain. 💖"
    )
    await log_to_channel(f"User {user_id} login success via PHONE+OTP.")

    try:
        await user_client.disconnect()
    except Exception:
        pass

    pending_logins.pop(user_id, None)
    login_steps.pop(user_id, None)


async def start_qr_login(user_id: int, chat_id: int):
    if not hasattr(Client, "qr_login"):
        await bot.send_message(
            chat_id,
            "Is server ke Pyrogram version me QR login supported nahi hai. 😔\n"
            "Please Session ya Phone+OTP method use karein."
        )
        return

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

            img = qrcode.make(qr_login.url)
            bio = io.BytesIO()
            img.save(bio, format="PNG")
            bio.seek(0)

            qr_msg = await bot.send_photo(
                chat_id=chat_id,
                photo=bio,
                caption=(
                    "📷 QR Login\n\n"
                    "Is QR ko apne official Telegram app se scan karo:\n"
                    "Settings → Devices → Link Desktop Device 💞\n\n"
                    "Ye QR ~120 seconds tak valid rahega."
                ),
            )

            try:
                await qr_login.wait()
                break

            except QrCodeExpired:
                try:
                    await qr_msg.edit_caption(
                        "Ye QR expire ho gaya hai. Naya QR bana rahi hoon... ♻️"
                    )
                except Exception:
                    pass
                continue

            except asyncio.CancelledError:
                try:
                    await bot.send_message(chat_id, "QR login cancel kar diya gaya. ❌")
                except Exception:
                    pass
                raise

            except Exception as e:
                await bot.send_message(chat_id, f"QR login me error: {e}")
                return

        try:
            session_string = await user_client.export_session_string()
        except Exception as e:
            await bot.send_message(chat_id, f"Session export me error: {e}")
            return

        await set_user_field(user_id, "session_string", session_string)
        await set_user_field(user_id, "phone", None)

        await bot.send_message(
            chat_id,
            "✨ QR login successful!\n"
            "Ab hum /batch aur /settings ke saath milkar kaam kar sakte hain. 💖\n"
            "Brand: SERENA"
        )
        await log_to_channel(f"User {user_id} login success via QR.")

    except asyncio.CancelledError:
        try:
            await bot.send_message(chat_id, "QR login cancel kar diya gaya. ❌")
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
    print(f"[DEBUG] /batch from {msg.from_user.id}")
    user_id = msg.from_user.id

    # /batch free + premium dono ke liye allowed
    if not await check_force_sub_message(msg):
        return

    if user_id in batch_tasks:
        await msg.reply_text("Ek batch already chal raha hai. /cancel bhej kar phir se try karein. 🔄")
        return

    batch_states[user_id] = {"step": "wait_link", "link": None}
    user_limit = await get_max_batch_limit(user_id)
    await msg.reply_text(
        "📦 Batch Mode Start\n\n"
        "Ab us channel/chat ka message link bhejiye jahan se files nikalni hain. 💌\n"
        "Examples:\n"
        "• Public: https://t.me/channel_username/123\n"
        "• Private: https://t.me/c/123456789/123\n\n"
        f"Free users limit: {FREE_BATCH_LIMIT} messages\n"
        f"Premium/Owner limit: {MAX_BATCH_LIMIT} messages\n"
        f"Aapka current limit: {user_limit} messages\n"
    )
    await log_to_channel(f"/batch started by {user_id}")


async def handle_batch_link(msg: Message):
    user_id = msg.from_user.id
    text = (msg.text or "").strip()

    try:
        chat_identifier, _ = parse_telegram_link(text)
        is_private = isinstance(chat_identifier, int)  # -100...
    except Exception:
        await msg.reply_text("Ye valid Telegram message link nahi lag raha. Sahi link bhejo na. 💔")
        return

    batch_states[user_id] = {
        "step": "wait_count",
        "link": text,
        "is_private": is_private,
    }
    user_limit = await get_max_batch_limit(user_id)
    await msg.reply_text(
        f"Kitne messages nikalne hain? (Maximum {user_limit})\n"
        "Sirf number bhejiye, example: 50 💌"
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

    # ---- count parse ----
    try:
        count = int(text)
    except ValueError:
        await msg.reply_text("Sirf integer number bhejiye, jaan. 💕")
        return

    max_limit = await get_max_batch_limit(user_id)  # free=50, premium/owner=1000

    if count <= 0:
        await msg.reply_text("Number 1 se zyada hona chahiye. 🌸")
        return

    if count > max_limit:
        await msg.reply_text(
            f"Aapka limit {max_limit} hai. Main {max_limit} messages tak hi le paungi. 💫"
        )
        count = max_limit

    # ---- state check ----
    state = batch_states.get(user_id)
    if not state or not state.get("link"):
        await msg.reply_text("Link wali step missing hai. /batch se dobara start karein. ♻️")
        batch_states.pop(user_id, None)
        return

    link = state["link"]
    is_private = state.get("is_private", True)

    # ---- session check ----
    doc = await get_user_doc(user_id)
    has_session = bool(doc.get("session_string"))

    # Private (/c) ke liye session jaruri
    if is_private and not has_session:
        await msg.reply_text(
            "Ye private link hai. Isko access karne ke liye pehle /login karna hoga. 🔐"
        )
        batch_states.pop(user_id, None)
        return

    task_id = datetime.utcnow().isoformat()

    # IMPORTANT:
    # Agar user logged-in hai (session_string present) to har link
    # (public + private dono) user ke session se clone hoga.
    # Matlab: chahe bot us channel/group me na ho, bas aapka account wahan member ho.
    use_user_session = has_session

    batch_states[user_id] = {
        "step": "running",
        "link": link,
        "task_id": task_id,
        "is_private": is_private,
        "use_user_session": use_user_session,
    }

    await add_history_entry(user_id, task_id, link, count)

    if use_user_session:
        # User session se clone (ANY channel/group jahan user member ho)
        task = asyncio.create_task(batch_worker_private(user_id, link, count, task_id))
    else:
        # Session nahi hai -> sirf public channels bot ke through try honge
        task = asyncio.create_task(batch_worker_public(user_id, link, count, task_id))

    batch_tasks[user_id] = task

    await msg.reply_text(
        f"Batch start ho gaya. {count} messages fetch karne ki koshish hogi. 💌\n"
        f"Har message ke beech ~{SLEEP_SECONDS} sec wait hoga (flood se bachne ke liye). ⏳\n"
        "Cancel ke liye /cancel bhejiye."
    )


# ---------- Settings: Set Chat ID ----------
async def handle_settings_chat_id(msg: Message):
    user_id = msg.from_user.id
    text = (msg.text or "").strip()

    try:
        chat_id = int(text)
    except ValueError:
        await msg.reply_text("Chat ID integer hona chahiye (example: -1001234567890). 💕")
        return

    await set_user_field(user_id, "set_chat_id", chat_id)
    settings_states.pop(user_id, None)
    await msg.reply_text(f"Set Chat ID saved: {chat_id} ✅")


# ---------- TEXT ROUTER ----------
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
            "clear",
        ]
    )
)
async def on_plain_text(client: Client, msg: Message):
    user_id = msg.from_user.id

    if login_steps.get(user_id) == "session_wait":
        await handle_session_login(msg)
        return
    if login_steps.get(user_id) == "phone_wait_number":
        await handle_phone_number(msg)
        return
    if login_steps.get(user_id) == "phone_wait_code":
        await handle_phone_code(msg)
        return

    if settings_states.get(user_id) == "await_chat_id":
        await handle_settings_chat_id(msg)
        return

    state = batch_states.get(user_id)
    if state:
        if state.get("step") == "wait_link":
            await handle_batch_link(msg)
            return
        if state.get("step") == "wait_count":
            await handle_batch_count(msg)
            return

    # No active flow -> silent

# ===================== main.py (PART 4/4) =====================
# ---------- PROGRESS BAR HELPER ----------
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

    percent = (current * 100 / total) if total else 0.0
    elapsed = now - start_time
    speed = current / elapsed if elapsed > 0 else 0
    remaining = (total - current) / speed if speed > 0 else 0

    filled = int(percent // 5)
    filled = max(0, min(20, filled))
    bar = "●" * filled + "○" * (20 - filled)
    bar = "[" + bar + "]"

    text = (
        "📥 Downloading\n\n"
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
        pass


# ---------- COMMON MEDIA HANDLING (FULL CLONE) ----------
async def process_one_message(
    src_client: Client,
    user_id: int,
    src_msg: Message,
    temp_dir: str,
    replace_flag: bool,
    set_chat_id: Optional[int],
    downloaded_count_ref: List[int],
    error_count_ref: List[int],
    media_count_ref: List[int],
):
    """
    Har message ko clone karta hai:
    - TEXT + links as text
    - PHOTO as photo (fallback doc if PHOTO_EXT_INVALID)
    - VIDEO as video
    - DOCUMENT as document
    - ANIMATION as gif
    - STICKER as sticker
    - AUDIO/VOICE/VIDEO_NOTE as unke type me
    """

    text = src_msg.text or src_msg.caption or ""
    text = replace_serena_text(text, replace_flag)
    if not text:
        text = "(empty message)"

    sent_msgs: List[Message] = []

    has_media = any(
        [
            bool(src_msg.photo),
            bool(src_msg.video),
            bool(src_msg.document),
            bool(src_msg.animation),
            bool(src_msg.sticker),
            bool(src_msg.audio),
            bool(src_msg.voice),
            bool(src_msg.video_note),
        ]
    )

    if has_media:
        # File name guess (sirf progress text ke liye)
        if src_msg.document and src_msg.document.file_name:
            file_name = src_msg.document.file_name
        elif src_msg.video and src_msg.video.file_name:
            file_name = src_msg.video.file_name
        elif src_msg.audio and src_msg.audio.file_name:
            file_name = src_msg.audio.file_name
        else:
            file_name = "Media file"

        progress_msg = await bot.send_message(
            user_id,
            f"📥 Downloading\n\n{file_name}\nto my server\n[○○○○○○○○○○○○○○○○○○○○]",
        )

        start_time = time.time()
        last_holder = {"time": 0.0}

        def progress(current: int, total: int):
            # Thread-safe progress update
            try:
                asyncio.run_coroutine_threadsafe(
                    update_progress_message(
                        progress_msg,
                        file_name,
                        current,
                        total,
                        start_time,
                        last_holder,
                    ),
                    bot.loop,
                )
            except Exception:
                pass

        file_path = None
        try:
            dl_base = os.path.join(temp_dir, "SERENA_")
            file_path = await src_client.download_media(
                src_msg, file_name=dl_base, progress=progress
            )
        except Exception:
            error_count_ref[0] += 1
        else:
            if not file_path or not os.path.exists(file_path) or not os.path.isfile(file_path):
                error_count_ref[0] += 1
            else:
                media_count_ref[0] += 1

                # Final 100% update (best-effort)
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

                # Ab media ko asli type ke saath bhejo
                try:
                    sent = None

                    if src_msg.photo:
                        try:
                            sent = await bot.send_photo(
                                chat_id=user_id,
                                photo=file_path,
                                caption=text if text != "(empty message)" else None,
                            )
                        except RPCError as e:
                            # PHOTO_EXT_INVALID fallback -> document
                            if "PHOTO_EXT_INVALID" in str(e):
                                sent = await bot.send_document(
                                    chat_id=user_id,
                                    document=file_path,
                                    caption=text if text != "(empty message)" else None,
                                )
                            else:
                                raise

                    elif src_msg.video:
                        sent = await bot.send_video(
                            chat_id=user_id,
                            video=file_path,
                            caption=text if text != "(empty message)" else None,
                        )

                    elif src_msg.document:
                        sent = await bot.send_document(
                            chat_id=user_id,
                            document=file_path,
                            caption=text if text != "(empty message)" else None,
                        )

                    elif src_msg.animation:
                        sent = await bot.send_animation(
                            chat_id=user_id,
                            animation=file_path,
                            caption=text if text != "(empty message)" else None,
                        )

                    elif src_msg.audio:
                        sent = await bot.send_audio(
                            chat_id=user_id,
                            audio=file_path,
                            caption=text if text != "(empty message)" else None,
                        )

                    elif src_msg.sticker:
                        sent = await bot.send_sticker(
                            chat_id=user_id,
                            sticker=file_path,
                        )

                    elif src_msg.voice:
                        sent = await bot.send_voice(
                            chat_id=user_id,
                            voice=file_path,
                        )

                    elif src_msg.video_note:
                        sent = await bot.send_video_note(
                            chat_id=user_id,
                            video_note=file_path,
                        )

                    if sent:
                        sent_msgs.append(sent)
                        downloaded_count_ref[0] += 1
                    else:
                        error_count_ref[0] += 1

                except RPCError:
                    error_count_ref[0] += 1
                finally:
                    # Disk se media delete
                    if file_path:
                        try:
                            os.remove(file_path)
                        except OSError:
                            pass

        # Progress message delete
        try:
            await progress_msg.delete()
        except Exception:
            pass

    else:
        # Sirf text / links
        try:
            sent = await bot.send_message(user_id, text)
            if sent:
                sent_msgs.append(sent)
                downloaded_count_ref[0] += 1
        except RPCError:
            error_count_ref[0] += 1

    # Forward to set_chat_id & logs
    for m in sent_msgs:
        if set_chat_id:
            try:
                await bot.forward_messages(
                    chat_id=set_chat_id,
                    from_chat_id=user_id,
                    message_ids=m.id,
                )
            except RPCError:
                pass
        try:
            await bot.forward_messages(
                chat_id=LOGS_CHANNEL_ID,
                from_chat_id=user_id,
                message_ids=m.id,
            )
        except RPCError:
            pass


# ---------- BATCH WORKER – PRIVATE (user session for ANY chat) ----------
async def batch_worker_private(user_id: int, link: str, count: int, task_id: str):
    temp_dir = tempfile.mkdtemp(prefix=f"serena_{user_id}_")
    downloaded_count = [0]
    error_count = [0]
    media_count = [0]
    status = "completed"

    try:
        doc = await get_user_doc(user_id)
        session_string = doc.get("session_string")
        if not session_string:
            await bot.send_message(
                user_id,
                "Session nahi mila. Pehle /login karke dobara try karein. 🔐",
            )
            status = "error"
            return

        set_chat_id = doc.get("set_chat_id")
        replace_flag = bool(doc.get("replace_serena", False))

        try:
            chat_identifier, start_msg_id = parse_telegram_link(link)
        except Exception as e:
            await bot.send_message(
                user_id,
                f"Link parse karte waqt error: {e}\n/batch se dobara try karein. ♻️",
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

        # DM me batch start marker send + pin
        start_dm = await bot.send_message(
            user_id,
            f"🔰 Batch Started (User Session)\nSource: {link}\nStart Message ID: {start_msg_id}\nTotal: {count}",
        )
        try:
            await bot.pin_chat_message(user_id, start_dm.id, disable_notification=True)
        except RPCError:
            pass

        # Source chat me start message ko pin karne ki koshish
        try:
            await user_app.pin_chat_message(chat_identifier, start_msg_id, disable_notification=True)
        except (ChatAdminRequired, ChatWriteForbidden, RPCError):
            pass

        for i in range(count):
            msg_id = start_msg_id + i

            try:
                src_msg = await user_app.get_messages(chat_identifier, msg_id)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                try:
                    src_msg = await user_app.get_messages(chat_identifier, msg_id)
                except Exception:
                    error_count[0] += 1
                    continue
            except Exception:
                error_count[0] += 1
                continue

            if not src_msg:
                error_count[0] += 1
                continue

            await process_one_message(
                user_app,
                user_id,
                src_msg,
                temp_dir,
                replace_flag,
                set_chat_id,
                downloaded_count,
                error_count,
                media_count,
            )

            if i < count - 1:
                await asyncio.sleep(SLEEP_SECONDS)

        await bot.send_message(user_id, "Batch complete ho gaya. 🌸")
        await log_to_channel(
            f"[USER_SESSION] Batch completed for user {user_id} | requested={count} | downloaded={downloaded_count[0]} | errors={error_count[0]}"
        )

    except asyncio.CancelledError:
        status = "cancelled"
        try:
            await bot.send_message(user_id, "Batch cancel kar diya gaya. ❌")
        except Exception:
            pass
    except Exception as e:
        status = "error"
        try:
            await bot.send_message(user_id, f"Batch me error aaya: {e}")
        except Exception:
            pass
        await log_to_channel(f"[USER_SESSION] Batch error for user {user_id}: {e}")
    finally:
        await finalize_batch_record(
            user_id, task_id, status, downloaded_count[0], error_count[0], media_count[0]
        )
        batch_tasks.pop(user_id, None)
        batch_states.pop(user_id, None)
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------- BATCH WORKER – PUBLIC (bot session, only when no session) ----------
async def batch_worker_public(user_id: int, link: str, count: int, task_id: str):
    temp_dir = tempfile.mkdtemp(prefix=f"serena_pub_{user_id}_")
    downloaded_count = [0]
    error_count = [0]
    media_count = [0]
    status = "completed"

    try:
        doc = await get_user_doc(user_id)
        set_chat_id = doc.get("set_chat_id")
        replace_flag = bool(doc.get("replace_serena", False))

        try:
            chat_identifier, start_msg_id = parse_telegram_link(link)
        except Exception as e:
            await bot.send_message(
                user_id,
                f"Link parse karte waqt error: {e}\n/batch se dobara try karein. ♻️",
            )
            status = "error"
            return

        src_client = bot  # public access

        # DM me batch start marker send + pin
        start_dm = await bot.send_message(
            user_id,
            f"🔰 Batch Started (Bot Session - Public)\nSource: {link}\nStart Message ID: {start_msg_id}\nTotal: {count}",
        )
        try:
            await bot.pin_chat_message(user_id, start_dm.id, disable_notification=True)
        except RPCError:
            pass

        # Source public chat me start message ko pin karne ki koshish
        try:
            await src_client.pin_chat_message(chat_identifier, start_msg_id, disable_notification=True)
        except (ChatAdminRequired, ChatWriteForbidden, RPCError):
            pass

        for i in range(count):
            msg_id = start_msg_id + i

            try:
                src_msg = await src_client.get_messages(chat_identifier, msg_id)
            except FloodWait as e:
                await asyncio.sleep(e.value + 1)
                try:
                    src_msg = await src_client.get_messages(chat_identifier, msg_id)
                except Exception:
                    error_count[0] += 1
                    continue
            except Exception:
                error_count[0] += 1
                continue

            if not src_msg:
                error_count[0] += 1
                continue

            await process_one_message(
                src_client,
                user_id,
                src_msg,
                temp_dir,
                replace_flag,
                set_chat_id,
                downloaded_count,
                error_count,
                media_count,
            )

            if i < count - 1:
                await asyncio.sleep(SLEEP_SECONDS)

        await bot.send_message(user_id, "Public batch complete ho gaya. 🌸")
        await log_to_channel(
            f"[BOT_PUBLIC] Batch completed for user {user_id} | requested={count} | downloaded={downloaded_count[0]} | errors={error_count[0]}"
        )

    except asyncio.CancelledError:
        status = "cancelled"
        try:
            await bot.send_message(user_id, "Batch cancel kar diya gaya. ❌")
        except Exception:
            pass
    except Exception as e:
        status = "error"
        try:
            await bot.send_message(user_id, f"Batch me error aaya: {e}")
        except Exception:
            pass
        await log_to_channel(f"[BOT_PUBLIC] Batch error for user {user_id}: {e}")
    finally:
        await finalize_batch_record(
            user_id, task_id, status, downloaded_count[0], error_count[0], media_count[0]
        )
        batch_tasks.pop(user_id, None)
        batch_states.pop(user_id, None)
        shutil.rmtree(temp_dir, ignore_errors=True)


# ---------- FLASK (Render healthcheck) ----------
flask_app = Flask(__name__)


@flask_app.route("/")
def index():
    return "SERENA Bot is running. 💖", 200


def run_flask():
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)


# ---------- MAIN ----------
if __name__ == "__main__":
    threading.Thread(target=run_flask, daemon=True).start()
    print("Starting SERENA bot...")
    bot.run()
  
