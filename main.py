from flask import Flask, jsonify
import os
import logging
import sys
import threading
import subprocess
import atexit

app = Flask(__name__)

# Simple logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Global variables
bot_process = None

def start_bot():
    """Bot को separate process में start करता है"""
    global bot_process
    
    try:
        logger.info("Starting Telegram bot in separate process...")
        
        # Bot run करने के लिए script content
        bot_script_content = """
import asyncio
import sys
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from bot_handlers import bot
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

async def main():
    logging.info("🤖 Telegram File Recovery Bot Starting...")
    
    # Check environment variables
    required_vars = ['API_ID', 'API_HASH', 'BOT_TOKEN', 'MONGO_URL']
    missing_vars = [var for var in required_vars if not os.environ.get(var)]
    
    if missing_vars:
        logging.error(f"Missing environment variables: {missing_vars}")
        return
    
    logging.info(f"API_ID: {os.environ.get('API_ID')[:3]}***")
    logging.info(f"BOT_TOKEN present: {'Yes' if os.environ.get('BOT_TOKEN') else 'No'}")
    
    try:
        await bot.start()
        logging.info("✅ Bot started successfully!")
        logging.info(f"Bot username: @{(await bot.get_me()).username}")
        
        # Keep bot running
        await bot.run_until_disconnected()
        
    except Exception as e:
        logging.error(f"Bot startup failed: {e}")
        import traceback
        logging.error(traceback.format_exc())
    finally:
        await bot.stop()
        logging.info("Bot stopped")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Unexpected error: {e}")
        import traceback
        logging.error(traceback.format_exc())
"""
        
        # Script को temporary file में save करो
        with open("run_bot.py", "w") as f:
            f.write(bot_script_content)
        
        # Separate process start करो
        env = os.environ.copy()
        bot_process = subprocess.Popen(
            [sys.executable, "run_bot.py"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True
        )
        
        # Bot process के output को real-time log करो
        def log_bot_output():
            while True:
                output = bot_process.stdout.readline()
                if output == '' and bot_process.poll() is not None:
                    break
                if output:
                    logger.info(f"🤖 BOT: {output.strip()}")
        
        # Output logging thread start करो
        output_thread = threading.Thread(target=log_bot_output, daemon=True)
        output_thread.start()
        
        logger.info(f"✅ Bot process started with PID: {bot_process.pid}")
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot process: {e}")
        import traceback
        logger.error(traceback.format_exc())

def stop_bot():
    """Bot process stop करता है"""
    global bot_process
    
    if bot_process:
        logger.info(f"Stopping bot process (PID: {bot_process.pid})...")
        bot_process.terminate()
        try:
            bot_process.wait(timeout=10)
            logger.info("Bot process stopped")
        except subprocess.TimeoutExpired:
            logger.warning("Bot process didn't stop gracefully, forcing...")
            bot_process.kill()
        bot_process = None

def cleanup():
    """App shutdown पर cleanup करता है"""
    logger.info("Cleaning up...")
    stop_bot()
    
    # Temporary file delete करो
    try:
        if os.path.exists("run_bot.py"):
            os.remove("run_bot.py")
            logger.info("Cleaned up temporary files")
    except:
        pass

# App shutdown पर cleanup register करो
atexit.register(cleanup)

# Flask routes
@app.route('/')
def home():
    return jsonify({
        "status": "online", 
        "service": "Telegram File Recovery Bot",
        "bot_status": "running" if bot_process and bot_process.poll() is None else "stopped",
        "pid": bot_process.pid if bot_process else None,
        "endpoints": ["/", "/health", "/status", "/restart-bot"]
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "bot_alive": bot_process is not None and bot_process.poll() is None,
        "timestamp": os.times().user
    })

@app.route('/status')
def status():
    if bot_process:
        return jsonify({
            "bot": {
                "pid": bot_process.pid,
                "alive": bot_process.poll() is None,
                "returncode": bot_process.poll()
            }
        })
    return jsonify({"bot": "not_running"})

@app.route('/restart-bot')
def restart_bot():
    stop_bot()
    time.sleep(2)
    start_bot()
    return jsonify({"message": "Bot restart initiated"})

# Render के लिए main execution
if __name__ == "__main__":
    # Environment variables log करो (masked)
    logger.info("=" * 50)
    logger.info("🚀 Starting File Recovery Bot Server")
    logger.info("=" * 50)
    
    # Environment check
    env_vars = ['API_ID', 'API_HASH', 'BOT_TOKEN', 'MONGO_URL']
    for var in env_vars:
        value = os.environ.get(var)
        if value:
            # Sensitive data mask करो
            if var in ['BOT_TOKEN', 'API_HASH', 'MONGO_URL']:
                masked = value[:10] + "..." + value[-5:] if len(value) > 15 else "***"
                logger.info(f"{var}: {masked}")
            else:
                logger.info(f"{var}: {value}")
        else:
            logger.warning(f"⚠️  {var} is not set")
    
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Port: {port}")
    
    # Bot start करो (delay के साथ)
    logger.info("Starting bot in 3 seconds...")
    import time
    time.sleep(3)
    
    start_bot()
    
    # Flask app run करो
    logger.info(f"Starting Flask server on port {port}")
    app.run(
        host='0.0.0.0', 
        port=port, 
        debug=False, 
        use_reloader=False
    )
else:
    # WSGI server के लिए (production)
    # App load होने पर bot start करो
    logger.info("WSGI server detected, starting bot...")
    
    # Background thread में bot start करो
    def delayed_bot_start():
        import time
        time.sleep(5)
        start_bot()
    
    bot_thread = threading.Thread(target=delayed_bot_start, daemon=True)
    bot_thread.start()
    logger.info("Bot startup scheduled in background thread")
