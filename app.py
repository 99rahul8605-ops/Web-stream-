import os
import uuid
import logging
from datetime import datetime, timedelta
from flask import Flask, render_template, Response, jsonify, request
from telegram import Bot
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
app.secret_key = os.getenv("SECRET_KEY", "your-secret-key-here")

# Configuration
class Config:
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
    SERVER_URL = os.getenv("SERVER_URL", "https://web-stream-1.onrender.com")
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB

# Simple in-memory storage with automatic cleanup
class VideoStorage:
    def __init__(self):
        self.videos = OrderedDict()
        self.stats = {
            "total_videos": 0,
            "total_views": 0,
            "start_time": datetime.now().isoformat()
        }
    
    def add_video(self, video_data):
        """Add a video to storage"""
        video_id = video_data.get('video_id')
        if video_id:
            self.videos[video_id] = video_data
            self.stats["total_videos"] += 1
            logger.info(f"✅ Video added: {video_id}")
            return True
        return False
    
    def get_video(self, video_id):
        """Get video by ID"""
        # Clean old videos first
        self.cleanup_old_videos()
        return self.videos.get(video_id)
    
    def increment_views(self, video_id):
        """Increment view count"""
        video = self.videos.get(video_id)
        if video:
            video['views'] = video.get('views', 0) + 1
            self.stats["total_views"] += 1
            return True
        return False
    
    def cleanup_old_videos(self, max_age_hours=168):  # 7 days
        """Remove videos older than max_age_hours"""
        now = datetime.now()
        videos_to_delete = []
        
        for video_id, video in self.videos.items():
            created_str = video.get('created_at')
            if created_str:
                try:
                    created = datetime.fromisoformat(created_str)
                    age_hours = (now - created).total_seconds() / 3600
                    if age_hours > max_age_hours:
                        videos_to_delete.append(video_id)
                except:
                    pass
        
        for video_id in videos_to_delete:
            del self.videos[video_id]
        
        if videos_to_delete:
            self.stats["total_videos"] -= len(videos_to_delete)
            logger.info(f"🧹 Cleaned up {len(videos_to_delete)} old videos")
        
        return len(videos_to_delete)
    
    def get_stats(self):
        """Get storage statistics"""
        self.cleanup_old_videos()  # Clean up before returning stats
        return {
            "total_videos": len(self.videos),
            "total_views": self.stats["total_views"],
            "status": "active"
        }

# Initialize storage
storage = VideoStorage()

# Flask Routes
@app.route('/')
def index():
    """Home page"""
    stats = storage.get_stats()
    return render_template('index.html',
                         server_url=Config.SERVER_URL,
                         total_videos=stats['total_videos'],
                         total_views=stats['total_views'])

@app.route('/stream/<video_id>')
def stream_video(video_id):
    """Video player page"""
    video = storage.get_video(video_id)
    if not video:
        return render_template('error.html', 
                             message="Video not found or expired",
                             server_url=Config.SERVER_URL), 404
    
    storage.increment_views(video_id)
    
    # Format date
    created = video.get('created_at', '')
    if created:
        try:
            created_dt = datetime.fromisoformat(created)
            created = created_dt.strftime('%B %d, %Y %H:%M')
        except:
            created = 'Recently'
    
    size_mb = video.get('file_size', 0) / (1024 * 1024)
    
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
    video = storage.get_video(video_id)
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
        
        # Check if client supports range requests
        range_header = request.headers.get('Range')
        
        if range_header:
            # Handle range request for seeking
            headers = {'Range': range_header}
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
                    'Content-Range': response.headers.get('Content-Range'),
                    'Accept-Ranges': 'bytes',
                    'Content-Length': response.headers.get('Content-Length'),
                    'Content-Disposition': f'inline; filename="{video.get("file_name", "video.mp4")}"'
                }
            )
        else:
            # Full video stream
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
        logger.error(f"❌ Error serving video: {e}")
        return "Error serving video", 500

@app.route('/health')
def health():
    """Health check endpoint"""
    stats = storage.get_stats()
    return jsonify({
        "status": "healthy",
        "timestamp": datetime.now().isoformat(),
        "server": Config.SERVER_URL,
        "storage": "memory",
        "videos": stats['total_videos'],
        "views": stats['total_views'],
        "bot": "enabled" if Config.BOT_TOKEN else "disabled"
    })

@app.route('/api/video/<video_id>')
def video_info(video_id):
    """Get video info"""
    video = storage.get_video(video_id)
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

@app.route('/api/save_video', methods=['POST'])
def save_video():
    """API endpoint to save video metadata"""
    try:
        data = request.json
        if not data:
            return jsonify({"error": "No data provided"}), 400
        
        video_id = data.get('video_id')
        if not video_id:
            return jsonify({"error": "video_id is required"}), 400
        
        # Ensure required fields
        required_fields = ['file_id', 'file_name', 'file_size', 'user_id']
        for field in required_fields:
            if field not in data:
                return jsonify({"error": f"{field} is required"}), 400
        
        # Add timestamp if not present
        if 'created_at' not in data:
            data['created_at'] = datetime.now().isoformat()
        
        # Add default values
        data.setdefault('views', 0)
        data.setdefault('mime_type', 'video/mp4')
        
        # Save video
        success = storage.add_video(data)
        
        if success:
            return jsonify({
                "status": "success",
                "video_id": video_id,
                "stream_url": f"{Config.SERVER_URL}/stream/{video_id}"
            })
        else:
            return jsonify({"error": "Failed to save video"}), 500
            
    except Exception as e:
        logger.error(f"❌ Error saving video: {e}")
        return jsonify({"error": str(e)}), 500

@app.route('/stats')
def stats_page():
    """Statistics page"""
    stats = storage.get_stats()
    return jsonify({
        "server": Config.SERVER_URL,
        "total_videos": stats['total_videos'],
        "total_views": stats['total_views'],
        "uptime": storage.stats.get('start_time', 'Unknown'),
        "status": "running"
    })

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

# Background cleanup thread
def cleanup_thread():
    """Background thread to cleanup old videos"""
    while True:
        try:
            deleted = storage.cleanup_old_videos()
            if deleted:
                logger.info(f"🧹 Cleaned up {deleted} old videos")
            time.sleep(3600)  # Run every hour
        except Exception as e:
            logger.error(f"Cleanup thread error: {e}")
            time.sleep(300)

# Start cleanup thread
import threading
cleanup_worker = threading.Thread(target=cleanup_thread, daemon=True)
cleanup_worker.start()

# Main entry point
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    logger.info(f"🚀 Starting Flask app on port {port}")
    logger.info(f"🌐 Server URL: {Config.SERVER_URL}")
    logger.info(f"🤖 Bot Token: {'Set' if Config.BOT_TOKEN else 'Not set'}")
    app.run(host='0.0.0.0', port=port, debug=False)
