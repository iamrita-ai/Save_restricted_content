 from flask import Flask, request
import logging
import os
import asyncio
import threading
import time

# Bot imports
from pyrogram import Client
import config

app = Flask(__name__)

# Global bot instance
bot = None

def run_bot():
    """Run the bot in a separate thread"""
    global bot
    
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    
    # Bot initialization
    bot = Client(
        "serena_bot",
        api_id=config.API_ID,
        api_hash=config.API_HASH,
        bot_token=config.BOT_TOKEN,
        workers=50
    )
    
    # Import handlers AFTER bot is created
    from bot_handlers import register_handlers
    register_handlers(bot)
    
    try:
        print("🤖 Starting Telegram Bot...")
        bot.start()
        print("✅ Bot started successfully!")
        
        # Get bot info
        me = loop.run_until_complete(bot.get_me())
        print(f"🤖 Bot Username: @{me.username}")
        print(f"🆔 Bot ID: {me.id}")
        
        # Keep the bot running
        loop.run_forever()
    except Exception as e:
        print(f"❌ Bot startup error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if bot:
            bot.stop()

# Start bot in background thread
def start_bot_background():
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    print("🚀 Bot thread started in background...")

# Root route - Render health check ke liye
@app.route('/')
def home():
    return """
    <!DOCTYPE html>
    <html>
    <head>
        <title>SERENA File Recovery Bot</title>
        <style>
            body { font-family: Arial, sans-serif; text-align: center; padding: 50px; }
            .status { color: green; font-weight: bold; }
        </style>
    </head>
    <body>
        <h1>🤖 SERENA File Recovery Bot</h1>
        <p class="status">✅ Bot is running!</p>
        <p>Flask Server + Telegram Bot</p>
        <p>Made with ❤️ by SERENA</p>
    </body>
    </html>
    """, 200

# Health check endpoint for Render
@app.route('/health')
def health():
    return {"status": "healthy", "bot_running": bot is not None}, 200

# Webhook endpoint (optional)
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        # Webhook logic here if needed
        return 'ok', 200
    return 'error', 403

if __name__ == '__main__':
    # Start bot in background
    start_bot_background()
    
    # Start Flask app
    port = int(os.environ.get('PORT', 8080))
    print(f"🌐 Starting Flask server on port {port}...")
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
