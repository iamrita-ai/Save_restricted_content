import asyncio
import logging
from pyrogram import Client, filters, idle
from pyrogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Bot configuration
API_ID = 123456  # Change this to your API_ID
API_HASH = "your_api_hash_here"  # Change this
BOT_TOKEN = "your_bot_token_here"  # Change this

# Initialize bot
bot = Client(
    "test_bot",
    api_id=API_ID,
    api_hash=API_HASH,
    bot_token=BOT_TOKEN
)

@bot.on_message(filters.command("start") & filters.private)
async def start_command(client, message):
    await message.reply_text(
        "✅ **Bot is working!**\n\n"
        "This is a test bot.\n"
        "Send /help for commands."
    )

@bot.on_message(filters.command("help") & filters.private)
async def help_command(client, message):
    await message.reply_text(
        "📋 **Available Commands:**\n"
        "/start - Start bot\n"
        "/help - Show this help\n"
        "/test - Test response"
    )

@bot.on_message(filters.command("test") & filters.private)
async def test_command(client, message):
    await message.reply_text("✅ Bot is responding correctly!")

async def main():
    logger.info("Starting bot...")
    await bot.start()
    
    me = await bot.get_me()
    logger.info(f"✅ Bot started: @{me.username}")
    
    await idle()

if __name__ == "__main__":
    asyncio.run(main())
