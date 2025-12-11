from flask import Flask, jsonify
import os

app = Flask(__name__)

@app.route('/')
def home():
    return jsonify({"status": "Bot is running as background process"})

@app.route('/health')
def health():
    return jsonify({"status": "ok"})

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    
    # Bot को direct import और run करो
    import asyncio
    import threading
    
    def run_bot():
        import asyncio
        from bot_handlers import bot
        
        async def start():
            await bot.start()
            print("✅ Bot started successfully!")
            await bot.run_until_disconnected()
        
        asyncio.run(start())
    
    # Bot को background thread में start करो
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    
    app.run(host='0.0.0.0', port=port, debug=False)
