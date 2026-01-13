from flask import Flask, render_template, Response, request, jsonify
from telegram import Bot
from config import Config
from database import db
import logging
from datetime import datetime
import os

app = Flask(__name__)
app.secret_key = Config.SECRET_KEY
bot_instance = None

def get_bot():
    """Get bot instance for file downloads."""
    global bot_instance
    if bot_instance is None:
        bot_instance = Bot(token=Config.BOT_TOKEN)
    return bot_instance

@app.route('/')
def index():
    """Home page."""
    try:
        stats = db.get_database_stats()
        return render_template('index.html', 
                             server_url=Config.SERVER_URL,
                             total_videos=stats['total_videos'],
                             total_views=stats['total_views'])
    except Exception as e:
        logging.error(f"Error in index: {e}")
        return render_template('index.html', 
                             server_url=Config.SERVER_URL,
                             total_videos=0,
                             total_views=0)

@app.route('/stream/<video_id>')
def stream_video(video_id):
    """Stream video page."""
    try:
        video = db.get_video(video_id)
        if not video:
            return render_template('error.html', 
                                 message="Video not found or expired",
                                 server_url=Config.SERVER_URL), 404
        
        # Increment view count
        db.increment_views(video_id)
        
        # Format created date
        created = video['created_at'].strftime('%B %d, %Y %H:%M') if 'created_at' in video else 'Unknown'
        
        return render_template(
            'video_player.html',
            video_id=video_id,
            video_name=video.get('file_name', 'Unknown'),
            video_size=video.get('file_size', 0),
            views=video.get('views', 0) + 1,
            created=created,
            username=video.get('username', 'Anonymous')
        )
    except Exception as e:
        logging.error(f"Error in stream_video: {e}")
        return render_template('error.html', 
                             message="Error loading video",
                             server_url=Config.SERVER_URL), 500

@app.route('/video/<video_id>')
def serve_video(video_id):
    """Serve video content (streaming endpoint)."""
    try:
        video = db.get_video(video_id)
        if not video:
            return "Video not found", 404
        
        # Get the file from Telegram
        bot = get_bot()
        file = bot.get_file(video['file_id'])
        
        # Get file URL from Telegram
        file_url = file.file_path
        if not file_url.startswith('http'):
            file_url = f"https://api.telegram.org/file/bot{Config.BOT_TOKEN}/{file_url}"
        
        # Create streaming response
        import requests
        from io import BytesIO
        
        # Get file size
        head_response = requests.head(file_url)
        file_size = int(head_response.headers.get('content-length', 0))
        
        # Get range header for partial content
        range_header = request.headers.get('Range', None)
        
        if range_header:
            # Parse range header
            byte1, byte2 = 0, None
            range_ = range_header.split('bytes=')[1].split('-')
            byte1 = int(range_[0])
            if range_[1]:
                byte2 = int(range_[1])
            else:
                byte2 = file_size - 1
            
            chunk_size = (byte2 - byte1) + 1
            
            # Get partial content
            headers = {'Range': f'bytes={byte1}-{byte2}'}
            response = requests.get(file_url, headers=headers, stream=True)
            
            def generate():
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            
            return Response(
                generate(),
                status=206,
                content_type=video.get('mime_type', 'video/mp4'),
                headers={
                    'Content-Range': f'bytes {byte1}-{byte2}/{file_size}',
                    'Accept-Ranges': 'bytes',
                    'Content-Length': str(chunk_size),
                    'Content-Disposition': f'inline; filename="{video.get("file_name", "video.mp4")}"'
                }
            )
        else:
            # Stream entire file
            def generate():
                response = requests.get(file_url, stream=True)
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        yield chunk
            
            return Response(
                generate(),
                content_type=video.get('mime_type', 'video/mp4'),
                headers={
                    'Content-Length': str(file_size),
                    'Accept-Ranges': 'bytes',
                    'Content-Disposition': f'inline; filename="{video.get("file_name", "video.mp4")}"'
                }
            )
    
    except Exception as e:
        logging.error(f"Error serving video {video_id}: {e}")
        return "Error serving video", 500

@app.route('/api/video/<video_id>')
def api_video_info(video_id):
    """API endpoint to get video information."""
    try:
        video = db.get_video(video_id)
        if not video:
            return jsonify({"error": "Video not found"}), 404
        
        # Convert datetime to string
        video_data = {
            'video_id': video.get('video_id'),
            'file_name': video.get('file_name'),
            'file_size': video.get('file_size'),
            'views': video.get('views', 0),
            'created_at': video.get('created_at', datetime.utcnow()).isoformat() if isinstance(video.get('created_at'), datetime) else datetime.utcnow().isoformat(),
            'stream_url': f"{Config.SERVER_URL}/stream/{video_id}",
            'direct_url': f"{Config.SERVER_URL}/video/{video_id}"
        }
        
        return jsonify(video_data)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/health')
def health_check():
    """Health check endpoint for Render."""
    try:
        # Check database connection
        db_stats = db.get_database_stats()
        return jsonify({
            'status': 'healthy',
            'database': 'connected',
            'timestamp': datetime.utcnow().isoformat(),
            'stats': db_stats
        })
    except Exception as e:
        return jsonify({
            'status': 'unhealthy',
            'error': str(e),
            'timestamp': datetime.utcnow().isoformat()
        }), 500

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Cleanup old videos (admin only)."""
    auth_token = request.headers.get('Authorization')
    if auth_token != f"Bearer {Config.ADMIN_ID}":
        return jsonify({"error": "Unauthorized"}), 401
    
    try:
        deleted_count = db.cleanup_old_data()
        return jsonify({
            "message": f"Cleaned up {deleted_count} old videos",
            "deleted": deleted_count
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.errorhandler(404)
def not_found(e):
    return render_template('error.html', 
                         message="Page not found",
                         server_url=Config.SERVER_URL), 404

@app.errorhandler(500)
def server_error(e):
    return render_template('error.html',
                         message="Internal server error",
                         server_url=Config.SERVER_URL), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
