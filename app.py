# app.py
from flask import Flask, request
import threading
import asyncio
from bot_handlers import bot, start_bot

app = Flask(__name__)

# Global variable to track if bot is running
bot_running = False

@app.route('/')
def home():
    return "Bot is running on Render!"

@app.route('/webhook', methods=['POST'])
def webhook():
    # You can add a webhook endpoint here if needed later
    return 'OK', 200

def run_bot_in_thread():
    """Function to run the bot in a separate thread."""
    global bot_running
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(start_bot())
    except Exception as e:
        print(f"Bot stopped with error: {e}")
    finally:
        bot_running = False

if __name__ == "__main__":
    # Start the bot in a background thread when the Flask app starts
    if not bot_running:
        bot_running = True
        bot_thread = threading.Thread(target=run_bot_in_thread, daemon=True)
        bot_thread.start()
        print("Bot thread started.")
    
    # Run Flask app on all interfaces, port 10000 (as required by Render)
    app.run(host='0.0.0.0', port=10000, debug=False, use_reloader=False)
