import logging
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext
from config import Config
from database import Database

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

db = Database()

async def start(update: Update, context: CallbackContext):
    """Send a message when the command /start is issued."""
    welcome_text = """
🚀 *Welcome to Video Stream Bot!*

I can help you stream videos online. Just send me a video file and I'll create a streamable link for you.

*Features:*
• Upload videos up to 50MB
• Get a private streaming link
• View count tracking
• Mobile-friendly player

*Commands:*
/start - Show this message
/help - Get help
/myvideos - List your uploaded videos
/stats - Bot statistics (admin only)

*How to use:*
1. Send me any video file
2. I'll process it and send you a link
3. Share the link with anyone to stream
    """
    await update.message.reply_text(welcome_text, parse_mode='Markdown')

async def help_command(update: Update, context: CallbackContext):
    """Send a message when the command /help is issued."""
    help_text = """
*Help Guide*

*Supported Formats:* MP4, AVI, MOV, MKV, WebM
*Max File Size:* 50MB

*Common Issues:*
• If your video is larger than 50MB, try compressing it first
• Some formats may not play on all devices
• Links expire after 7 days

*Privacy:* Your videos are private and only accessible via the link I provide.
    """
    await update.message.reply_text(help_text, parse_mode='Markdown')

async def handle_video(update: Update, context: CallbackContext):
    """Handle video files sent to the bot."""
    user = update.effective_user
    
    try:
        # Check if message contains a video
        if update.message.video:
            video_file = update.message.video
            file_name = video_file.file_name or f"video_{video_file.file_id}.mp4"
        elif update.message.document and update.message.document.mime_type.startswith('video/'):
            video_file = update.message.document
            file_name = video_file.file_name or f"video_{video_file.file_id}"
        else:
            return
        
        # Check file size
        if video_file.file_size > Config.MAX_FILE_SIZE:
            await update.message.reply_text(
                f"❌ File too large! Maximum size is {Config.MAX_FILE_SIZE // (1024*1024)}MB"
            )
            return
        
        # Generate unique ID for the video
        video_id = str(uuid.uuid4())[:8]
        
        # Save to database
        db.add_video(
            video_id=video_id,
            file_id=video_file.file_id,
            file_name=file_name,
            file_size=video_file.file_size,
            mime_type=video_file.mime_type,
            user_id=user.id,
            chat_id=update.message.chat_id,
            message_id=update.message.message_id
        )
        
        # Create streaming URL
        stream_url = f"{Config.SERVER_URL}/stream/{video_id}"
        
        # Create response with inline keyboard
        keyboard = [
            [InlineKeyboardButton("🎬 Stream Video", url=stream_url)],
            [InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_{video_id}")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        response_text = f"""
✅ *Video Received!*

📹 *File:* {file_name}
📦 *Size:* {video_file.file_size // 1024}KB
🔗 *Stream Link:* {stream_url}

*Click the button below to stream your video:*
        """
        
        await update.message.reply_text(
            response_text,
            reply_markup=reply_markup,
            parse_mode='Markdown',
            disable_web_page_preview=True
        )
        
    except Exception as e:
        logger.error(f"Error handling video: {e}")
        await update.message.reply_text("❌ An error occurred while processing your video.")

async def my_videos(update: Update, context: CallbackContext):
    """List user's uploaded videos."""
    user = update.effective_user
    videos = db.get_user_videos(user.id)
    
    if not videos:
        await update.message.reply_text("You haven't uploaded any videos yet.")
        return
    
    response = "📁 *Your Videos:*\n\n"
    for idx, video in enumerate(videos[:10], 1):  # Show last 10 videos
        stream_url = f"{Config.SERVER_URL}/stream/{video['id']}"
        response += f"{idx}. {video['file_name']}\n"
        response += f"   👁️ {video['views']} views | 📅 {video['created_at'][:10]}\n"
        response += f"   🔗 {stream_url}\n\n"
    
    await update.message.reply_text(response, parse_mode='Markdown', disable_web_page_preview=True)

async def stats(update: Update, context: CallbackContext):
    """Show bot statistics (admin only)."""
    if update.effective_user.id != Config.ADMIN_ID:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    with db.get_connection() as conn:
        total_videos = conn.execute('SELECT COUNT(*) FROM videos').fetchone()[0]
        total_views = conn.execute('SELECT SUM(views) FROM videos').fetchone()[0] or 0
    
    stats_text = f"""
📊 *Bot Statistics*

📹 Total Videos: {total_videos}
👁️ Total Views: {total_views}
🚀 Server: {Config.SERVER_URL}
    """
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def button_callback(update: Update, context: CallbackContext):
    """Handle button callbacks."""
    query = update.callback_query
    await query.answer()
    
    if query.data.startswith("copy_"):
        video_id = query.data[5:]
        video = db.get_video(video_id)
        if video:
            stream_url = f"{Config.SERVER_URL}/stream/{video_id}"
            await query.edit_message_text(
                text=f"📋 Copy this link:\n\n`{stream_url}`\n\nLink copied to clipboard!",
                parse_mode='Markdown'
            )

def main():
    """Start the bot."""
    if not Config.BOT_TOKEN:
        logger.error("BOT_TOKEN not set in environment variables")
        return
    
    # Create application
    application = Application.builder().token(Config.BOT_TOKEN).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("myvideos", my_videos))
    application.add_handler(CommandHandler("stats", stats))
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Start the Bot
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
