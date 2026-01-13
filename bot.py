import logging
import uuid
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, CallbackContext, CallbackQueryHandler
from config import Config
from database import db

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

async def start(update: Update, context: CallbackContext):
    """Send a message when the command /start is issued."""
    user = update.effective_user
    
    # Store user info in database
    db.add_user({
        "telegram_id": user.id,
        "username": user.username,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "language_code": user.language_code,
        "joined_at": datetime.utcnow()
    })
    
    welcome_text = """
🚀 *Welcome to Video Stream Bot!*

I can help you stream videos online. Just send me a video file and I'll create a streamable link for you.

*Features:*
• Upload videos up to 50MB
• Get a private streaming link
• View count tracking
• Mobile-friendly player
• Auto-delete after 7 days

*Commands:*
/start - Show this message
/help - Get help
/myvideos - List your uploaded videos
/stats - Bot statistics (admin only)
/delete <id> - Delete a video

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
• Links auto-expire after 7 days
• Videos are private - only people with the link can view

*Privacy:* Your videos are private and only accessible via the unique link I provide.
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
        
        # Generate unique ID for the video
        video_id = str(uuid.uuid4())[:8]
        
        # Prepare video data for database
        video_data = {
            "video_id": video_id,
            "file_id": video_file.file_id,
            "file_name": file_name,
            "file_size": video_file.file_size,
            "mime_type": mime_type,
            "user_id": user.id,
            "username": user.username,
            "chat_id": update.message.chat_id,
            "message_id": update.message.message_id,
            "duration": video_file.duration if hasattr(video_file, 'duration') else None,
            "width": video_file.width if hasattr(video_file, 'width') else None,
            "height": video_file.height if hasattr(video_file, 'height') else None
        }
        
        # Save to database
        db_id = db.add_video(video_data)
        
        if not db_id:
            await update.message.reply_text("❌ Failed to save video to database.")
            return
        
        # Update user stats
        db.update_user_stats(user.id)
        
        # Create streaming URL
        stream_url = f"{Config.SERVER_URL}/stream/{video_id}"
        
        # Create response with inline keyboard
        keyboard = [
            [InlineKeyboardButton("🎬 Stream Video", url=stream_url)],
            [
                InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_{video_id}"),
                InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{video_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        # Format file size
        size_mb = video_file.file_size / (1024 * 1024)
        
        response_text = f"""
✅ *Video Uploaded Successfully!*

📹 *File:* `{file_name}`
📦 *Size:* `{size_mb:.1f} MB`
⏱️ *Duration:* `{video_data['duration']}s` (if available)
🔗 *Stream Link:* `{stream_url}`
🆔 *Video ID:* `{video_id}`

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
        await update.message.reply_text("📭 You haven't uploaded any videos yet.")
        return
    
    response = "📁 *Your Recent Videos:*\n\n"
    for idx, video in enumerate(videos[:10], 1):
        stream_url = f"{Config.SERVER_URL}/stream/{video['video_id']}"
        size_mb = video['file_size'] / (1024 * 1024) if video['file_size'] else 0
        created = video['created_at'].strftime('%b %d, %H:%M')
        
        response += f"*{idx}. {video['file_name']}*\n"
        response += f"   🆔 `{video['video_id']}` | 👁️ `{video['views']}` views\n"
        response += f"   📦 `{size_mb:.1f}MB` | 📅 `{created}`\n"
        response += f"   🔗 {stream_url}\n\n"
    
    response += f"\n📊 *Total Videos:* `{len(videos)}`"
    
    await update.message.reply_text(
        response, 
        parse_mode='Markdown', 
        disable_web_page_preview=True
    )

async def delete_video(update: Update, context: CallbackContext):
    """Delete a video by ID."""
    user = update.effective_user
    
    if not context.args:
        await update.message.reply_text("❌ Please provide a video ID. Usage: `/delete <video_id>`", parse_mode='Markdown')
        return
    
    video_id = context.args[0]
    
    # Check if video exists and belongs to user
    video = db.get_video(video_id)
    if not video:
        await update.message.reply_text("❌ Video not found.")
        return
    
    if video['user_id'] != user.id and user.id != Config.ADMIN_ID:
        await update.message.reply_text("❌ You can only delete your own videos.")
        return
    
    # Delete video
    if db.delete_video(video_id, user.id if user.id != Config.ADMIN_ID else None):
        await update.message.reply_text(f"✅ Video `{video_id}` has been deleted.", parse_mode='Markdown')
    else:
        await update.message.reply_text("❌ Failed to delete video.")

async def stats(update: Update, context: CallbackContext):
    """Show bot statistics (admin only)."""
    if update.effective_user.id != Config.ADMIN_ID:
        await update.message.reply_text("❌ Admin only command.")
        return
    
    stats_data = db.get_database_stats()
    
    stats_text = f"""
📊 *Bot Statistics*

📹 Total Videos: `{stats_data['total_videos']}`
👁️ Total Views: `{stats_data['total_views']}`
👥 Total Users: `{stats_data['total_users']}`
🚀 Server: `{Config.SERVER_URL}`

*Storage Information:*
• Videos auto-delete after {Config.CLEANUP_DAYS} days
• Max file size: {Config.MAX_FILE_SIZE // (1024*1024)}MB
• Using MongoDB Atlas
    """
    
    await update.message.reply_text(stats_text, parse_mode='Markdown')

async def button_callback(update: Update, context: CallbackContext):
    """Handle button callbacks."""
    query = update.callback_query
    await query.answer()
    
    user = query.from_user
    
    if query.data.startswith("copy_"):
        video_id = query.data[5:]
        video = db.get_video(video_id)
        if video:
            stream_url = f"{Config.SERVER_URL}/stream/{video_id}"
            await query.edit_message_text(
                text=f"📋 *Link Copied!*\n\n"
                     f"Share this link to stream the video:\n"
                     f"`{stream_url}`\n\n"
                     f"*Video:* {video['file_name']}\n"
                     f"*Views:* {video['views']}",
                parse_mode='Markdown'
            )
    
    elif query.data.startswith("delete_"):
        video_id = query.data[7:]
        video = db.get_video(video_id)
        
        if not video:
            await query.edit_message_text("❌ Video not found or already deleted.")
            return
        
        if video['user_id'] != user.id and user.id != Config.ADMIN_ID:
            await query.edit_message_text("❌ You can only delete your own videos.")
            return
        
        # Show confirmation keyboard
        keyboard = [
            [
                InlineKeyboardButton("✅ Yes, Delete", callback_data=f"confirm_delete_{video_id}"),
                InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_delete_{video_id}")
            ]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        await query.edit_message_text(
            text=f"🗑️ *Delete Video?*\n\n"
                 f"Are you sure you want to delete:\n"
                 f"`{video['file_name']}`\n\n"
                 f"This action cannot be undone!",
            reply_markup=reply_markup,
            parse_mode='Markdown'
        )
    
    elif query.data.startswith("confirm_delete_"):
        video_id = query.data[15:]
        video = db.get_video(video_id)
        
        if video and db.delete_video(video_id, user.id if user.id != Config.ADMIN_ID else None):
            await query.edit_message_text(f"✅ Video `{video_id}` has been deleted.", parse_mode='Markdown')
        else:
            await query.edit_message_text("❌ Failed to delete video or video not found.")
    
    elif query.data.startswith("cancel_delete_"):
        video_id = query.data[14:]
        video = db.get_video(video_id)
        
        if video:
            stream_url = f"{Config.SERVER_URL}/stream/{video_id}"
            keyboard = [
                [InlineKeyboardButton("🎬 Stream Video", url=stream_url)],
                [
                    InlineKeyboardButton("📋 Copy Link", callback_data=f"copy_{video_id}"),
                    InlineKeyboardButton("🗑️ Delete", callback_data=f"delete_{video_id}")
                ]
            ]
            reply_markup = InlineKeyboardMarkup(keyboard)
            
            await query.edit_message_text(
                text=f"✅ *Deletion Cancelled*\n\n"
                     f"Video `{video_id}` is still available.\n"
                     f"🔗 {stream_url}",
                reply_markup=reply_markup,
                parse_mode='Markdown'
            )

async def error_handler(update: Update, context: CallbackContext):
    """Log errors."""
    logger.error(f"Update {update} caused error {context.error}")
    try:
        await update.message.reply_text("❌ An error occurred. Please try again.")
    except:
        pass

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
    application.add_handler(CommandHandler("delete", delete_video))
    application.add_handler(MessageHandler(filters.VIDEO | filters.Document.VIDEO, handle_video))
    application.add_handler(CallbackQueryHandler(button_callback))
    
    # Add error handler
    application.add_error_handler(error_handler)
    
    # Start the Bot
    logger.info("Starting bot...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
