import os
import uuid
import json
import threading
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, Response, request, jsonify
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
import requests
from dotenv import load_dotenv
import pickle
from collections import OrderedDict
import time

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

# Simple in-memory database with file backup
class SimpleDB:
    def __init__(self):
        self.videos = OrderedDict()  # video_id -> video_data
        self.stats = {
            "total_videos": 0,
            "total_views": 0,
            "start_time": datetime.now().isoformat()
        }
        self.load_from_file()
    
    def load_from_file(self):
        """Load data from file if exists"""
        try:
            if os.path.exists('data.pkl'):
                with open('data.pkl', 'rb') as f:
                    data = pickle.load(f)
                    self.videos = data.get('videos', OrderedDict())
                    self.stats = data.get('stats', self.stats)
                logger.info("✅ Loaded data from file")
        except Exception as e:
            logger.error(f"❌ Error loading data: {e}")
    
    def save_to_file(self):
        """Save data to file"""
        try:
            data = {
                'videos': self.videos,
                'stats': self.stats
            }
            with open('data.pkl', 'wb') as f:
                pickle.dump(data, f)
        except Exception as e:
            logger.error(f"❌ Error saving data: {e}")
    
    def add_video(self, video_data):
        """Add a video"""
        video_id = video_data.get('video_id')
        if video_id:
            self.videos[video_id] = video_data
            self.stats["total_videos"] += 1
            self.save_to_file()
            logger.info(f"✅ Video added: {video_id}")
            return True
        return False
    
    def get_video(self, video_id):
        """Get video by ID"""
        return self.videos.get(video_id)
    
    def increment_views(self, video_id):
        """Increment view count"""
        if video_id in self.videos:
            video = self.videos[video_id]
            video['views'] = video.get('views', 0) + 1
            self.stats["total_views"] += 1
            self.save_to_file()
            return True
        return False
    
    def get_user_videos(self, user_id, limit=10):
        """Get videos by user"""
        user_videos = []
        for video in reversed(list(self.videos.values())):
            if video.get('user_id') == user_id:
                user_videos.append(video)
                if len(user_videos) >= limit:
                    break
        return user_videos
    
    def delete_video(self, video_id, user_id=None):
        """Delete a video"""
        if video_id in self.videos:
            if user_id is None or self.videos[video_id].get('user_id') == user_id:
                del self.videos[video_id]
                self.stats["total_videos"] -= 1
                self.save_to_file()
                return True
        return False
    
    def cleanup_old_videos(self, max_age_hours=24):
        """Cleanup old videos (older than max_age_hours)"""
        now = datetime.now()
        deleted = 0
        video_ids_to_delete = []
        
        for video_id, video in self.videos.items():
            created_str = video.get('created_at')
            if created_str:
                try:
                    created = datetime.fromisoformat(created_str)
                    age = now - created
                    if age.total_seconds() > max_age_hours * 3600:
                        video_ids_to_delete.append(video_id)
                except:
                    pass
        
        for video_id in video_ids_to_delete:
            del self.videos[video_id]
            deleted += 1
        
        if deleted:
            self.stats["total_videos"] -= deleted
            self.save_to_file()
        
        return deleted
    
    def get_stats(self):
        """Get database statistics"""
        return {
            "total_videos": len(self.videos),
            "total_views": self.stats.get("total_views", 0),
            "status": "connected",
            "uptime": self.stats.get("start_time")
        }

# Initialize database
db = SimpleDB()

# Background cleanup task
def cleanup_task():
    """Background task to cleanup old videos"""
    while True:
        try:
            deleted = db.cleanup_old_videos(max_age_hours=168)  # 7 days
            if deleted:
                logger.info(f"🧹 Cleaned up {deleted} old videos")
            time.sleep(3600)  # Run every hour
        except Exception as e:
            logger.error(f"Error in cleanup task: {e}")
            time.sleep(300)

# Start cleanup thread
cleanup_thread = threading.Thread(target=cleanup_task, daemon=True)
cleanup_thread.start()

# Flask Routes
@app.route('/')
def index():
    """Home page"""
    stats = db.get_stats()
    return render_template('index.html',
                         server_url=Config.SERVER_URL,
                         total_videos=stats['total_videos'],
                         total_views=stats['total_views'])

@app.route('/stream/<video_id>')
def stream_video(video_id):
    """Video player page"""
    video = db.get_video(video_id)
    if not video:
        return render_template('error.html', 
                             message="Video not found or expired",
                             server_url=Config.SERVER_URL), 404
    
    db.increment_views(video_id)
    
    # Format date
    created = video.get('created_at', '')
    if created:
        try:
            created_dt = datetime.fromisoformat(created)
            created = created_dt.strftime('%B %d, %Y %H:%M')
        except:
            created = 'Unknown'
    
    size_mb = video.get('file_size', 0) / (1024 * 1024)
    
    return render_template(
        'video_player.html',
        video_id=video_id,
        video_name=video.get('file_name', 'Video'),
        video_size=size_mb,
        views=video.get('views', 0) + 1,
        created=created,
        username=video.get('username', 'Anonymous')
    )

@app.route('/video/<video_id>')
def serve_video(video_id):
    """Serve video stream"""
    video = db.get_video(video_id)
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
                'Content-Disposition': f'inline; filename="{video.get("file_name", "video.mp4")}"',
                'Cache-Control': 'no-cache'
            }
        )
    
    except Exception as e:
        logger.error(f"❌ Error serving video: {e}")
        return "Error serving video", 500

@app.route('/health')
def health():
    """Health check endpoint"""
    stats = db.get_stats()
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "server": Config.SERVER_URL,
        "database": "simple_memory_db",
        "bot": "running" if Config.BOT_TOKEN else "disabled",
        "videos": stats['total_videos'],
        "views": stats['total_views'],
        "uptime": stats['uptime']
    })

@app.route('/api/video/<video_id>')
def video_info(video_id):
    """Get video info"""
    video = db.get_video(video_id)
    if not video:
        return jsonify({"error": "Video not found"}), 404
    
    return jsonify({
        "video_id": video.get('video_id'),
        "file_name": video.get('file_name'),
        "file_size": video.get('file_size'),
        "views": video.get('views', 0),
        "created_at": video.get('created_at'),
        "stream_url": f"{Config.SERVER_URL}/stream/{video_id}"
    })

# Telegram Bot Functions
async def start_command(update: Update, context: CallbackContext):
    """Handle /start command"""
    await update.message.reply_text(
        "🎬 *Welcome to Video Stream Bot!*\n\n"
        "Send me any video file (up to 50MB) and I'll give you a streaming link.\n\n"
        "*Features:*\n"
        "• Upload videos up to 50MB\n"
        "• Get streaming links instantly\n"
        "• Videos auto-delete after 7 days\n"
        "• Mobile-friendly player\n\n"
        "*Commands:*\n"
        "/start - Show this message\n"
        "/help - Get help\n"
        "/myvideos - List your videos\n"
        "/status - Check bot status",
        parse_mode='Markdown'
    )

async def help_command(update: Update, context: CallbackContext):
    """Handle /help command"""
    await update.message.reply_text(
        "📖 *Help Guide*\n\n"
        "1. Send me any video file (MP4, AVI, MOV, MKV, WebM)\n"
        "2. Maximum file size: 50MB\n"
        "3. I'll send you a streaming link\n"
        "4. Share the link with anyone\n"
        "5. Videos auto-delete after 7 days\n\n"
        "*Note:* Videos are stored temporarily in memory and will be lost on server restart.",
        parse_mode='Markdown'
    )

async def myvideos_command(update: Update, context: CallbackContext):
    """Handle /myvideos command"""
    user = update.effective_user
    try:
        videos = db.get_user_videos(user.id)
        
        if not videos:
            await update.message.reply_text("📭 You haven't uploaded any videos yet.")
            return
        
        response = "📁 *Your Recent Videos:*\n\n"
        for idx, video in enumerate(videos[:5], 1):
            stream_url = f"{Config.SERVER_URL}/stream/{video['video_id']}"
            size_mb = video.get('file_size', 0) / (1024 * 1024)
            
            response += f"{idx}. *{video.get('file_name', 'Video')}*\n"
            response += f"   👁️ {video.get('views', 0)} views | 📦 {size_mb:.1f}MB\n"
            response += f"   🔗 {stream_url}\n\n"
        
        response += f"📊 Total: {len(videos)} videos"
        
        await update.message.reply_text(response, parse_mode='Markdown', disable_web_page_preview=True)
    except Exception as e:
        logger.error(f"Error in myvideos command: {e}")
        await update.message.reply_text("❌ Error fetching your videos.")

async def status_command(update: Update, context: CallbackContext):
    """Handle /status command"""
    try:
        stats = db.get_stats()
        await update.message.reply_text(
            f"📊 *Bot Status*\n\n"
            f"✅ Server: {Config.SERVER_URL}\n"
            f"📹 Total Videos: {stats['total_videos']}\n"
            f"👁️ Total Views: {stats['total_views']}\n"
            f"🕐 Uptime: {stats.get('uptime', 'Unknown')}\n"
            f"🛠️ Storage: Simple Memory DB",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in status command: {e}")
        await update.message.reply_text("❌ Error fetching status.")

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
            "username": user.username or str(user.id),
            "views": 0,
            "created_at": datetime.now().isoformat()
        }
        
        # Save to database
        success = db.add_video(video_data)
        
        if not success:
            await update.message.reply_text("❌ Failed to save video. Please try again.")
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
        
        response = f"""
✅ *Video Uploaded Successfully!*

📹 *File:* `{file_name}`
📦 *Size:* `{size_mb:.1f} MB`
🔗 *Stream Link:* `{stream_url}`

*Click below to stream your video:*
        """
        
        await update.message.reply_text(
            response,
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
    logger.error(f"Telegram Bot Error: {context.error}")

# Telegram bot thread function
def run_bot():
    """Run Telegram bot in a separate thread"""
    if not Config.BOT_TOKEN:
        logger.error("❌ BOT_TOKEN not set! Telegram bot disabled.")
        return
    
    try:
        # Create application
        application = Application.builder().token(Config.BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("myvideos", myvideos_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_error_handler(error_handler)
        
        # Start bot
        logger.info("🤖 Starting Telegram bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")

# Start bot thread
bot_thread = threading.Thread(target=run_bot, daemon=True)
bot_thread.start()
logger.info("✅ Bot thread started")

# For local development
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
