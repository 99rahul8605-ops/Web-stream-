import os
import uuid
import asyncio
import threading
import logging
from datetime import datetime
from flask import Flask, render_template, Response, jsonify
from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup
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

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")

# Configuration
class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
    SERVER_URL = os.getenv("SERVER_URL", "http://localhost:5000")
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# Simple in-memory storage
videos_db = {}
stats = {"total_videos": 0, "total_views": 0}

# Flask Routes
@app.route('/')
def index():
    """Home page"""
    return render_template('index.html',
                         server_url=Config.SERVER_URL,
                         total_videos=stats["total_videos"],
                         total_views=stats["total_views"])

@app.route('/stream/<video_id>')
def stream_video(video_id):
    """Video player page"""
    video = videos_db.get(video_id)
    if not video:
        return render_template('error.html', 
                             message="Video not found or expired",
                             server_url=Config.SERVER_URL), 404
    
    # Increment view count
    video['views'] = video.get('views', 0) + 1
    stats["total_views"] += 1
    
    return render_template(
        'video_player.html',
        video_id=video_id,
        video_name=video.get('file_name', 'Video'),
        views=video.get('views', 0)
    )

@app.route('/video/<video_id>')
def serve_video(video_id):
    """Serve video stream"""
    video = videos_db.get(video_id)
    if not video:
        return "Video not found", 404
    
    try:
        # Get bot instance
        bot = Bot(token=Config.BOT_TOKEN)
        file = bot.get_file(video['file_id'])
        
        # Get file URL
        file_url = file.file_path
        if not file_url.startswith('http'):
            file_url = f"https://api.telegram.org/file/bot{Config.BOT_TOKEN}/{file_url}"
        
        # Stream video
        def generate():
            response = requests.get(file_url, stream=True)
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    yield chunk
        
        return Response(
            generate(),
            content_type=video.get('mime_type', 'video/mp4'),
            headers={
                'Content-Disposition': f'inline; filename="{video.get("file_name", "video.mp4")}"'
            }
        )
    
    except Exception as e:
        logger.error(f"Error serving video: {e}")
        return "Error serving video", 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "server": Config.SERVER_URL,
        "bot": "running" if Config.BOT_TOKEN else "disabled",
        "videos": stats["total_videos"],
        "views": stats["total_views"]
    })

# Telegram Bot Functions
async def start_command(update: Update, context: CallbackContext):
    """Handle /start command"""
    await update.message.reply_text(
        "🎬 *Welcome to Video Stream Bot!*\n\n"
        "Send me any video file (up to 50MB) and I'll give you a streaming link.\n\n"
        "*Commands:*\n"
        "/start - Show this message\n"
        "/help - Get help\n"
        "/status - Check bot status",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: CallbackContext):
    """Handle /help command"""
    await update.message.reply_text(
        "📖 *Help*\n\n"
        "1. Send me any video file (MP4, AVI, MOV, MKV, WebM)\n"
        "2. Maximum file size: 50MB\n"
        "3. I'll send you a streaming link\n"
        "4. Share the link with anyone\n"
        "5. Videos auto-delete after 7 days\n\n"
        "Need help? Contact admin.",
        parse_mode='Markdown'
    )

async def status_command(update: Update, context: CallbackContext):
    """Handle /status command"""
    await update.message.reply_text(
        f"📊 *Bot Status*\n\n"
        f"✅ Server: {Config.SERVER_URL}\n"
        f"📹 Total Videos: {stats['total_videos']}\n"
        f"👁️ Total Views: {stats['total_views']}\n",
        parse_mode='Markdown'
    )

async def handle_video(update: Update, context: CallbackContext):
    """Handle video files"""
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
            await update.message.reply_text(f"❌ File too large! Max: {Config.MAX_FILE_SIZE // (1024*1024)}MB")
            return
        
        # Generate video ID
        video_id = str(uuid.uuid4())[:8]
        
        # Save to database
        videos_db[video_id] = {
            "video_id": video_id,
            "file_id": video_file.file_id,
            "file_name": file_name,
            "file_size": video_file.file_size,
            "mime_type": mime_type,
            "user_id": update.effective_user.id,
            "views": 0,
            "created_at": datetime.now().isoformat()
        }
        
        stats["total_videos"] += 1
        
        # Create streaming URL
        stream_url = f"{Config.SERVER_URL}/stream/{video_id}"
        
        # Create buttons
        keyboard = [[InlineKeyboardButton("🎬 Stream Video", url=stream_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        size_mb = video_file.file_size / (1024 * 1024)
        
        response = f"""
✅ *Video Uploaded!*

📹 *File:* {file_name}
📦 *Size:* {size_mb:.1f}MB
🔗 *Stream Link:* {stream_url}
        """
        
        await update.message.reply_text(
            response,
            reply_markup=reply_markup,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error handling video: {e}")
        await update.message.reply_text("❌ Error processing video.")

async def error_handler(update: Update, context: CallbackContext):
    """Handle errors"""
    logger.error(f"Bot error: {context.error}")

# Telegram bot thread with proper asyncio setup
def run_bot():
    """Run the Telegram bot with proper asyncio event loop"""
    if not Config.BOT_TOKEN:
        logger.warning("BOT_TOKEN not set. Bot disabled.")
        return
    
    try:
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create application
        application = Application.builder().token(Config.BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
        application.add_error_handler(error_handler)
        
        # Run the bot
        logger.info("Starting Telegram bot...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

# Start bot thread
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()
logger.info("✅ Bot thread started successfully")

# For local development
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
