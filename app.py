# app.py - Fixed port binding issue
from flask import Flask, request, jsonify
import threading
import asyncio
import os
import sys

# Add current directory to PATH
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)

# Global variables
bot_running = False
bot_thread = None

@app.route('/')
def home():
    return jsonify({
        "status": "running",
        "service": "Serena File Recovery Bot",
        "port": 10000
    })

@app.route('/health')
def health():
    return jsonify({"status": "healthy"}), 200

def run_bot():
    """Run bot in a new thread"""
    try:
        from bot_handlers import start_bot
        asyncio.run(start_bot())
    except Exception as e:
        print(f"Bot error: {e}")
        import traceback
        traceback.print_exc()

@app.before_first_request
def initialize():
    """Initialize bot on first request"""
    global bot_running, bot_thread
    
    if not bot_running:
        print("Starting bot in background thread...")
        bot_running = True
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        print("Bot thread started successfully")

if __name__ == "__main__":
    # Initialize bot
    initialize()
    
    # Start Flask app on port 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
