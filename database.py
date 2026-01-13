from pymongo import MongoClient, DESCENDING
from datetime import datetime, timedelta
from config import Config
import logging

class Database:
    def __init__(self):
        self.client = MongoClient(Config.MONGO_URI)
        self.db = self.client[Config.DATABASE_NAME]
        self.videos = self.db.videos
        self.users = self.db.users
        self.setup_indexes()
    
    def setup_indexes(self):
        """Create necessary indexes for performance"""
        # TTL index for auto-deleting old videos
        self.videos.create_index("created_at", expireAfterSeconds=Config.CLEANUP_DAYS * 24 * 3600)
        
        # Indexes for common queries
        self.videos.create_index("user_id")
        self.videos.create_index("video_id", unique=True)
        self.videos.create_index([("user_id", DESCENDING), ("created_at", DESCENDING)])
        
        # Users index
        self.users.create_index("telegram_id", unique=True)
    
    def add_video(self, video_data):
        """Add a new video to database"""
        try:
            video_data['created_at'] = datetime.utcnow()
            video_data['views'] = 0
            result = self.videos.insert_one(video_data)
            return str(result.inserted_id)
        except Exception as e:
            logging.error(f"Error adding video: {e}")
            return None
    
    def get_video(self, video_id):
        """Get video by video_id"""
        return self.videos.find_one({"video_id": video_id})
    
    def get_video_by_telegram_id(self, file_id):
        """Get video by Telegram file_id"""
        return self.videos.find_one({"file_id": file_id})
    
    def increment_views(self, video_id):
        """Increment view count for a video"""
        self.videos.update_one(
            {"video_id": video_id},
            {"$inc": {"views": 1}}
        )
    
    def get_user_videos(self, user_id, limit=20):
        """Get all videos uploaded by a user"""
        return list(self.videos.find(
            {"user_id": user_id}
        ).sort("created_at", DESCENDING).limit(limit))
    
    def delete_video(self, video_id, user_id=None):
        """Delete a video"""
        query = {"video_id": video_id}
        if user_id:
            query["user_id"] = user_id
        
        result = self.videos.delete_one(query)
        return result.deleted_count > 0
    
    def count_user_videos(self, user_id):
        """Count videos uploaded by a user"""
        return self.videos.count_documents({"user_id": user_id})
    
    def get_all_videos_count(self):
        """Get total videos count"""
        return self.videos.count_documents({})
    
    def get_total_views(self):
        """Get total views across all videos"""
        pipeline = [
            {"$group": {"_id": None, "total_views": {"$sum": "$views"}}}
        ]
        result = list(self.videos.aggregate(pipeline))
        return result[0]["total_views"] if result else 0
    
    def add_user(self, user_data):
        """Add or update user information"""
        self.users.update_one(
            {"telegram_id": user_data["telegram_id"]},
            {"$set": user_data},
            upsert=True
        )
    
    def get_user(self, telegram_id):
        """Get user by Telegram ID"""
        return self.users.find_one({"telegram_id": telegram_id})
    
    def update_user_stats(self, telegram_id):
        """Update user statistics"""
        video_count = self.count_user_videos(telegram_id)
        self.users.update_one(
            {"telegram_id": telegram_id},
            {"$set": {"video_count": video_count, "last_active": datetime.utcnow()}}
        )
    
    def cleanup_old_data(self):
        """Manual cleanup of old data (optional)"""
        cutoff = datetime.utcnow() - timedelta(days=Config.CLEANUP_DAYS)
        result = self.videos.delete_many({"created_at": {"$lt": cutoff}})
        return result.deleted_count
    
    def get_database_stats(self):
        """Get database statistics"""
        return {
            "total_videos": self.get_all_videos_count(),
            "total_views": self.get_total_views(),
            "total_users": self.users.count_documents({})
        }

# Singleton database instance
db = Database()
