from flask import Flask, request, jsonify
from threading import Thread
import asyncio
from bot_handlers import bot
import logging

app = Flask(__name__)

# Bot को background में run करने के लिए function
def run_bot():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    bot.run()

# Flask server start होते ही bot launch करो
@app.before_first_request
def launch_bot():
    bot_thread = Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logging.info("Telegram Bot started in background thread.")

# Health check endpoint (Render के लिए जरूरी)
@app.route('/')
def home():
    return jsonify({"status": "online", "service": "Telegram File Recovery Bot"})

# Webhook endpoint (आगे के लिए reserved)
@app.route('/webhook', methods=['POST'])
def webhook():
    # Future webhook implementations के लिए
    return jsonify({"status": "ok"})

# Render पोर्ट 10000 का इस्तेमाल करता है
if __name__ == "__main__":
    app.run(host='0.0.0.0', port=10000, debug=False)
