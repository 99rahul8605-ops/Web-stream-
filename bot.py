import os
import uuid
import asyncio
import logging
from datetime import datetime
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
import requests
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Setup logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Configuration
class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    SERVER_URL = os.getenv("SERVER_URL", "https://web-stream-1.onrender.com")
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

async def start_command(update: Update, context: CallbackContext):
    """Handle /start command"""
    user = update.effective_user
    await update.message.reply_text(
        f"🎬 *Welcome to Video Stream Bot, {user.first_name}!*\n\n"
        "I can convert your Telegram videos into streamable web links!\n\n"
        "*How to use:*\n"
        "1. Send me any video file (up to 50MB)\n"
        "2. I'll process it and give you a streaming link\n"
        "3. Share the link with anyone to watch\n\n"
        "*Supported formats:* MP4, AVI, MOV, MKV, WebM\n"
        "*Auto-delete:* Videos expire after 7 days\n\n"
        "*Commands:*\n"
        "/start - Show this message\n"
        "/help - Get help\n"
        "/status - Check bot status",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: CallbackContext):
    """Handle /help command"""
    await update.message.reply_text(
        "📖 *Help Guide*\n\n"
        "*Uploading Videos:*\n"
        "• Send me any video file\n"
        "• Maximum size: 50MB\n"
        "• I'll reply with a streaming link\n\n"
        "*Streaming:*\n"
        "• Click the link to open video player\n"
        "• Works on all devices\n"
        "• Supports seeking\n"
        "• Mobile-friendly\n\n"
        "*Privacy:*\n"
        "• Videos are private\n"
        "• Only people with the link can view\n"
        "• Auto-deletes after 7 days\n\n"
        "Need more help? Contact @your_admin",
        parse_mode='Markdown'
    )

async def status_command(update: Update, context: CallbackContext):
    """Handle /status command"""
    try:
        # Get server stats
        response = requests.get(f"{Config.SERVER_URL}/health", timeout=5)
        if response.status_code == 200:
            data = response.json()
            await update.message.reply_text(
                f"📊 *Bot Status*\n\n"
                f"✅ Server: {Config.SERVER_URL}\n"
                f"📹 Videos: {data.get('videos', 0)}\n"
                f"👁️ Views: {data.get('views', 0)}\n"
                f"🛠️ Status: {data.get('status', 'unknown')}\n"
                f"🤖 Bot: Running\n",
                parse_mode='Markdown'
            )
        else:
            await update.message.reply_text("❌ Cannot connect to server")
    except Exception as e:
        logger.error(f"Status check error: {e}")
        await update.message.reply_text("❌ Error checking status")

async def handle_video(update: Update, context: CallbackContext):
    """Handle video files"""
    user = update.effective_user
    
    try:
        # Get video file
        if update.message.video:
            video_file = update.message.video
            file_name = video_file.file_name or f"video_{video_file.file_id}.mp4"
            mime_type = "video/mp4"
        elif update.message.document and update.message.document.mime_type.startswith('video/'):
            video_file = update.message.document
            file_name = video_file.file_name or f"video_{video_file.file_id}"
            mime_type = video_file.mime_type
        else:
            return
        
        # Check file size
        if video_file.file_size > Config.MAX_FILE_SIZE:
            await update.message.reply_text(
                f"❌ File too large! Maximum size is {Config.MAX_FILE_SIZE // (1024*1024)}MB"
            )
            return
        
        # Generate video ID
        video_id = str(uuid.uuid4())[:8]
        
        # Prepare video data
        video_data = {
            "video_id": video_id,
            "file_id": video_file.file_id,
            "file_name": file_name,
            "file_size": video_file.file_size,
            "mime_type": mime_type,
            "user_id": user.id,
            "username": user.username or user.first_name or str(user.id),
            "views": 0,
            "created_at": datetime.now().isoformat()
        }
        
        # Save to server via API
        try:
            response = requests.post(
                f"{Config.SERVER_URL}/api/save_video",
                json=video_data,
                timeout=10
            )
            
            if response.status_code != 200:
                raise Exception(f"Server error: {response.status_code}")
                
            result = response.json()
            if result.get('status') != 'success':
                raise Exception(f"API error: {result.get('error', 'Unknown error')}")
                
        except Exception as e:
            logger.error(f"Server API error: {e}")
            await update.message.reply_text("❌ Server error. Please try again later.")
            return
        
        # Create streaming URL
        stream_url = f"{Config.SERVER_URL}/stream/{video_id}"
        
        # Create buttons
        keyboard = [
            [InlineKeyboardButton("🎬 Stream Video", url=stream_url)],
            [InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_{video_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        size_mb = video_file.file_size / (1024 * 1024)
        
        response_text = f"""
✅ *Video Uploaded Successfully!*

📹 *File:* `{file_name}`
📦 *Size:* `{size_mb:.1f} MB`
🔗 *Stream Link:* `{stream_url}`

*Click below to stream your video:*
        """
        
        await update.message.reply_text(
            response_text,
            reply_markup=reply_markup,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"❌ Error handling video: {e}")
        await update.message.reply_text("❌ Error processing video. Please try again.")

async def button_callback(update: Update, context: CallbackContext):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("copy_"):
        video_id = query.data[5:]
        stream_url = f"{Config.SERVER_URL}/stream/{video_id}"
        await query.edit_message_text(
            f"📋 *Link Copied!*\n\nShare this link:\n`{stream_url}`",
            parse_mode='Markdown'
        )

async def error_handler(update: Update, context: CallbackContext):
    """Handle errors"""
    logger.error(f"Bot error: {context.error}")
    try:
        await update.message.reply_text("❌ An error occurred. Please try again.")
    except:
        pass

def main():
    """Main function to run the bot"""
    if not Config.BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set! Bot will not start.")
        return
    
    try:
        # Create application
        application = Application.builder().token(Config.BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_error_handler(error_handler)
        
        # Start bot
        logger.info("🤖 Starting Telegram bot...")
        logger.info(f"🌐 Server URL: {Config.SERVER_URL}")
        
        # Run bot with polling
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")

if __name__ == '__main__':
    main()
