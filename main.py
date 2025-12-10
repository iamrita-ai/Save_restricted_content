from flask import Flask, request, jsonify
import threading
import asyncio
from bot_handlers import bot
import logging
import sys
import os
import time

app = Flask(__name__)

# Global variables
bot_thread = None
bot_running = False
loop = None

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

def run_bot_in_thread():
    """Bot को separate thread में run करता है"""
    global bot_running, loop
    
    try:
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        logger.info("Starting Telegram Bot...")
        
        # Bot start करो
        bot.start()
        bot_running = True
        logger.info("✅ Bot started successfully")
        
        # Bot को running रखो
        idle = asyncio.ensure_future(bot.idle())
        loop.run_until_complete(idle)
        
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
    except Exception as e:
        logger.error(f"❌ Bot startup failed: {e}")
        import traceback
        logger.error(traceback.format_exc())
    finally:
        bot_running = False
        if loop and not loop.is_closed():
            loop.stop()
            loop.close()
        logger.info("Bot thread terminated")

def start_bot():
    """Bot thread start करता है"""
    global bot_thread
    
    if bot_thread and bot_thread.is_alive():
        logger.warning("Bot is already running")
        return
    
    try:
        bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
        bot_thread.start()
        
        # Wait for bot to initialize
        timeout = 30
        start_time = time.time()
        
        while not bot_running and time.time() - start_time < timeout:
            time.sleep(1)
            logger.info("Waiting for bot to start...")
        
        if bot_running:
            logger.info("✅ Bot thread started successfully")
        else:
            logger.warning("Bot startup timed out")
            
    except Exception as e:
        logger.error(f"Failed to start bot thread: {e}")
        import traceback
        logger.error(traceback.format_exc())

def stop_bot():
    """Bot stop करता है"""
    global bot_running
    
    if loop and not loop.is_closed():
        loop.call_soon_threadsafe(loop.stop)
    
    bot_running = False
    logger.info("Bot stop requested")

# Flask routes
@app.route('/')
def home():
    return jsonify({
        "status": "online", 
        "service": "Telegram File Recovery Bot",
        "bot_status": "running" if bot_running else "stopped",
        "endpoints": ["/", "/health", "/start-bot", "/stop-bot", "/webhook"]
    })

@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "bot_running": bot_running,
        "timestamp": time.time()
    })

@app.route('/start-bot')
def start_bot_endpoint():
    """Bot manually start करने के लिए endpoint"""
    start_bot()
    return jsonify({
        "message": "Bot start requested",
        "bot_running": bot_running
    })

@app.route('/stop-bot')
def stop_bot_endpoint():
    """Bot manually stop करने के लिए endpoint"""
    stop_bot()
    return jsonify({
        "message": "Bot stop requested",
        "bot_running": bot_running
    })

@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logger.info(f"Webhook received: {data}")
        return jsonify({"status": "received", "message": "Webhook processed"})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500

# Application startup
@app.before_first_request
def initialize():
    """First request से पहले bot start करो"""
    logger.info("Initializing application...")
    
    # Bot start करो (delay के साथ)
    threading.Timer(5.0, start_bot).start()
    logger.info("Bot startup scheduled in 5 seconds...")

# Render के लिए port configuration
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    logger.info(f"Starting Flask app on port {port}")
    logger.info(f"Environment: API_ID={os.environ.get('API_ID', 'Not set')}")
    logger.info(f"Bot Token present: {'Yes' if os.environ.get('BOT_TOKEN') else 'No'}")
    logger.info(f"Mongo URL present: {'Yes' if os.environ.get('MONGO_URL') else 'No'}")
    
    # Production में debug mode off रखो
    debug_mode = os.environ.get("DEBUG", "false").lower() == "true"
    
    app.run(
        host='0.0.0.0', 
        port=port, 
        debug=debug_mode,
        use_reloader=False  # Reloader multiple threads create कर सकता है
    )
