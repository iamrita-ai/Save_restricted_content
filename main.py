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

def run_bot():
    """Run the bot in a separate thread"""
    global bot_running
    
    try:
        # Import bot inside the function
        from bot_handlers import bot
        
        logger.info("🤖 Starting Telegram Bot...")
        
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Start the bot
        loop.run_until_complete(bot.start())
        
        # Get bot info
        me = loop.run_until_complete(bot.get_me())
        logger.info(f"✅ Bot started successfully!")
        logger.info(f"🤖 Username: @{me.username}")
        logger.info(f"🆔 ID: {me.id}")
        
        bot_running = True
        
        # Keep bot running
        loop.run_forever()
        
    except Exception as e:
        logger.error(f"❌ Bot startup failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
        bot_running = False

def start_bot_thread():
    """Start bot in background thread"""
    try:
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        
        # Wait a bit for bot to initialize
        time.sleep(5)
        
        if bot_running:
            logger.info("✅ Bot thread started successfully")
        else:
            logger.warning("⚠️ Bot may not have started properly")
            
    except Exception as e:
        logger.error(f"Failed to start bot thread: {e}")

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "bot": "running" if bot_running else "not_running",
        "service": "Telegram File Recovery Bot"
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "bot_running": bot_running,
        "timestamp": time.time()
    })

@app.route('/start-bot')
def start_bot():
    """Manually start bot endpoint"""
    start_bot_thread()
    return jsonify({"message": "Bot start requested"})

if __name__ == "__main__":
    # Log startup info
    logger.info("=" * 60)
    logger.info("🚀 Starting Telegram File Recovery Bot Server")
    logger.info("=" * 60)
    
    # Check environment variables
    logger.info("Checking environment...")
    
    # List of required variables
    required_vars = ['API_ID', 'API_HASH', 'BOT_TOKEN', 'MONGO_URL']
    
    for var in required_vars:
        value = os.environ.get(var)
        if value:
            # Mask sensitive values
            if var in ['BOT_TOKEN', 'API_HASH', 'MONGO_URL']:
                display = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
            else:
                display = value
            logger.info(f"✓ {var}: {display}")
        else:
            logger.error(f"✗ {var}: NOT SET")
    
    # Start bot
    logger.info("Starting bot in 3 seconds...")
    time.sleep(3)
    start_bot_thread()
    
    # Start Flask app
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting Flask server on port {port}")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        use_reloader=False
    )
