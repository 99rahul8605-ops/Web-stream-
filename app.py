import os
import uuid
import asyncio
import threading
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, Response, jsonify
from telegram import Bot, Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
import requests
from dotenv import load_dotenv
import time
from collections import OrderedDict

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
app.secret_key = os.getenv("SECRET_KEY", "your-secret-key-here-123")

# Configuration - USE YOUR ACTUAL VALUES
BOT_TOKEN = os.getenv("BOT_TOKEN", "8501689500:AAF1QWBlE_wCdKmhmL-mc2eLRi3w7YteHyw")  # Your actual bot token
ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
SERVER_URL = os.getenv("SERVER_URL", "https://web-stream-1.onrender.com")
MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# Simple in-memory storage
videos_db = {}  # video_id -> video_data
stats = {"total_videos": 0, "total_views": 0}

# Flask Routes
@app.route('/')
def index():
    """Home page"""
    return render_template('index.html',
                         server_url=SERVER_URL,
                         total_videos=stats["total_videos"],
                         total_views=stats["total_views"])

@app.route('/stream/<video_id>')
def stream_video(video_id):
    """Video player page"""
    video = videos_db.get(video_id)
    if not video:
        return render_template('error.html', 
                             message="Video not found or expired",
                             server_url=SERVER_URL), 404
    
    # Increment view count
    if 'views' not in video:
        video['views'] = 0
    video['views'] += 1
    stats["total_views"] += 1
    
    # Format date
    created = video.get('created_at', 'Recently')
    size_mb = video.get('file_size', 0) / (1024 * 1024) if video.get('file_size') else 0
    
    return render_template(
        'video_player.html',
        video_id=video_id,
        video_name=video.get('file_name', 'Video'),
        video_size=size_mb,
        views=video.get('views', 0),
        created=created,
        username=video.get('username', 'Anonymous')
    )

@app.route('/video/<video_id>')
def serve_video(video_id):
    """Serve video stream"""
    video = videos_db.get(video_id)
    if not video:
        return "Video not found", 404
    
    try:
        # Get bot instance
        bot = Bot(token=BOT_TOKEN)
        file = bot.get_file(video['file_id'])
        
        # Get file URL
        file_url = file.file_path
        if not file_url.startswith('http'):
            file_url = f"https://api.telegram.org/file/bot{BOT_TOKEN}/{file_url}"
        
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
        "server": SERVER_URL,
        "bot": "running" if BOT_TOKEN else "disabled",
        "videos": len(videos_db),
        "views": stats["total_views"]
    })

# Telegram Bot Functions
async def start_command(update: Update, context: CallbackContext):
    """Handle /start command"""
    await update.message.reply_text(
        "🎬 *Welcome to Video Stream Bot!*\n\n"
        "I can convert your Telegram videos into streamable web links!\n\n"
        "*How to use:*\n"
        "1. Send me any video file (up to 50MB)\n"
        "2. I'll process it and give you a streaming link\n"
        "3. Share the link with anyone to watch\n\n"
        "Try it now - send me a video! 🎥",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: CallbackContext):
    """Handle /help command"""
    await update.message.reply_text(
        "📖 *Help Guide*\n\n"
        "*Supported formats:* MP4, AVI, MOV, MKV, WebM\n"
        "*Max file size:* 50MB\n"
        "*Auto-delete:* Videos expire after 24 hours\n\n"
        "Just send me a video file and I'll do the rest!",
        parse_mode='Markdown'
    )

async def handle_video(update: Update, context: CallbackContext):
    """Handle video files - SIMPLE VERSION"""
    try:
        user = update.effective_user
        
        # Get video file
        if update.message.video:
            video_file = update.message.video
            file_name = video_file.file_name or f"video_{video_file.file_id[:8]}.mp4"
            mime_type = "video/mp4"
        elif update.message.document and update.message.document.mime_type and 'video' in update.message.document.mime_type:
            video_file = update.message.document
            file_name = video_file.file_name or f"video_{video_file.file_id[:8]}"
            mime_type = video_file.mime_type
        else:
            return
        
        # Check file size
        if video_file.file_size and video_file.file_size > MAX_FILE_SIZE:
            await update.message.reply_text(
                f"❌ File too large! Maximum size is {MAX_FILE_SIZE // (1024*1024)}MB"
            )
            return
        
        # Generate video ID
        video_id = str(uuid.uuid4())[:8]
        
        # Store video data in memory
        videos_db[video_id] = {
            "video_id": video_id,
            "file_id": video_file.file_id,
            "file_name": file_name,
            "file_size": video_file.file_size,
            "mime_type": mime_type,
            "user_id": user.id,
            "username": user.username or user.first_name or f"User_{user.id}",
            "views": 0,
            "created_at": datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        }
        
        stats["total_videos"] = len(videos_db)
        
        # Create streaming URL
        stream_url = f"{SERVER_URL}/stream/{video_id}"
        
        # Create button
        keyboard = [[InlineKeyboardButton("🎬 Watch Video Online", url=stream_url)]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        size_mb = video_file.file_size / (1024 * 1024) if video_file.file_size else 0
        
        response_text = f"""
✅ *Video Received!*

📹 *File:* {file_name}
📦 *Size:* {size_mb:.1f} MB
🔗 *Stream Link:* {stream_url}

*Click the button below to watch:*
        """
        
        await update.message.reply_text(
            response_text,
            reply_markup=reply_markup,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
        logger.info(f"Video processed: {video_id}, User: {user.id}")
        
    except Exception as e:
        logger.error(f"Error handling video: {str(e)}", exc_info=True)
        await update.message.reply_text("❌ Error processing video. Please try again.")

async def error_handler(update: Update, context: CallbackContext):
    """Handle errors"""
    logger.error(f"Bot error: {context.error}")
    if update and update.message:
        try:
            await update.message.reply_text("❌ An error occurred. Please try again.")
        except:
            pass

# Cleanup old videos function
def cleanup_old_videos():
    """Remove videos older than 24 hours"""
    while True:
        try:
            now = datetime.now()
            videos_to_delete = []
            
            for video_id, video in list(videos_db.items()):
                created_str = video.get('created_at')
                if created_str:
                    try:
                        created = datetime.strptime(created_str, '%Y-%m-%d %H:%M:%S')
                        age_hours = (now - created).total_seconds() / 3600
                        if age_hours > 24:  # 24 hours
                            videos_to_delete.append(video_id)
                    except:
                        # If can't parse date, delete the video
                        videos_to_delete.append(video_id)
            
            for video_id in videos_to_delete:
                if video_id in videos_db:
                    del videos_db[video_id]
            
            if videos_to_delete:
                stats["total_videos"] = len(videos_db)
                logger.info(f"Cleaned up {len(videos_to_delete)} old videos")
            
            time.sleep(3600)  # Run every hour
            
        except Exception as e:
            logger.error(f"Cleanup error: {e}")
            time.sleep(300)

# Telegram bot runner
def run_bot():
    """Run the Telegram bot"""
    if not BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set! Bot cannot start.")
        return
    
    try:
        # Create a new event loop for this thread
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Create application
        application = Application.builder().token(BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(MessageHandler(
            filters.VIDEO | (filters.Document.ALL & ~filters.Document.AUDIO), 
            handle_video
        ))
        application.add_error_handler(error_handler)
        
        # Run the bot
        logger.info(f"🤖 Starting Telegram bot with token: {BOT_TOKEN[:10]}...")
        logger.info(f"🌐 Server URL: {SERVER_URL}")
        application.run_polling(drop_pending_updates=True)
        
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {str(e)}", exc_info=True)

# Start background threads
def start_background_threads():
    """Start background threads"""
    # Start cleanup thread
    cleanup_thread = threading.Thread(target=cleanup_old_videos, daemon=True)
    cleanup_thread.start()
    logger.info("✅ Cleanup thread started")
    
    # Start bot thread
    bot_thread = threading.Thread(target=run_bot, daemon=True)
    bot_thread.start()
    logger.info("✅ Bot thread started")

# Start everything
start_background_threads()

# Main entry point
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting Flask app on port {port}")
    logger.info(f"📊 Initial stats: {stats}")
    app.run(host='0.0.0.0', port=port, debug=False)
