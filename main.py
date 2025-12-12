from flask import Flask, jsonify
import os
import logging
import sys
import threading
import time
import asyncio

app = Flask(__name__)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables
bot_running = False

def run_bot_async():
    """Run bot with proper event loop handling"""
    try:
        # Create new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Now import and run bot
        from bot_handlers import main as bot_main
        
        logger.info("🤖 Starting Telegram Bot...")
        
        # Run the bot
        loop.run_until_complete(bot_main())
        
    except Exception as e:
        logger.error(f"❌ Bot failed: {e}")
        import traceback
        logger.error(traceback.format_exc())

def start_bot():
    """Start bot in background thread"""
    global bot_running
    
    try:
        # Run bot in separate thread
        bot_thread = threading.Thread(target=run_bot_async, daemon=True)
        bot_thread.start()
        
        # Wait and check
        time.sleep(5)
        bot_running = True
        logger.info("✅ Bot started successfully!")
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot thread: {e}")

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
    start_bot()
    return jsonify({"message": "Bot start requested"})

if __name__ == "__main__":
    # Log startup info
    logger.info("=" * 60)
    logger.info("🚀 TELEGRAM FILE RECOVERY BOT v2.0")
    logger.info("=" * 60)
    
    # Check environment variables
    env_vars = ['API_ID', 'API_HASH', 'BOT_TOKEN', 'MONGO_URL']
    
    all_set = True
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            if var in ['BOT_TOKEN', 'API_HASH', 'MONGO_URL']:
                masked = value[:8] + "..." + value[-4:] if len(value) > 12 else "***"
                logger.info(f"✓ {var}: {masked}")
            else:
                logger.info(f"✓ {var}: {value}")
        else:
            logger.error(f"✗ {var}: NOT SET")
            all_set = False
    
    if all_set:
        # Start bot
        logger.info("Starting bot in 3 seconds...")
        time.sleep(3)
        start_bot()
    else:
        logger.error("❌ Missing required environment variables!")
    
    # Start Flask server
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting Flask server on port {port}")
    
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
