import os
import uuid
import threading
import logging
from datetime import datetime
from flask import Flask, render_template, Response, request, jsonify
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
import requests
from pymongo import MongoClient, DESCENDING
from pymongo.errors import ConnectionFailure
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
    MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017/")
    DATABASE_NAME = "video_stream_bot"
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# Database setup
class Database:
    def __init__(self):
        try:
            self.client = MongoClient(Config.MONGO_URI, serverSelectionTimeoutMS=5000)
            self.db = self.client[Config.DATABASE_NAME]
            self.videos = self.db.videos
            self.setup_indexes()
            logger.info("✅ MongoDB connected successfully")
        except Exception as e:
            logger.error(f"❌ MongoDB connection failed: {e}")
            # Fallback to in-memory storage
            self.videos = []
    
    def setup_indexes(self):
        """Create database indexes"""
        try:
            # TTL index for auto-delete after 7 days
            self.videos.create_index("created_at", expireAfterSeconds=7 * 24 * 3600)
            self.videos.create_index("video_id", unique=True)
            logger.info("✅ Database indexes created")
        except Exception as e:
            logger.error(f"❌ Error creating indexes: {e}")
    
    def add_video(self, video_data):
        """Add video to database"""
        try:
            video_data['created_at'] = datetime.utcnow()
            video_data['views'] = 0
            result = self.videos.insert_one(video_data)
            logger.info(f"✅ Video added: {video_data['video_id']}")
            return str(result.inserted_id)
        except Exception as e:
            logger.error(f"❌ Error adding video: {e}")
            return None
    
    def get_video(self, video_id):
        """Get video by ID"""
        try:
            return self.videos.find_one({"video_id": video_id})
        except Exception as e:
            logger.error(f"❌ Error getting video: {e}")
            return None
    
    def increment_views(self, video_id):
        """Increment view count"""
        try:
            self.videos.update_one(
                {"video_id": video_id},
                {"$inc": {"views": 1}}
            )
            logger.debug(f"✅ Views incremented for {video_id}")
        except Exception as e:
            logger.error(f"❌ Error incrementing views: {e}")
    
    def get_stats(self):
        """Get database statistics"""
        try:
            total_videos = self.videos.count_documents({})
            
            pipeline = [{"$group": {"_id": None, "total_views": {"$sum": "$views"}}}]
            result = list(self.videos.aggregate(pipeline))
            total_views = result[0]["total_views"] if result else 0
            
            return {
                "total_videos": total_videos,
                "total_views": total_views,
                "status": "connected"
            }
        except Exception as e:
            logger.error(f"❌ Error getting stats: {e}")
            return {"total_videos": 0, "total_views": 0, "status": "disconnected"}

# Initialize database
db = Database()

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
    
    return render_template(
        'video_player.html',
        video_id=video_id,
        video_name=video.get('file_name', 'Video'),
        views=video.get('views', 0) + 1
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
        "timestamp": datetime.utcnow().isoformat(),
        "server": Config.SERVER_URL,
        "database": stats['status'],
        "bot": "running" if Config.BOT_TOKEN else "disabled"
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
        "created_at": video.get('created_at').isoformat() if video.get('created_at') else None,
        "stream_url": f"{Config.SERVER_URL}/stream/{video_id}"
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
    stats = db.get_stats()
    await update.message.reply_text(
        f"📊 *Bot Status*\n\n"
        f"✅ Server: {Config.SERVER_URL}\n"
        f"📹 Total Videos: {stats['total_videos']}\n"
        f"👁️ Total Views: {stats['total_views']}\n"
        f"🛠️ Database: {stats['status']}\n",
        parse_mode='Markdown'
    )

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
            await update.message.reply_text(f"❌ File too large! Max size: {Config.MAX_FILE_SIZE // (1024*1024)}MB")
            return
        
        # Generate video ID
        video_id = str(uuid.uuid4())[:8]
        
        # Save to database
        video_data = {
            "video_id": video_id,
            "file_id": video_file.file_id,
            "file_name": file_name,
            "file_size": video_file.file_size,
            "mime_type": mime_type,
            "user_id": user.id,
            "username": user.username or str(user.id)
        }
        
        db_id = db.add_video(video_data)
        
        if not db_id:
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
    logger.error(f"Update {update} caused error {context.error}")
    try:
        await update.message.reply_text("❌ An error occurred. Please try again.")
    except:
        pass

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
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_error_handler(error_handler)
        
        # Start bot
        logger.info("🤖 Starting Telegram bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"❌ Failed to start bot: {e}")

# Start bot thread when Flask app starts
def start_bot_thread():
    """Start the Telegram bot in a separate thread"""
    if Config.BOT_TOKEN:
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        logger.info("✅ Bot thread started")

# Start bot thread when app is imported (for gunicorn)
start_bot_thread()

# For local development
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting Flask app on port {port}")
    app.run(host='0.0.0.0', port=port, debug=False)
