from flask import Flask, request, jsonify
from threading import Thread
import asyncio
from bot_handlers import bot
import logging
import sys
import os

app = Flask(__name__)

# Bot को background में run करने का function
def run_bot():
    """Bot को separate thread में run करता है"""
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        logging.info("Starting Telegram Bot...")
        bot.run()
        
    except Exception as e:
        logging.error(f"Bot startup failed: {e}")
        sys.exit(1)

# Flask app start होने पर bot launch करो
bot_started = False

def start_bot_on_app_start():
    """App startup पर bot start करता है"""
    global bot_started
    if not bot_started:
        try:
            logging.info("Launching bot in background thread...")
            bot_thread = Thread(target=run_bot, daemon=True)
            bot_thread.start()
            bot_started = True
            logging.info("Bot thread started successfully")
        except Exception as e:
            logging.error(f"Failed to start bot thread: {e}")

# App startup पर bot start करने के लिए
start_bot_on_app_start()

# Health check endpoint (Render के लिए जरूरी)
@app.route('/')
def home():
    return jsonify({
        "status": "online", 
        "service": "Telegram File Recovery Bot",
        "endpoints": ["/", "/health", "/webhook"]
    })

# Health check endpoint
@app.route('/health')
def health_check():
    return jsonify({
        "status": "healthy",
        "bot_started": bot_started,
        "message": "Bot is running"
    })

# Webhook endpoint (future use के लिए)
@app.route('/webhook', methods=['POST'])
def webhook():
    try:
        data = request.get_json()
        logging.info(f"Webhook received: {data}")
        return jsonify({"status": "received", "message": "Webhook processed"})
    except Exception as e:
        logging.error(f"Webhook error: {e}")
        return jsonify({"status": "error", "message": str(e)}), 400

# Error handlers
@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Endpoint not found"}), 404

@app.errorhandler(500)
def server_error(e):
    return jsonify({"error": "Internal server error"}), 500

# Render पोर्ट 10000 का इस्तेमाल करता है (Free tier)
if __name__ == "__main__":
    # Logging setup
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )
    
    # Port environment variable से लो करो (Render automatically सेट करता है)
    port = int(os.environ.get("PORT", 10000))
    
    app.run(host='0.0.0.0', port=port, debug=False)
