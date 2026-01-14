#!/bin/bash

# Run both Flask app and Telegram bot
echo "🚀 Starting Video Stream Bot..."

# Start Flask app in background
python app.py &
FLASK_PID=$!

# Start Telegram bot
python bot.py &
BOT_PID=$!

# Wait for both processes
wait $FLASK_PID $BOT_PID
