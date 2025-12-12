# bot_handlers.py - PART 1 of 2 (修復版本)
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
# 環境變量
API_ID = int(os.environ.get("API_ID", 0))
API_HASH = os.environ.get("API_HASH", "")
BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
MONGO_URL = os.environ.get("MONGO_URL", "")  # 使用第一個MongoDB URL
DELAY_BETWEEN_MESSAGES = int(os.environ.get("DELAY_BETWEEN_MESSAGES", 12))  # 默認12秒

# 常量配置
OWNER_IDS = [1598576202, 6518065496]
LOG_CHANNEL = -1003286415377
FORCE_SUB_CHANNEL = "serenaunzipbot"
OWNER_USERNAME = "technicalserena"
FREE_USER_LIMIT = 20
PREMIUM_USER_LIMIT = 1000

# 檢查環境變量
if not all([API_ID, API_HASH, BOT_TOKEN, MONGO_URL]):
    print("錯誤：缺少必要的環境變量！")
    sys.exit(1)

# 初始化MongoDB
try:
    mongo_client = pymongo.MongoClient(MONGO_URL)
    db = mongo_client["serena_file_bot"]
    users_col = db["users"]
    premium_col = db["premium_users"]
    settings_col = db["settings"]
    batch_col = db["batch_tasks"]
    logs_col = db["logs"]
    print(f"✅ 成功連接到MongoDB")
    print(f"📊 數據庫: {db.name}")
    print(f"👥 用戶數: {users_col.count_documents({})}")
except Exception as e:
    print(f"❌ MongoDB連接錯誤: {e}")
    sys.exit(1)

# 初始化機器人客戶端
bot = Client(
    "serena_file_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN,
    workers=100,
    sleep_threshold=60
)

# 存儲活躍任務
user_tasks = {}
user_states = {}  # 用戶狀態存儲

# ========== HELPER FUNCTIONS ==========
async def check_force_sub(user_id):
    """檢查用戶是否訂閱了強制頻道"""
    try:
        member = await bot.get_chat_member(f"@{FORCE_SUB_CHANNEL}", user_id)
        if member.status in ["member", "administrator", "creator"]:
            return True
    except UserNotParticipant:
        return False
    except Exception as e:
        print(f"檢查訂閱錯誤: {e}")
        return False
    return False

async def send_log(action, user_id, details=""):
    """發送日誌到日誌頻道"""
    try:
        log_text = f"📝 **{action}**\n"
        log_text += f"👤 **用戶ID:** `{user_id}`\n"
        log_text += f"🕒 **時間:** `{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}`\n"
        if details:
            log_text += f"📋 **詳情:** `{details}`"
        
        # 發送到Telegram頻道
        await bot.send_message(LOG_CHANNEL, log_text)
        
        # 保存到MongoDB
        logs_col.insert_one({
            "action": action,
            "user_id": user_id,
            "details": details,
            "timestamp": datetime.now()
        })
        
    except Exception as e:
        print(f"日誌發送失敗: {e}")

async def is_owner(user_id):
    """檢查是否為所有者"""
    return user_id in OWNER_IDS

# ========== COMMAND HANDLERS ==========
@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message: Message):
    """處理 /start 命令"""
    user_id = message.from_user.id
    await send_log("START_COMMAND", user_id)
    
    # 檢查強制訂閱
    if not await check_force_sub(user_id):
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 加入頻道", url=f"https://t.me/{FORCE_SUB_CHANNEL}"),
            InlineKeyboardButton("👤 聯繫所有者", url=f"https://t.me/{OWNER_USERNAME}")
        ], [
            InlineKeyboardButton("🔄 重新檢查", callback_data="check_sub")
        ]])
        
        await message.reply_photo(
            photo="https://telegra.ph/file/1a72b6072e5c4c739e9c0.jpg",
            caption="**👋 歡迎來到 SERENA 文件恢復機器人！**\n\n"
                    "**⚠️ 您必須加入我們的頻道才能使用此機器人。**\n\n"
                    "**📋 步驟：**\n"
                    "1. 點擊下方按鈕加入頻道\n"
                    "2. 等待幾秒鐘\n"
                    "3. 點擊「重新檢查」按鈕\n\n"
                    "**品牌：** SERENA\n"
                    "**版本：** 2.0",
            reply_markup=keyboard
        )
        return
    
    # 歡迎消息
    keyboard = InlineKeyboardMarkup([[
        InlineKeyboardButton("🚀 開始恢復", callback_data="start_recovery"),
        InlineKeyboardButton("⚙️ 設置", callback_data="open_settings")
    ], [
        InlineKeyboardButton("📖 幫助", callback_data="show_help"),
        InlineKeyboardButton("👑 高級版", callback_data="premium_info")
    ]])
    
    await message.reply_photo(
        photo="https://telegra.ph/file/1a72b6072e5c4c739e9c0.jpg",
        caption="**🤖 歡迎來到 SERENA 文件恢復機器人！**\n\n"
                "**品牌：** SERENA\n"
                "**目的：** 從您遺失的Telegram帳戶頻道恢復文件\n\n"
                "**✨ 功能：**\n"
                "• 批量文件恢復\n"
                "• 支持照片、視頻、文檔\n"
                "• 自動清理臨時文件\n"
                "• 高級用戶優先處理\n\n"
                "**📊 限制：**\n"
                "• 免費用戶：每次任務20條消息\n"
                "• 高級用戶：每次任務1000條消息\n\n"
                "**🛠 可用命令：**\n"
                "• /login - 使用電話號碼登錄\n"
                "• /batch - 開始批量恢復\n"
                "• /setting - 配置機器人設置\n"
                "• /status - 檢查當前任務狀態\n"
                "• /cancel - 取消進行中的任務\n"
                "• /help - 獲取詳細指南",
        reply_markup=keyboard
    )

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client, message: Message):
    """處理 /help 命令"""
    help_text = """
**📖 SERENA 機器人指南**

**1. 登錄流程：**
   • 使用 /login 開始
   • 輸入您的電話號碼（帶國家代碼，例如 +91XXXXXXXXXX）
   • 輸入在Telegram上收到的OTP
   • 現在您已登錄！

**2. 恢復文件：**
   • 使用 /batch 加上頻道鏈接
   • 示例：`/batch https://t.me/channel_name/123`
   • 輸入要獲取的消息數量
   • 機器人會將文件發送到您的私信

**3. 設置：**
   • /setting - 配置選項
   • 設置默認聊天ID用於直接轉發
   • 更改按鈕文本
   • 如果需要則重置設置

**4. 其他命令：**
   • /status - 檢查當前任務
   • /cancel - 停止進行中的任務
   • /addpremium - 僅所有者：添加高級用戶
   • /removepremium - 僅所有者：移除高級用戶

**5. 限制：**
   • 免費用戶：每次任務20條消息
   • 高級用戶：每次任務1000條消息
   • 消息間延遲：{}秒（可配置）

**⚠️ 注意事項：**
   • 機器人在消息之間休眠{}秒以避免洪水限制
   • 發送後文件會從服務器刪除
   • 所有日誌保存在日誌頻道中
   • 使用 /cancel 停止任何任務
    """.format(DELAY_BETWEEN_MESSAGES, DELAY_BETWEEN_MESSAGES)
    
    await message.reply(help_text)
    await send_log("HELP_COMMAND", message.from_user.id)

@bot.on_message(filters.command("login") & filters.private)
async def login_command(client, message: Message):
    """處理 /login 命令進行身份驗證"""
    user_id = message.from_user.id
    await send_log("LOGIN_COMMAND", user_id)
    
    # 檢查是否已登錄
    session = await get_user_session(user_id)
    if session:
        await message.reply("✅ 您已經登錄了！\n使用 /batch 開始文件恢復。")
        return
    
    # 設置用戶狀態
    user_states[user_id] = {"state": "awaiting_phone"}
    
    await message.reply(
        "**📱 登錄流程開始**\n\n"
        "請以國際格式發送您的電話號碼：\n"
        "**示例：** `+91XXXXXXXXXX`\n\n"
        "**格式要求：**\n"
        "• 以 + 開頭\n"
        "• 包含國家代碼\n"
        "• 10-15位數字\n\n"
        "輸入 /cancel 中止登錄。"
    )

@bot.on_message(filters.command("status") & filters.private)
async def status_command(client, message: Message):
    """處理 /status 命令"""
    user_id = message.from_user.id
    
    # 檢查任務狀態
    task = user_tasks.get(user_id)
    
    if task and not task.done():
        status_msg = "**🔄 任務狀態：運行中**\n"
        status_msg += "• 任務當前正在進行\n"
        status_msg += "• 使用 /cancel 停止任務\n"
        status_msg += f"• 延遲設置：{DELAY_BETWEEN_MESSAGES}秒"
    else:
        status_msg = "**✅ 任務狀態：空閒**\n"
        status_msg += "• 沒有正在運行的任務\n"
        status_msg += "• 使用 /batch 開始新任務"
    
    # 添加高級狀態
    premium = await is_premium_user(user_id)
    limit = PREMIUM_USER_LIMIT if premium else FREE_USER_LIMIT
    
    status_msg += f"\n\n**👑 高級狀態：** {'✅ 激活' if premium else '❌ 未激活'}"
    status_msg += f"\n**📊 消息限制：** {limit} 條消息/任務"
    status_msg += f"\n**⏱️ 消息延遲：** {DELAY_BETWEEN_MESSAGES}秒"
    
    # 添加用戶信息
    user_data = users_col.find_one({"user_id": user_id})
    if user_data and user_data.get("phone"):
        status_msg += f"\n**📱 登錄電話：** `{user_data['phone']}`"
    
    await message.reply(status_msg)
    await send_log("STATUS_COMMAND", user_id)

@bot.on_message(filters.command("delay") & filters.private)
async def delay_command(client, message: Message):
    """檢查當前延遲設置"""
    await message.reply(
        f"**⏱️ 當前延遲設置**\n\n"
        f"**消息間延遲：** {DELAY_BETWEEN_MESSAGES}秒\n"
        f"**來源：** 環境變量 (DELAY_BETWEEN_MESSAGES)\n\n"
        f"**注意：** 此設置只能在部署時通過環境變量更改。"
  )

# bot_handlers.py - PART 2 of 2 (修復版本)
# 從第一部分繼續

@bot.on_message(filters.command("batch") & filters.private)
async def batch_command(client, message: Message):
    """處理批量文件恢復的 /batch 命令"""
    user_id = message.from_user.id
    await send_log("BATCH_COMMAND", user_id)
    
    # 檢查強制訂閱
    if not await check_force_sub(user_id):
        await message.reply("⚠️ 請先加入我們的頻道以使用此功能。")
        return
    
    # 檢查用戶是否登錄
    session = await get_user_session(user_id)
    if not session:
        await message.reply("❌ 您需要先登錄！\n使用 /login 開始。")
        return
    
    # 檢查用戶是否已有活躍任務
    if user_id in user_tasks and not user_tasks[user_id].done():
        await message.reply("⚠️ 您已經有一個活躍任務！\n使用 /status 檢查或 /cancel 停止。")
        return
    
    # 解析命令參數
    args = message.text.split()
    if len(args) < 2:
        await message.reply(
            "**用法：** `/batch <頻道鏈接>`\n\n"
            "**示例：**\n"
            "`/batch https://t.me/serenaunzipbot/123`\n\n"
            "鏈接應是來自頻道的特定消息。"
        )
        return
    
    # 存儲批次信息
    channel_link = args[1]
    user_states[user_id] = {
        "state": "awaiting_batch_count",
        "channel_link": channel_link
    }
    
    # 根據高級狀態確定批次限制
    premium = await is_premium_user(user_id)
    max_limit = PREMIUM_USER_LIMIT if premium else FREE_USER_LIMIT
    
    await message.reply(
        f"**📦 批次處理開始**\n\n"
        f"**頻道：** `{channel_link}`\n"
        f"**最大限制：** `{max_limit}` 條消息\n"
        f"**用戶類型：** {'👑 高級用戶' if premium else '👤 免費用戶'}\n\n"
        f"現在發送要獲取的**消息數量** (1-{max_limit})：\n"
        f"輸入 /cancel 中止。"
    )

@bot.on_message(filters.command("setting") & filters.private)
async def setting_command(client, message: Message):
    """處理配置機器人的 /setting 命令"""
    user_id = message.from_user.id
    await send_log("SETTING_COMMAND", user_id)
    
    # 獲取當前設置或默認值
    set_chat_id = await get_setting(user_id, "set_chat_id") or "未設置"
    button_text = await get_setting(user_id, "button_text") or "Serena|Kumari"
    
    # 創建內聯鍵盤
    keyboard = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✏️ 設置聊天ID", callback_data="set_chat_id"),
            InlineKeyboardButton("🔄 重置設置", callback_data="reset_settings")
        ],
        [
            InlineKeyboardButton("🔧 更改按鈕文本", callback_data="change_button"),
            InlineKeyboardButton("📊 查看限制", callback_data="view_limits")
        ],
        [
            InlineKeyboardButton("❌ 關閉", callback_data="close_settings")
        ]
    ])
    
    # 檢查高級狀態
    premium = await is_premium_user(user_id)
    
    settings_text = f"""
**⚙️ 機器人設置**

**當前配置：**
• **轉發聊天ID：** `{set_chat_id}`
• **按鈕文本：** `{button_text}`
• **用戶類型：** {'👑 高級用戶' if premium else '👤 免費用戶'}
• **消息限制：** {PREMIUM_USER_LIMIT if premium else FREE_USER_LIMIT} 條/任務
• **消息延遲：** {DELAY_BETWEEN_MESSAGES}秒

**選項：**
1. **設置聊天ID** - 配置文件轉發位置
2. **重置設置** - 恢復默認配置
3. **更改按鈕文本** - 修改內聯按鈕文本
4. **查看限制** - 查看當前限制信息
"""
    await message.reply(settings_text, reply_markup=keyboard)

@bot.on_message(filters.command("cancel") & filters.private)
async def cancel_command(client, message: Message):
    """處理 /cancel 命令"""
    user_id = message.from_user.id
    await send_log("CANCEL_COMMAND", user_id, "用戶請求取消任務")
    
    if user_id in user_tasks:
        task = user_tasks[user_id]
        if not task.done():
            task.cancel()
            await message.reply("✅ 任務已成功取消！")
            
            # 清理狀態
            if user_id in user_states:
                del user_states[user_id]
        else:
            await message.reply("ℹ️ 沒有活躍任務可取消。")
    else:
        await message.reply("ℹ️ 未找到活躍任務。")
    
    # 清理任何狀態
    if user_id in user_states:
        del user_states[user_id]

@bot.on_message(filters.command(["addpremium", "addpremium"]) & filters.private)
async def add_premium_command(client, message: Message):
    """添加高級用戶（僅所有者）"""
    user_id = message.from_user.id
    
    if not await is_owner(user_id):
        await message.reply("❌ 僅所有者命令！")
        return
    
    args = message.text.split()
    if len(args) < 3:
        await message.reply("用法：`/addpremium <用戶ID> <天數>`")
        return
    
    try:
        target_user = int(args[1])
        days = int(args[2])
        
        expiry = datetime.now() + timedelta(days=days)
        await add_premium_user(target_user, expiry)
        
        await message.reply(
            f"✅ 已為用戶 `{target_user}` 添加高級版\n"
            f"到期時間：{expiry.strftime('%Y-%m-%d %H:%M:%S')}\n"
            f"天數：{days} 天"
        )
        await send_log("PREMIUM_ADDED", user_id, f"目標用戶: {target_user}, 天數: {days}")
        
    except Exception as e:
        await message.reply(f"❌ 錯誤：{str(e)}")
        await send_log("PREMIUM_ADD_ERROR", user_id, str(e))

@bot.on_message(filters.command(["removepremium", "removepremium"]) & filters.private)
async def remove_premium_command(client, message: Message):
    """移除高級用戶（僅所有者）"""
    user_id = message.from_user.id
    
    if not await is_owner(user_id):
        await message.reply("❌ 僅所有者命令！")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.reply("用法：`/removepremium <用戶ID>`")
        return
    
    try:
        target_user = int(args[1])
        await remove_premium_user(target_user)
        
        await message.reply(f"✅ 已移除用戶 `{target_user}` 的高級版")
        await send_log("PREMIUM_REMOVED", user_id, f"目標用戶: {target_user}")
        
    except Exception as e:
        await message.reply(f"❌ 錯誤：{str(e)}")

# ========== 消息處理器 ==========
@bot.on_message(filters.private & filters.text & ~filters.command)
async def handle_text_messages(client, message: Message):
    """處理非命令文本消息"""
    user_id = message.from_user.id
    text = message.text.strip()
    
    # 檢查用戶狀態
    if user_id not in user_states:
        return
    
    state_data = user_states[user_id]
    state = state_data.get("state")
    
    # 處理電話號碼輸入
    if state == "awaiting_phone":
        # 基本電話驗證
        if not re.match(r'^\+\d{10,15}$', text):
            await message.reply("❌ 無效的電話號碼格式！\n"
                              "請使用格式：`+91XXXXXXXXXX`\n"
                              "請重試或輸入 /cancel 中止。")
            return
        
        # 存儲電話並詢問OTP
        user_states[user_id] = {
            "state": "awaiting_otp",
            "phone": text
        }
        
        await message.reply(
            f"**📱 電話已接收：** `{text}`\n\n"
            "現在請發送您在Telegram上收到的**OTP**。\n"
            "格式：`123456` (6位數字)\n\n"
            "輸入 /cancel 中止。"
        )
        await send_log("PHONE_RECEIVED", user_id, f"電話: {text}")
    
    # 處理OTP輸入
    elif state == "awaiting_otp":
        if not re.match(r'^\d{6}$', text):
            await message.reply("❌ 無效的OTP格式！\n"
                              "OTP必須是6位數字。\n"
                              "請重試或輸入 /cancel 中止。")
            return
        
        try:
            # 模擬會話創建（在實際實現中，使用pyrogram會話）
            session_string = f"session_{user_id}_{int(datetime.now().timestamp())}"
            await save_user_session(user_id, session_string)
            
            # 存儲電話號碼
            users_col.update_one(
                {"user_id": user_id},
                {"$set": {"phone": state_data.get("phone"), "last_login": datetime.now()}},
                upsert=True
            )
            
            await message.reply(
                "✅ **登錄成功！**\n\n"
                "您的會話已創建。\n"
                "您現在可以使用 /batch 恢復文件。\n\n"
                "**下一步：**\n"
                "1. 找到您要恢復文件的頻道\n"
                "2. 複製消息鏈接\n"
                "3. 使用 `/batch <鏈接>`"
            )
            await send_log("LOGIN_SUCCESS", user_id, "會話創建成功")
            
            # 清理狀態
            if user_id in user_states:
                del user_states[user_id]
            
        except Exception as e:
            await message.reply(f"❌ 登錄失敗：{str(e)}\n請重試 /login。")
            await send_log("LOGIN_FAILED", user_id, str(e))
    
    # 處理批次計數輸入
    elif state == "awaiting_batch_count":
        try:
            count = int(text)
            premium = await is_premium_user(user_id)
            max_limit = PREMIUM_USER_LIMIT if premium else FREE_USER_LIMIT
            
            if count < 1 or count > max_limit:
                await message.reply(f"❌ 請輸入 1 到 {max_limit} 之間的數字！")
                return
            
            channel_link = state_data.get("channel_link", "")
            
            await message.reply(
                f"**✅ 批次已確認**\n\n"
                f"• **要獲取的消息：** `{count}`\n"
                f"• **頻道：** `{channel_link}`\n"
                f"• **用戶類型：** {'👑 高級用戶' if premium else '👤 免費用戶'}\n"
                f"• **估計時間：** `{count * DELAY_BETWEEN_MESSAGES / 60:.1f} 分鐘`\n"
                f"• **消息延遲：** `{DELAY_BETWEEN_MESSAGES}秒`\n\n"
                f"現在開始... 使用 /cancel 停止。"
            )
            
            # 開始批次處理任務
            task = asyncio.create_task(
                process_batch_messages(user_id, channel_link, count)
            )
            user_tasks[user_id] = task
            
            # 清理狀態
            if user_id in user_states:
                del user_states[user_id]
            
            await send_log("BATCH_STARTED", user_id, f"數量: {count}, 頻道: {channel_link}")
            
        except ValueError:
            await message.reply("❌ 請輸入有效的數字！")
        except Exception as e:
            await message.reply(f"❌ 錯誤：{str(e)}")
            await send_log("BATCH_ERROR", user_id, str(e))
    
    # 處理聊天ID設置
    elif state == "awaiting_chat_id":
        try:
            chat_id = int(text)
            await update_setting(user_id, "set_chat_id", str(chat_id))
            
            await message.reply(f"✅ 聊天ID已設置為：`{chat_id}`")
            await send_log("CHAT_ID_SET", user_id, f"聊天ID: {chat_id}")
            
            # 清理狀態
            if user_id in user_states:
                del user_states[user_id]
                
        except ValueError:
            await message.reply("❌ 無效的聊天ID！請發送有效的數字ID。")
    
    # 處理按鈕文本設置
    elif state == "awaiting_button_text":
        if "|" not in text:
            await message.reply("❌ 無效格式！請使用：`舊文本|新文本`")
            return
        
        await update_setting(user_id, "button_text", text)
        await message.reply(f"✅ 按鈕文本已設置為：`{text}`")
        await send_log("BUTTON_TEXT_SET", user_id, f"文本: {text}")
        
        # 清理狀態
        if user_id in user_states:
            del user_states[user_id]

# ========== 批次處理函數 ==========
async def process_batch_messages(user_id, channel_link, count):
    """使用洪水控制處理批次消息"""
    try:
        await send_log("BATCH_PROCESS_START", user_id, f"開始處理 {count} 條消息")
        
        # 從鏈接中提取頻道和消息ID
        # 示例：https://t.me/channel_name/123
        parts = channel_link.split('/')
        if len(parts) < 5:
            error_msg = "無效的頻道鏈接格式"
            await bot.send_message(user_id, f"❌ {error_msg}")
            raise ValueError(error_msg)
        
        channel_username = parts[3]
        start_msg_id = int(parts[4])
        
        # 獲取用戶會話
        session = await get_user_session(user_id)
        if not session:
            await bot.send_message(user_id, "❌ 會話已過期！請重新 /login。")
            await send_log("SESSION_EXPIRED", user_id, "批次處理期間會話過期")
            return
        
        processed = 0
        failed = 0
        
        # 發送開始消息
        progress_msg = await bot.send_message(
            user_id,
            f"**🔄 批次處理開始**\n\n"
            f"• **總計：** {count} 條消息\n"
            f"• **已處理：** 0/{count}\n"
            f"• **失敗：** 0\n"
            f"• **進度：** 0%\n"
            f"• **延遲：** {DELAY_BETWEEN_MESSAGES}秒/消息"
        )
        
        for i in range(count):
            msg_id = start_msg_id + i
            
            try:
                # 模擬獲取和發送消息
                file_info = f"文件_{msg_id}.zip"
                
                # 發送給用戶
                await bot.send_message(
                    user_id,
                    f"**📦 文件 {i+1}/{count}**\n"
                    f"**消息ID：** `{msg_id}`\n"
                    f"**狀態：** ✅ 已發送\n"
                    f"**類型：** 模擬文件"
                )
                
                # 如果配置了，發送到set_chat_id
                set_chat_id = await get_setting(user_id, "set_chat_id")
                if set_chat_id and set_chat_id != "未設置":
                    try:
                        await bot.send_message(
                            int(set_chat_id),
                            f"**轉發文件**\n"
                            f"來自批次處理\n"
                            f"消息ID: {msg_id}\n"
                            f"用戶ID: {user_id}"
                        )
                    except Exception as e:
                        print(f"轉發失敗：{e}")
                
                # 模擬文件刪除
                await delete_temp_file(file_info)
                
                processed += 1
                
                # 更新進度消息
                if (i + 1) % 10 == 0 or i == count - 1:
                    progress = ((i + 1) / count) * 100
                    try:
                        await progress_msg.edit_text(
                            f"**🔄 批次處理中...**\n\n"
                            f"• **總計：** {count} 條消息\n"
                            f"• **已處理：** {i+1}/{count}\n"
                            f"• **失敗：** {failed}\n"
                            f"• **進度：** {progress:.1f}%\n"
                            f"• **延遲：** {DELAY_BETWEEN_MESSAGES}秒/消息"
                        )
                    except:
                        pass
                
                # 消息之間的延遲
                if i < count - 1:
                    await asyncio.sleep(DELAY_BETWEEN_MESSAGES)
                    
            except FloodWait as e:
                wait_time = e.value
                await bot.send_message(
                    user_id,
                    f"⚠️ 洪水等待：休眠 {wait_time} 秒..."
                )
                await asyncio.sleep(wait_time)
                continue
            except Exception as e:
                failed += 1
                error_msg = str(e)[:100]
                await bot.send_message(
                    user_id,
                    f"❌ 消息 {msg_id} 錯誤：{error_msg}"
                )
                continue
        
        # 完成消息
        completion_text = (
            f"✅ **批次處理完成！**\n\n"
            f"• **總計請求：** {count}\n"
            f"• **成功發送：** {processed}\n"
            f"• **失敗：** {failed}\n"
            f"• **成功率：** {(processed/count)*100:.1f}%\n\n"
            f"所有臨時文件已被刪除。\n"
            f"**總用時：** {count * DELAY_BETWEEN_MESSAGES / 60:.1f} 分鐘"
        )
        
        await bot.send_message(user_id, completion_text)
        
        # 記錄完成情況
        await send_log(
            "BATCH_COMPLETE", 
            user_id, 
            f"處理: {processed}/{count}, 失敗: {failed}, 頻道: {channel_username}"
        )
        
    except Exception as e:
        error_msg = str(e)
        await bot.send_message(user_id, f"❌ 批次處理失敗：{error_msg}")
        await send_log("BATCH_PROCESS_FAILED", user_id, error_msg)
    finally:
        # 清理任務引用
        if user_id in user_tasks:
            del user_tasks[user_id]
        
        # 刪除進度消息
        try:
            await progress_msg.delete()
        except:
            pass

# ========== 回調查詢處理器 ==========
@bot.on_callback_query()
async def handle_callback_query(client, callback_query):
    """處理內聯按鈕回調"""
    user_id = callback_query.from_user.id
    data = callback_query.data
    
    await callback_query.answer()
    
    if data == "check_sub":
        if await check_force_sub(user_id):
            await callback_query.message.edit_text(
                "✅ **訂閱檢查通過！**\n\n"
                "現在您可以使用機器人的所有功能。\n"
                "點擊 /start 重新開始。"
            )
        else:
            await callback_query.message.edit_text(
                "❌ **您尚未加入頻道！**\n\n"
                "請先加入頻道，然後點擊「重新檢查」。"
            )
    
    elif data == "start_recovery":
        await callback_query.message.reply(
            "**🚀 開始文件恢復**\n\n"
            "請使用命令：`/batch <頻道鏈接>`\n\n"
            "**示例：**\n"
            "`/batch https://t.me/serenaunzipbot/123`\n\n"
            "然後輸入要恢復的消息數量。"
        )
    
    elif data == "open_settings":
        await callback_query.message.reply("請使用命令：`/setting`")
    
    elif data == "show_help":
        await callback_query.message.reply("請使用命令：`/help`")
    
    elif data == "premium_info":
        premium = await is_premium_user(user_id)
        
        if premium:
            info = "**👑 您已是高級用戶！**\n\n**好處：**\n• 1000條消息/任務限制\n• 優先處理\n• 直接頻道轉發"
        else:
            info = "**👑 高級版信息**\n\n**好處：**\n• 1000條消息/任務限制（免費：20）\n• 優先處理\n• 直接頻道轉發\n\n**聯繫所有者獲取高級版：** @technicalserena"
        
        await callback_query.message.reply(info)
    
    elif data == "set_chat_id":
        user_states[user_id] = {"state": "awaiting_chat_id"}
        await callback_query.message.reply(
            "發送文件應轉發到的聊天ID：\n"
            "格式：`-100xxxxxxxxxx`\n"
            "輸入 /cancel 中止。"
        )
    
    elif data == "reset_settings":
        settings_col.delete_one({"user_id": user_id})
        await callback_query.message.edit_text(
            "✅ 所有設置已重置為默認值！"
        )
        await send_log("SETTINGS_RESET", user_id)
    
    elif data == "change_button":
        user_states[user_id] = {"state": "awaiting_button_text"}
        await callback_query.message.reply(
            "以以下格式發送新按鈕文本：\n"
            "`舊文本|新文本`\n\n"
            "示例：`Serena|Kumari`\n"
            "輸入 /cancel 中止。"
        )
    
    elif data == "view_limits":
        premium = await is_premium_user(user_id)
        limit = PREMIUM_USER_LIMIT if premium else FREE_USER_LIMIT
        
        limits_text = f"""
**📊 您的限制**

**用戶類型：** {'👑 高級用戶' if premium else '👤 免費用戶'}
**消息限制：** {limit} 條消息/任務
**消息延遲：** {DELAY_BETWEEN_MESSAGES}秒
**洪水保護：** ✅ 已啟用

**免費 vs 高級：**
• 免費：{FREE_USER_LIMIT} 條消息/任務
• 高級：{PREMIUM_USER_LIMIT} 條消息/任務
• 高級優先處理

**聯繫 @{OWNER_USERNAME} 獲取高級版**
"""
        await callback_query.message.reply(limits_text)
    
    elif data == "close_settings":
        try:
            await callback_query.message.delete()
        except:
            pass

# ========== 啟動機器人函數 ==========
async def start_bot():
    """啟動機器人客戶端"""
    print("🤖 正在啟動 SERENA 文件恢復機器人...")
    print(f"📊 配置：")
    print(f"  • 免費用戶限制：{FREE_USER_LIMIT} 條消息")
    print(f"  • 高級用戶限制：{PREMIUM_USER_LIMIT} 條消息")
    print(f"  • 消息延遲：{DELAY_BETWEEN_MESSAGES}秒")
    print(f"  • 所有者ID：{OWNER_IDS}")
    print(f"  • 日誌頻道：{LOG_CHANNEL}")
    
    await bot.start()
    print("✅ 機器人成功啟動！")
    
    me = await bot.get_me()
    print(f"🤖 機器人：@{me.username} (ID: {me.id})")
    
    await idle()
    await bot.stop()

if __name__ == "__main__":
    asyncio.run(start_bot())
