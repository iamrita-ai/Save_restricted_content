from flask import Flask, jsonify
import os
import logging
import sys
import subprocess
import signal
import atexit
import time

app = Flask(__name__)

# Logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.StreamHandler(sys.stderr)
    ]
)
logger = logging.getLogger(__name__)

# Global variable for bot process
bot_process = None
bot_script_path = "bot_runner.py"

# Bot runner script (separate file में create करेंगे)
bot_script = '''
import asyncio
import os
import sys
import logging

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - BOT - %(levelname)s - %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

async def run_bot():
    """Bot को run करता है"""
    try:
        from bot_handlers import bot
        
        # Check required environment variables
        required = ['API_ID', 'API_HASH', 'BOT_TOKEN', 'MONGO_URL']
        missing = [var for var in required if not os.environ.get(var)]
        
        if missing:
            logging.error(f"Missing environment variables: {missing}")
            return
        
        logging.info("Starting Telegram Bot...")
        
        # Bot start करो
        await bot.start()
        
        # Bot details log करो
        me = await bot.get_me()
        logging.info(f"✅ Bot started successfully!")
        logging.info(f"🤖 Bot Username: @{me.username}")
        logging.info(f"🆔 Bot ID: {me.id}")
        
        # Bot को running रखो
        await bot.run_until_disconnected()
        
    except Exception as e:
        logging.error(f"Bot error: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
    finally:
        try:
            await bot.stop()
            logging.info("Bot stopped")
        except:
            pass

if __name__ == "__main__":
    # Fix for asyncio event loop
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    try:
        # Run the bot
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}")
        import traceback
        logging.error(traceback.format_exc())
'''

def create_bot_script():
    """Bot runner script create करता है"""
    try:
        with open(bot_script_path, "w") as f:
            f.write(bot_script)
        logger.info(f"Created bot script: {bot_script_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to create bot script: {e}")
        return False

def start_bot():
    """Bot process start करता है"""
    global bot_process
    
    # पहले existing process को stop करो
    stop_bot()
    
    # Bot script create करो
    if not create_bot_script():
        return False
    
    try:
        logger.info("Starting bot process...")
        
        # Bot को separate process में run करो
        env = os.environ.copy()
        
        bot_process = subprocess.Popen(
            [sys.executable, bot_script_path],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Bot process output read करने के लिए thread start करो
        import threading
        
        def read_bot_output():
            while True:
                if bot_process is None:
                    break
                    
                line = bot_process.stdout.readline()
                if not line and bot_process.poll() is not None:
                    break
                
                if line:
                    # Bot logs को Flask logs में add करो
                    logger.info(f"🤖 {line.strip()}")
        
        output_thread = threading.Thread(target=read_bot_output, daemon=True)
        output_thread.start()
        
        # Bot startup check करो
        time.sleep(5)
        
        if bot_process.poll() is None:
            logger.info(f"✅ Bot process started (PID: {bot_process.pid})")
            return True
        else:
            logger.error("Bot process failed to start")
            return False
            
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def stop_bot():
    """Bot process stop करता है"""
    global bot_process
    
    if bot_process:
        logger.info(f"Stopping bot process (PID: {bot_process.pid})...")
        
        try:
            # Process को terminate करो
            bot_process.terminate()
            
            # Wait for process to end
            for _ in range(10):  # 10 seconds max
                if bot_process.poll() is not None:
                    break
                time.sleep(1)
            else:
                # Force kill if not terminated
                bot_process.kill()
                
            bot_process.wait()
            logger.info("Bot process stopped")
            
        except Exception as e:
            logger.error(f"Error stopping bot: {e}")
        
        bot_process = None
    
    # Bot script file delete करो
    try:
        if os.path.exists(bot_script_path):
            os.remove(bot_script_path)
    except:
        pass

def cleanup():
    """App shutdown पर cleanup करता है"""
    logger.info("Cleaning up...")
    stop_bot()

# Cleanup handlers register करो
atexit.register(cleanup)

# Flask routes
@app.route('/')
def home():
    bot_alive = bot_process and bot_process.poll() is None
    return jsonify({
        "status": "online",
        "service": "Telegram File Recovery Bot",
        "bot_status": "running" if bot_alive else "stopped",
        "bot_pid": bot_process.pid if bot_process else None,
        "endpoints": ["/", "/health", "/bot-status", "/start-bot", "/stop-bot"]
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "timestamp": time.time()
    })

@app.route('/bot-status')
def bot_status():
    if bot_process:
        return jsonify({
            "running": bot_process.poll() is None,
            "pid": bot_process.pid,
            "returncode": bot_process.poll()
        })
    return jsonify({"running": False})

@app.route('/start-bot')
def start_bot_endpoint():
    if start_bot():
        return jsonify({"success": True, "message": "Bot started"})
    return jsonify({"success": False, "message": "Failed to start bot"})

@app.route('/stop-bot')
def stop_bot_endpoint():
    stop_bot()
    return jsonify({"success": True, "message": "Bot stopped"})

# App initialization
def initialize():
    """App initialize होते ही bot start करता है"""
    logger.info("=" * 60)
    logger.info("🚀 Telegram File Recovery Bot Server")
    logger.info("=" * 60)
    
    # Environment variables check करो
    logger.info("Checking environment...")
    
    env_vars = {
        'API_ID': os.environ.get('API_ID'),
        'API_HASH': os.environ.get('API_HASH'),
        'BOT_TOKEN': os.environ.get('BOT_TOKEN'),
        'MONGO_URL': os.environ.get('MONGO_URL')
    }
    
    all_set = True
    for key, value in env_vars.items():
        if value:
            # Sensitive data mask करो
            if key in ['BOT_TOKEN', 'API_HASH', 'MONGO_URL']:
                display = value[:8] + "****" if len(value) > 12 else "***"
            else:
                display = value
            logger.info(f"✓ {key}: {display}")
        else:
            logger.error(f"✗ {key}: NOT SET")
            all_set = False
    
    if not all_set:
        logger.error("❌ Missing environment variables!")
    else:
        logger.info("✅ All environment variables are set")
    
    # Bot start करो
    logger.info("Starting bot in 3 seconds...")
    time.sleep(3)
    
    if start_bot():
        logger.info("✅ Bot startup initiated")
    else:
        logger.error("❌ Bot startup failed")

# Application entry point
if __name__ == "__main__":
    # Initialize and start bot
    initialize()
    
    # Flask app run करो
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting Flask server on port {port}")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        use_reloader=False
    )
else:
    # For WSGI (production)
    logger.info("WSGI server detected")
    
    # Bot start करो (delay के साथ)
    import threading
    def delayed_start():
        time.sleep(5)
        initialize()
    
    thread = threading.Thread(target=delayed_start, daemon=True)
    thread.start()
