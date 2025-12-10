from flask import Flask, jsonify
import os
import logging
import sys

app = Flask(__name__)

# Simple logging setup
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

@app.route('/')
def home():
    return jsonify({
        "status": "online",
        "service": "Telegram File Recovery Bot",
        "message": "Bot is running as separate process"
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    # Bot को separate process के रूप में start करो
    import subprocess
    import threading
    
    def start_bot_process():
        """Bot को separate Python process के रूप में start करता है"""
        try:
            logger.info("Starting Telegram bot in separate process...")
            
            # bot_handlers.py को direct run करो
            bot_script = """
import asyncio
from bot_handlers import bot
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Bot starting...")
    await bot.start()
    logger.info("✅ Bot started successfully")
    await bot.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())
"""
            
            # Script को file में save करो और run करो
            with open("run_bot.py", "w") as f:
                f.write(bot_script)
            
            # Separate process start करो
            subprocess.Popen([sys.executable, "run_bot.py"])
            logger.info("Bot process started successfully")
            
        except Exception as e:
            logger.error(f"Failed to start bot process: {e}")
    
    # Bot process start करो
    bot_thread = threading.Thread(target=start_bot_process, daemon=True)
    bot_thread.start()
    
    # Flask app run करो
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)
