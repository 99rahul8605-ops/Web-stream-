import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # Telegram Bot Token from @BotFather
    BOT_TOKEN = os.getenv("BOT_TOKEN", "")
    
    # Your Telegram User ID (for admin features)
    ADMIN_ID = int(os.getenv("ADMIN_ID", 0))
    
    # Server configuration
    SERVER_URL = os.getenv("SERVER_URL", "https://your-app-name.onrender.com")
    
    # Database
    DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///videos.db")
    
    # Video settings
    MAX_FILE_SIZE = 50 * 1024 * 1024  # 50MB limit for free tier
    ALLOWED_EXTENSIONS = ['.mp4', '.avi', '.mov', '.mkv', '.webm']
    
    # Cleanup old files (days)
    CLEANUP_DAYS = 7
