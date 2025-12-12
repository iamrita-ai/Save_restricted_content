from flask import Flask, jsonify
import os
import logging
import sys
import asyncio
import threading
import time

app = Flask(__name__)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variable to track bot status
bot_running = False
bot_task = None

def run_bot():
    """Run the bot"""
    global bot_running
    
    try:
        # Import inside function to avoid circular imports
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        
        # Check environment variables first
        required_vars = ['API_ID', 'API_HASH', 'BOT_TOKEN', 'MONGO_URL']
        missing_vars = []
        
        for var in required_vars:
            if not os.environ.get(var):
                missing_vars.append(var)
        
        if missing_vars:
            logger.error(f"Missing environment variables: {missing_vars}")
            return
        
        # Now import bot
        from bot_handlers import bot
        
        logger.info("🤖 Starting Telegram Bot...")
        
        # Create event loop
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Start bot
        loop.run_until_complete(bot.start())
        
        # Get bot info
        me = loop.run_until_complete(bot.get_me())
        logger.info("✅ Bot started successfully!")
        logger.info(f"🤖 Username: @{me.username}")
        logger.info(f"🆔 ID: {me.id}")
        
        bot_running = True
        
        # Keep bot running
        from pyrogram import idle
        loop.run_until_complete(idle())
        
    except Exception as e:
        logger.error(f"❌ Bot startup failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        bot_running = False

def start_bot():
    """Start bot in background thread"""
    global bot_task
    
    if bot_task and bot_task.is_alive():
        logger.warning("Bot is already running")
        return
    
    try:
        bot_task = threading.Thread(target=run_bot, daemon=True)
        bot_task.start()
        
        # Wait for bot to start
        for i in range(10):
            if bot_running:
                logger.info("✅ Bot is running")
                break
            time.sleep(1)
            if i == 5:
                logger.info("Still starting bot...")
        
        if not bot_running:
            logger.warning("⚠️ Bot may not have started properly")
            
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "bot": "running" if bot_running else "starting",
        "service": "Telegram File Recovery Bot",
        "endpoints": ["/", "/health", "/start-bot", "/bot-status"]
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
    start_bot()
    return jsonify({
        "message": "Bot start requested",
        "bot_running": bot_running
    })

@app.route('/bot-status')
def bot_status():
    return jsonify({
        "running": bot_running,
        "thread_alive": bot_task.is_alive() if bot_task else False
    })

if __name__ == "__main__":
    # Log startup info
    logger.info("=" * 60)
    logger.info("🚀 Starting Telegram File Recovery Bot Server")
    logger.info("=" * 60)
    
    # Check environment variables
    logger.info("Checking environment variables...")
    
    env_vars = ['API_ID', 'API_HASH', 'BOT_TOKEN', 'MONGO_URL']
    
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            # Mask sensitive values
            if var in ['BOT_TOKEN', 'API_HASH', 'MONGO_URL']:
                masked = value[:8] + "..." + value[-4:] if len(value) > 15 else "***"
                logger.info(f"✓ {var}: {masked}")
            else:
                logger.info(f"✓ {var}: {value}")
        else:
            logger.error(f"✗ {var}: NOT SET")
    
    # Start bot
    logger.info("Starting bot in 2 seconds...")
    time.sleep(2)
    
    start_bot()
    
    # Start Flask app
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting Flask server on port {port}")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        use_reloader=False
    )
