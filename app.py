from flask import Flask, request
import logging
import os
from bot_handlers import bot

app = Flask(__name__)

# Root route - Render health check ke liye
@app.route('/')
def home():
    return "✅ Serena File Recovery Bot is running!", 200

# Webhook route (Agar aap webhook use karna chaahen)
@app.route('/webhook', methods=['POST'])
def webhook():
    if request.headers.get('content-type') == 'application/json':
        update = request.get_json()
        bot.process_new_updates([update])
        return 'ok', 200
    return 'error', 403

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8080))  # Render apne aap PORT set karta hai
    app.run(host='0.0.0.0', port=port, debug=False)
