import asyncio
import logging
from config import Config
from pyrogram.errors import FloodWait

logger = logging.getLogger(__name__)

async def send_message_with_delay(client, chat_id, message_id, target_chat_id, delay=Config.SLEEP_TIME):
    """Forward message with delay to avoid flood"""
    try:
        await client.forward_messages(target_chat_id, chat_id, message_id)
        await asyncio.sleep(delay)
        return True, None
    except FloodWait as e:
        wait_time = e.value
        logger.warning(f"Flood wait: {wait_time} seconds")
        await asyncio.sleep(wait_time)
        return False, f"Flood wait: {wait_time}s"
    except Exception as e:
        logger.error(f"Forward error: {e}")
        return False, str(e)

async def process_batch_messages(user_client, user_id, chat_id, start_msg_id, count, target_chat_id, task_id, update_callback=None):
    """Process batch of messages"""
    from database import update_task_status
    import time
    
    successful = 0
    failed = 0
    errors = []
    
    logger.info(f"Processing batch: {count} messages from {start_msg_id}")
    
    for i in range(count):
        current_msg_id = start_msg_id + i
        
        # Check if task is cancelled
        from database import batch_tasks_collection
        task = batch_tasks_collection.find_one({"_id": task_id})
        if task and task.get("status") == "cancelled":
            logger.info(f"Task {task_id} cancelled by user")
            break
        
        try:
            success, error = await send_message_with_delay(
                user_client, chat_id, current_msg_id, target_chat_id
            )
            
            if success:
                successful += 1
            else:
                failed += 1
                if error:
                    errors.append(f"Msg {current_msg_id}: {error[:50]}")
            
            # Update progress every 10 messages or last message
            if (i + 1) % 10 == 0 or i == count - 1:
                update_task_status(task_id, "processing", i + 1, successful, failed)
                
                if update_callback:
                    await update_callback(user_id, i + 1, count, successful, failed)
            
        except Exception as e:
            failed += 1
            errors.append(f"Msg {current_msg_id}: {str(e)[:50]}")
            logger.error(f"Error processing message {current_msg_id}: {e}")
    
    # Final update
    final_status = "completed" if successful > 0 else "failed"
    update_task_status(task_id, final_status, count, successful, failed)
    
    return successful, failed, errors

async def send_log_to_channel(bot, message, log_type="INFO", user_id=None):
    """Send log to log channel"""
    try:
        log_text = f"**{log_type}**\n"
        if user_id:
            log_text += f"User: `{user_id}`\n"
        log_text += f"Message: {message}\n"
        log_text += f"Time: {time.strftime('%Y-%m-%d %H:%M:%S')}"
        
        await bot.send_message(Config.LOG_CHANNEL, log_text)
        return True
    except Exception as e:
        logger.error(f"Failed to send log: {e}")
        return False

async def check_user_access(user_client, chat_id):
    """Check if user has access to chat"""
    try:
        # Try to get chat info
        chat = await user_client.get_chat(chat_id)
        return True, chat
    except Exception as e:
        return False, str(e)

def format_file_size(size_bytes):
    """Format file size in human readable format"""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.2f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.2f} TB"

def format_time(seconds):
    """Format time in human readable format"""
    if seconds < 60:
        return f"{seconds}s"
    elif seconds < 3600:
        return f"{seconds//60}m {seconds%60}s"
    else:
        hours = seconds // 3600
        minutes = (seconds % 3600) // 60
        return f"{hours}h {minutes}m"

def create_progress_bar(progress, total, length=20):
    """Create progress bar"""
    percentage = (progress / total) * 100
    filled_length = int(length * progress // total)
    bar = '█' * filled_length + '░' * (length - filled_length)
    return f"[{bar}] {percentage:.1f}%"

def extract_info_from_link(link):
    """Extract chat_id and message_id from Telegram link"""
    import re
    
    patterns = [
        r"https?://t\.me/([^/]+)/(\d+)",
        r"https?://telegram\.me/([^/]+)/(\d+)",
        r"https?://telegram\.dog/([^/]+)/(\d+)"
    ]
    
    for pattern in patterns:
        match = re.match(pattern, link)
        if match:
            return match.group(1), int(match.group(2))
    
    return None, None
