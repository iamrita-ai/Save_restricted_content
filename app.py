# app.py - 修復端口綁定問題
from flask import Flask, request, jsonify
import threading
import asyncio
import os
import sys

# 添加當前目錄到PATH
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

app = Flask(__name__)

# 全局變量
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
    """在新的線程中運行機器人"""
    try:
        from bot_handlers import start_bot
        asyncio.run(start_bot())
    except Exception as e:
        print(f"Bot error: {e}")
        import traceback
        traceback.print_exc()

@app.before_first_request
def initialize():
    """在第一次請求時初始化機器人"""
    global bot_running, bot_thread
    
    if not bot_running:
        print("Starting bot in background thread...")
        bot_running = True
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        print("Bot thread started successfully")

if __name__ == "__main__":
    # 初始化機器人
    initialize()
    
    # 啟動Flask應用，指定端口10000
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port, debug=False, threaded=True)
