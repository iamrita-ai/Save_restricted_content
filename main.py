from flask import Flask, jsonify
import os
import logging
import sys
import threading
import time

app = Flask(__name__)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables
bot_running = False

def start_bot():
    """Start Telegram bot"""
    global bot_running
    
    try:
        logger.info("🚀 Initializing Telegram Bot...")
        
        # Import bot handlers
        from bot_handlers import bot
        
        logger.info("Starting bot...")
        
        # Run bot
        import asyncio
        
        async def run():
            await bot.start()
            logger.info("✅ Bot started successfully!")
            
            # Get bot info
            me = await bot.get_me()
            logger.info(f"🤖 Username: @{me.username}")
            logger.info(f"🆔 ID: {me.id}")
            
            # Send startup log
            from bot_handlers import send_log_to_channel
            try:
                await send_log_to_channel(
                    bot,
                    f"🚀 Bot Started!\nUsername: @{me.username}\nID: {me.id}",
                    "STARTUP"
                )
            except:
                pass
            
            bot_running = True
            
            # Keep bot running
            from pyrogram import idle
            await idle()
        
        # Run bot
        asyncio.run(run())
        
    except Exception as e:
        logger.error(f"❌ Bot failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        bot_running = False

def run_bot_in_thread():
    """Run bot in separate thread"""
    bot_thread = threading.Thread(target=start_bot, daemon=True)
    bot_thread.start()

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "Telegram File Recovery Bot",
        "bot": "running" if bot_running else "starting",
        "version": "2.0"
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "bot_running": bot_running,
        "timestamp": time.time()
    })

@app.route('/start-bot')
def start_bot_endpoint():
    """Manually start bot"""
    run_bot_in_thread()
    return jsonify({"message": "Bot start requested"})

if __name__ == "__main__":
    # Log startup info
    logger.info("=" * 60)
    logger.info("🚀 TELEGRAM FILE RECOVERY BOT v2.0")
    logger.info("=" * 60)
    
    # Check environment
    env_vars = ['API_ID', 'API_HASH', 'BOT_TOKEN']
    
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            if var in ['BOT_TOKEN', 'API_HASH']:
                masked = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
                logger.info(f"✓ {var}: {masked}")
            else:
                logger.info(f"✓ {var}: {value}")
        else:
            logger.error(f"✗ {var}: NOT SET")
    
    # Start bot
    logger.info("Starting bot in 3 seconds...")
    time.sleep(3)
    run_bot_in_thread()
    
    # Start Flask
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting Flask server on port {port}")
    
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
