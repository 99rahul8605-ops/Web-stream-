import os
import sys
import time

# Docker health check helper
def check_dependencies():
    """Check if all required dependencies are available"""
    try:
        import flask
        import telegram
        import pymongo
        return True
    except ImportError as e:
        print(f"Missing dependency: {e}")
        return False

# Wait for MongoDB if needed
def wait_for_mongodb():
    """Wait for MongoDB to be ready"""
    if os.getenv('MONGO_URI', '').startswith('mongodb://'):
        from pymongo import MongoClient
        from pymongo.errors import ConnectionFailure
        
        max_attempts = 30
        for attempt in range(max_attempts):
            try:
                client = MongoClient(os.getenv('MONGO_URI'), serverSelectionTimeoutMS=2000)
                client.admin.command('ping')
                print("✅ MongoDB connection successful")
                return True
            except ConnectionFailure:
                if attempt < max_attempts - 1:
                    print(f"⏳ Waiting for MongoDB... (attempt {attempt + 1}/{max_attempts})")
                    time.sleep(2)
                else:
                    print("❌ MongoDB connection failed after multiple attempts")
                    return False
    return True

# Run health checks
if __name__ != '__main__':
    # These checks run when imported (in Docker)
    if not check_dependencies():
        sys.exit(1)
    
    if not wait_for_mongodb():
        print("⚠️  MongoDB not available, using fallback mode")
