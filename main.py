import os
import uuid
import logging
from datetime import datetime
from flask import Flask, render_template, Response, request, jsonify
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
import threading
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

# Flask app
app = Flask(__name__)
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-key")

# Configuration
class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
    SERVER_URL = os.getenv("SERVER_URL", "https://your-app.onrender.com")
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
            logger.info("MongoDB connected successfully")
        except Exception as e:
            logger.error(f"MongoDB connection failed: {e}")
            self.videos = None
    
    def setup_indexes(self):
        """Create database indexes"""
        if self.videos:
            # TTL index for auto-delete after 7 days
            self.videos.create_index("created_at", expireAfterSeconds=7 * 24 * 3600)
            self.videos.create_index("video_id", unique=True)
            self.videos.create_index("user_id")
    
    def add_video(self, video_data):
        """Add video to database"""
        if self.videos:
            try:
                video_data['created_at'] = datetime.utcnow()
                video_data['views'] = 0
                result = self.videos.insert_one(video_data)
                return str(result.inserted_id)
            except Exception as e:
                logger.error(f"Error adding video: {e}")
        return None
    
    def get_video(self, video_id):
        """Get video by ID"""
        if self.videos:
            return self.videos.find_one({"video_id": video_id})
        return None
    
    def increment_views(self, video_id):
        """Increment view count"""
        if self.videos:
            self.videos.update_one(
                {"video_id": video_id},
                {"$inc": {"views": 1}}
            )
    
    def get_user_videos(self, user_id, limit=10):
        """Get videos by user"""
        if self.videos:
            return list(self.videos.find(
                {"user_id": user_id}
            ).sort("created_at", DESCENDING).limit(limit))
        return []
    
    def delete_video(self, video_id, user_id=None):
        """Delete a video"""
        if self.videos:
            query = {"video_id": video_id}
            if user_id:
                query["user_id"] = user_id
            result = self.videos.delete_one(query)
            return result.deleted_count > 0
        return False
    
    def get_stats(self):
        """Get database statistics"""
        if self.videos:
            total_videos = self.videos.count_documents({})
            
            pipeline = [{"$group": {"_id": None, "total_views": {"$sum": "$views"}}}]
            result = list(self.videos.aggregate(pipeline))
            total_views = result[0]["total_views"] if result else 0
            
            return {
                "total_videos": total_videos,
                "total_views": total_views
            }
        return {"total_videos": 0, "total_views": 0}

# Initialize database
db = Database()
bot_instance = None

# Telegram Bot Functions
async def start_command(update: Update, context: CallbackContext):
    """Handle /start command"""
    await update.message.reply_text(
        "🎬 *Welcome to Video Stream Bot!*\n\n"
        "Send me any video file (up to 50MB) and I'll give you a streaming link.\n\n"
        "*Commands:*\n"
        "/start - Show this message\n"
        "/help - Get help\n"
        "/myvideos - List your videos",
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
        "*Commands:* /start, /help, /myvideos",
        parse_mode='Markdown'
    )

async def myvideos_command(update: Update, context: CallbackContext):
    """Handle /myvideos command"""
    user = update.effective_user
    videos = db.get_user_videos(user.id)
    
    if not videos:
        await update.message.reply_text("📭 You haven't uploaded any videos yet.")
        return
    
    response = "📁 *Your Videos:*\n\n"
    for idx, video in enumerate(videos[:5], 1):
        stream_url = f"{Config.SERVER_URL}/stream/{video['video_id']}"
        size_mb = video.get('file_size', 0) / (1024 * 1024)
        
        response += f"{idx}. {video.get('file_name', 'Video')}\n"
        response += f"   👁️ {video.get('views', 0)} views | 📦 {size_mb:.1f}MB\n"
        response += f"   🔗 {stream_url}\n\n"
    
    await update.message.reply_text(response, parse_mode='Markdown', disable_web_page_preview=True)

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
            "username": user.username
        }
        
        db.add_video(video_data)
        
        # Create streaming URL
        stream_url = f"{Config.SERVER_URL}/stream/{video_id}"
        
        # Create buttons
        keyboard = [
            [InlineKeyboardButton("🎬 Stream Video", url=stream_url)],
            [InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_{video_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        response = f"""
✅ *Video Uploaded!*

📹 *File:* {file_name}
📦 *Size:* {video_file.file_size // 1024}KB
🔗 *Stream Link:* {stream_url}

*Click below to stream:*
        """
        
        await update.message.reply_text(
            response,
            reply_markup=reply_markup,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error handling video: {e}")
        await update.message.reply_text("❌ Error processing video. Please try again.")

async def button_callback(update: Update, context: CallbackContext):
    """Handle button clicks"""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("copy_"):
        video_id = query.data[5:]
        stream_url = f"{Config.SERVER_URL}/stream/{video_id}"
        await query.edit_message_text(
            f"📋 *Link Copied!*\n\n`{stream_url}`\n\nShare this link to stream the video.",
            parse_mode='Markdown'
        )

async def error_handler(update: Update, context: CallbackContext):
    """Handle errors"""
    logger.error(f"Update {update} caused error {context.error}")
    try:
        await update.message.reply_text("❌ An error occurred. Please try again.")
    except:
        pass

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
        return "Video not found or expired", 404
    
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
        import requests
        
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
        "timestamp": datetime.utcnow().isoformat(),
        "server": Config.SERVER_URL
    })

# Telegram bot thread
def run_bot():
    """Run Telegram bot in a separate thread"""
    if not Config.BOT_TOKEN:
        logger.error("BOT_TOKEN not set!")
        return
    
    try:
        # Create application
        application = Application.builder().token(Config.BOT_TOKEN).build()
        
        # Add handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("myvideos", myvideos_command))
        application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
        application.add_handler(CallbackQueryHandler(button_callback))
        application.add_error_handler(error_handler)
        
        # Start bot
        logger.info("Starting Telegram bot...")
        application.run_polling(allowed_updates=Update.ALL_TYPES)
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

# Start bot thread when Flask starts
bot_thread = None

@app.before_first_request
def start_bot():
    """Start bot thread when Flask starts"""
    global bot_thread
    if Config.BOT_TOKEN and bot_thread is None:
        bot_thread = threading.Thread(target=run_bot, daemon=True)
        bot_thread.start()
        logger.info("Bot thread started")

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
