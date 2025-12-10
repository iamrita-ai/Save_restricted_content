import asyncio
from pyrogram import Client
from config import Config
import time

async def send_message_with_delay(client, chat_id, message_id, target_chat_id, delay=Config.SLEEP_TIME):
    """एक message को forward करता है और specified delay लगाता है।"""
    try:
        await client.forward_messages(target_chat_id, chat_id, message_id)
        await asyncio.sleep(delay)
        return True
    except Exception as e:
        print(f"Error forwarding message {message_id}: {e}")
        return False

async def process_batch(client, chat_id, start_msg_id, count, target_chat_id, user_id, task_id):
    """Messages का batch process करता है और progress update करता है।"""
    from database import batch_tasks_collection
    successful = 0
    failed = 0
    
    for i in range(count):
        # अगर task cancel हुआ है तो loop break करो
        task = batch_tasks_collection.find_one({"_id": task_id})
        if task and task.get("status") == "cancelled":
            break
            
        msg_id = start_msg_id + i
        if await send_message_with_delay(client, chat_id, msg_id, target_chat_id):
            successful += 1
        else:
            failed += 1
            
        # हर 50 messages के बाद database में progress update करो
        if i % 50 == 0:
            batch_tasks_collection.update_one(
                {"_id": task_id},
                {"$set": {"progress": i+1, "successful": successful, "failed": failed}}
            )
    
    # Task complete, final status update करो
    batch_tasks_collection.update_one(
        {"_id": task_id},
        {"$set": {"status": "completed", "progress": count, "successful": successful, "failed": failed}}
    )
    return successful, failed

async def send_log_to_channel(bot, message, log_type="INFO"):
    """Logs channel में message भेजता है।"""
    try:
        log_text = f"**{log_type}**\n{message}"
        await bot.send_message(Config.LOG_CHANNEL, log_text)
    except Exception as e:
        print(f"Failed to send log: {e}")
