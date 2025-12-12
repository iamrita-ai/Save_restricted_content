# app.py - Fixed Flask 2.3+ compatibility
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
        "port": 10000,
        "flask_version": "2.3+ compatible"
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

def start_bot_thread():
    """Start bot thread on app startup"""
    global bot_running, bot_thread
    
    if not bot_running:
        print("Starting bot in background thread...")
        bot_running = True
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        print("Bot thread started successfully")

# Start bot thread when app starts (Flask 2.3+ compatible)
with app.app_context():
    start_bot_thread()

if __name__ == "__main__":
    # Start bot thread if not already started
    if not bot_running:
        start_bot_thread()
    
    # Start Flask app on port 10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
