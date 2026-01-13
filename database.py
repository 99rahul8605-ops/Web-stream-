import sqlite3
import datetime
from contextlib import contextmanager

class Database:
    def __init__(self, db_path="videos.db"):
        self.db_path = db_path
        self.init_db()
    
    @contextmanager
    def get_connection(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()
    
    def init_db(self):
        with self.get_connection() as conn:
            conn.execute('''
                CREATE TABLE IF NOT EXISTS videos (
                    id TEXT PRIMARY KEY,
                    file_id TEXT NOT NULL,
                    file_name TEXT,
                    file_size INTEGER,
                    mime_type TEXT,
                    user_id INTEGER,
                    chat_id INTEGER,
                    message_id INTEGER,
                    views INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
    
    def add_video(self, video_id, file_id, file_name, file_size, mime_type, user_id, chat_id, message_id):
        with self.get_connection() as conn:
            conn.execute('''
                INSERT INTO videos (id, file_id, file_name, file_size, mime_type, user_id, chat_id, message_id)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ''', (video_id, file_id, file_name, file_size, mime_type, user_id, chat_id, message_id))
    
    def get_video(self, video_id):
        with self.get_connection() as conn:
            cursor = conn.execute('SELECT * FROM videos WHERE id = ?', (video_id,))
            return cursor.fetchone()
    
    def increment_views(self, video_id):
        with self.get_connection() as conn:
            conn.execute('UPDATE videos SET views = views + 1 WHERE id = ?', (video_id,))
    
    def get_user_videos(self, user_id, limit=50):
        with self.get_connection() as conn:
            cursor = conn.execute(
                'SELECT * FROM videos WHERE user_id = ? ORDER BY created_at DESC LIMIT ?',
                (user_id, limit)
            )
            return cursor.fetchall()
    
    def delete_old_videos(self, days=7):
        with self.get_connection() as conn:
            cutoff = datetime.datetime.now() - datetime.timedelta(days=days)
            conn.execute('DELETE FROM videos WHERE created_at < ?', (cutoff,))
            return conn.total_changes
