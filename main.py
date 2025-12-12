from flask import Flask, jsonify
import os
import logging
import sys
import subprocess
import signal
import atexit
import time
import threading

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

def create_bot_script():
    """Create the bot runner script with correct Pyrogram v2 syntax"""
    bot_script = '''import asyncio
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
    """Main bot runner function"""
    try:
        # Import inside function to avoid circular imports
        sys.path.append(os.path.dirname(os.path.abspath(__file__)))
        from bot_handlers import bot
        
        # Check required environment variables
        required = ['API_ID', 'API_HASH', 'BOT_TOKEN', 'MONGO_URL']
        missing = [var for var in required if not os.environ.get(var)]
        
        if missing:
            logging.error(f"Missing environment variables: {missing}")
            return
        
        logging.info("Starting Telegram Bot...")
        
        # Start the bot
        await bot.start()
        
        # Get bot info
        me = await bot.get_me()
        logging.info(f"✅ Bot started successfully!")
        logging.info(f"🤖 Bot Username: @{me.username}")
        logging.info(f"🆔 Bot ID: {me.id}")
        
        # Keep the bot running (Pyrogram v2 uses idle())
        from pyrogram import idle
        await idle()
        
    except KeyboardInterrupt:
        logging.info("Bot stopped by user")
    except Exception as e:
        logging.error(f"Bot error: {str(e)}")
        import traceback
        logging.error(traceback.format_exc())
    finally:
        try:
            await bot.stop()
            logging.info("Bot stopped gracefully")
        except:
            pass

if __name__ == "__main__":
    # Set event loop policy for Windows compatibility
    if sys.platform == "win32":
        asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
    
    # Run the bot
    try:
        asyncio.run(run_bot())
    except KeyboardInterrupt:
        logging.info("Bot process terminated")
    except Exception as e:
        logging.error(f"Fatal error in bot process: {e}")
'''
    
    try:
        with open("bot_runner.py", "w") as f:
            f.write(bot_script)
        logger.info("Created bot runner script")
        return True
    except Exception as e:
        logger.error(f"Failed to create bot script: {e}")
        return False

def start_bot():
    """Start the bot in a separate process"""
    global bot_process
    
    # Stop existing bot process if running
    stop_bot()
    
    # Create the bot runner script
    if not create_bot_script():
        return False
    
    try:
        logger.info("Starting bot process...")
        
        # Start bot in separate process
        env = os.environ.copy()
        bot_process = subprocess.Popen(
            [sys.executable, "bot_runner.py"],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
            universal_newlines=True
        )
        
        # Function to read bot output
        def read_output():
            while True:
                if bot_process is None:
                    break
                
                line = bot_process.stdout.readline()
                if not line and bot_process.poll() is not None:
                    break
                
                if line:
                    # Clean the line and log it
                    clean_line = line.strip()
                    if clean_line:
                        logger.info(f"🤖 {clean_line}")
        
        # Start output reader thread
        output_thread = threading.Thread(target=read_output, daemon=True)
        output_thread.start()
        
        # Wait for bot to start
        time.sleep(3)
        
        if bot_process.poll() is None:
            logger.info(f"✅ Bot process started successfully (PID: {bot_process.pid})")
            return True
        else:
            logger.error("❌ Bot process failed to start")
            return False
            
    except Exception as e:
        logger.error(f"Failed to start bot process: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False

def stop_bot():
    """Stop the bot process"""
    global bot_process
    
    if bot_process:
        logger.info(f"Stopping bot process (PID: {bot_process.pid})...")
        
        try:
            # Send SIGTERM
            bot_process.terminate()
            
            # Wait for process to terminate
            for _ in range(10):
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
    
    # Clean up bot runner file
    try:
        if os.path.exists("bot_runner.py"):
            os.remove("bot_runner.py")
            logger.debug("Cleaned up bot runner script")
    except:
        pass

def cleanup():
    """Cleanup on exit"""
    logger.info("Shutting down...")
    stop_bot()

# Register cleanup
atexit.register(cleanup)

# Flask routes
@app.route('/')
def home():
    bot_status = "running" if bot_process and bot_process.poll() is None else "stopped"
    return jsonify({
        "status": "online",
        "service": "Telegram File Recovery Bot",
        "bot_status": bot_status,
        "endpoints": ["/", "/health", "/bot-status", "/restart-bot"]
    })

@app.route('/health')
def health():
    return jsonify({
        "status": "healthy",
        "bot_alive": bot_process is not None and bot_process.poll() is None,
        "timestamp": time.time()
    })

@app.route('/bot-status')
def bot_status():
    if bot_process:
        return jsonify({
            "pid": bot_process.pid,
            "alive": bot_process.poll() is None,
            "return_code": bot_process.poll()
        })
    return jsonify({"status": "not_running"})

@app.route('/restart-bot')
def restart_bot():
    stop_bot()
    time.sleep(2)
    if start_bot():
        return jsonify({"success": True, "message": "Bot restarted"})
    return jsonify({"success": False, "message": "Failed to restart bot"})

# Initialize bot on startup
def initialize():
    """Initialize the application"""
    logger.info("=" * 60)
    logger.info("🚀 Telegram File Recovery Bot Server")
    logger.info("=" * 60)
    
    # Check environment variables
    logger.info("Checking environment variables...")
    
    env_vars = {
        'API_ID': os.environ.get('API_ID'),
        'API_HASH': os.environ.get('API_HASH'),
        'BOT_TOKEN': os.environ.get('BOT_TOKEN'),
        'MONGO_URL': os.environ.get('MONGO_URL')
    }
    
    all_set = True
    for key, value in env_vars.items():
        if value:
            # Mask sensitive data
            if key in ['BOT_TOKEN', 'API_HASH', 'MONGO_URL']:
                display = value[:10] + "..." if len(value) > 15 else "***"
            else:
                display = value
            logger.info(f"✓ {key}: {display}")
        else:
            logger.error(f"✗ {key}: NOT SET")
            all_set = False
    
    if not all_set:
        logger.error("❌ Missing required environment variables!")
        return False
    
    logger.info("✅ All environment variables are set")
    
    # Start the bot
    logger.info("Starting bot in 2 seconds...")
    time.sleep(2)
    
    return start_bot()

# App initialization
if __name__ == "__main__":
    # Initialize and start bot
    if initialize():
        logger.info("✅ Bot startup initiated successfully")
    else:
        logger.error("❌ Bot initialization failed")
    
    # Start Flask app
    port = int(os.environ.get("PORT", 10000))
    logger.info(f"Starting Flask server on port {port}")
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        use_reloader=False
    )
else:
    # For WSGI servers (production)
    logger.info("WSGI server detected")
    
    # Start bot in background thread
    def delayed_start():
        time.sleep(5)
        initialize()
    
    bot_thread = threading.Thread(target=delayed_start, daemon=True)
    bot_thread.start()
