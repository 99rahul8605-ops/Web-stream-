#!/bin/bash

# Telegram Video Stream Bot Docker Setup Script

set -e

echo "========================================="
echo "Telegram Video Stream Bot - Docker Setup"
echo "========================================="

# Check if Docker is installed
if ! command -v docker &> /dev/null; then
    echo "Docker is not installed. Please install Docker first."
    echo "Visit: https://docs.docker.com/get-docker/"
    exit 1
fi

# Check if Docker Compose is installed
if ! command -v docker-compose &> /dev/null; then
    echo "Docker Compose is not installed. Please install Docker Compose."
    echo "Visit: https://docs.docker.com/compose/install/"
    exit 1
fi

# Create environment file if it doesn't exist
if [ ! -f ".env" ]; then
    echo "Creating .env file from template..."
    cp .env.example .env
    echo ""
    echo "Please edit the .env file with your credentials:"
    echo "1. BOT_TOKEN - Get from @BotFather on Telegram"
    echo "2. ADMIN_ID - Get from @userinfobot on Telegram"
    echo "3. MONGO_URI - MongoDB connection string (optional for local)"
    echo ""
    read -p "Press Enter to continue after editing .env file..."
fi

# Create templates directory if it doesn't exist
mkdir -p templates

# Check if templates exist
if [ ! -f "templates/index.html" ]; then
    echo "Creating template files..."
    
    # Create index.html
    cat > templates/index.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Video Stream Bot</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            display: flex;
            justify-content: center;
            align-items: center;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            padding: 40px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            text-align: center;
            max-width: 500px;
            width: 100%;
        }
        h1 { color: #333; margin-bottom: 20px; }
        p { color: #666; line-height: 1.6; margin-bottom: 20px; }
        .stats {
            background: #f8f9fa;
            border-radius: 10px;
            padding: 15px;
            margin: 20px 0;
        }
        .btn {
            background: #667eea;
            color: white;
            text-decoration: none;
            padding: 12px 30px;
            border-radius: 10px;
            display: inline-block;
            font-weight: 600;
            margin: 10px;
            transition: all 0.3s ease;
        }
        .btn:hover {
            background: #5a67d8;
            transform: translateY(-2px);
            box-shadow: 0 10px 20px rgba(102, 126, 234, 0.3);
        }
        .instructions {
            text-align: left;
            margin-top: 30px;
            background: #f8f9fa;
            padding: 20px;
            border-radius: 10px;
        }
    </style>
</head>
<body>
    <div class="container">
        <h1>🎬 Video Stream Bot</h1>
        <p>Upload videos to Telegram bot and get streaming links instantly!</p>
        
        <div class="stats">
            <p>📹 Total Videos: <strong>{{ total_videos }}</strong></p>
            <p>👁️ Total Views: <strong>{{ total_views }}</strong></p>
        </div>
        
        <a href="https://t.me/your_bot_username" class="btn" target="_blank">
            Open Telegram Bot
        </a>
        
        <div class="instructions">
            <h3>How to use:</h3>
            <ol style="margin-left: 20px; margin-top: 10px;">
                <li>Open the Telegram bot</li>
                <li>Send any video file (up to 50MB)</li>
                <li>Receive a streaming link</li>
                <li>Share the link with anyone</li>
                <li>Videos auto-delete after 7 days</li>
            </ol>
        </div>
    </div>
</body>
</html>
EOF

    # Create video_player.html
    cat > templates/video_player.html << 'EOF'
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{{ video_name }} - Video Stream</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh;
            padding: 20px;
        }
        .container {
            background: white;
            border-radius: 20px;
            box-shadow: 0 20px 60px rgba(0,0,0,0.3);
            overflow: hidden;
            max-width: 800px;
            margin: 0 auto;
        }
        .header {
            background: #667eea;
            color: white;
            padding: 20px;
        }
        .video-container {
            position: relative;
            padding-bottom: 56.25%;
            height: 0;
            background: #000;
        }
        video {
            position: absolute;
            top: 0;
            left: 0;
            width: 100%;
            height: 100%;
            outline: none;
        }
        .controls {
            padding: 20px;
            background: #f8f9fa;
            text-align: center;
        }
        .btn {
            background: #667eea;
            color: white;
            border: none;
            padding: 12px 25px;
            border-radius: 10px;
            cursor: pointer;
            font-size: 1rem;
            margin: 5px;
            display: inline-block;
        }
        .info {
            padding: 15px;
            text-align: center;
            color: #666;
            font-size: 0.9rem;
        }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>{{ video_name }}</h1>
            <p>👁️ {{ views }} views | 🎬 Streaming</p>
        </div>
        
        <div class="video-container">
            <video controls autoplay playsinline>
                <source src="/video/{{ video_id }}" type="video/mp4">
                Your browser does not support video playback.
            </video>
        </div>
        
        <div class="controls">
            <button onclick="copyLink()" class="btn">📋 Copy Link</button>
            <button onclick="location.href='/'" class="btn">🏠 Home</button>
        </div>
        
        <div class="info">
            <p>Streaming via Video Stream Bot • Video ID: {{ video_id }}</p>
        </div>
    </div>

    <script>
        function copyLink() {
            const link = window.location.href;
            navigator.clipboard.writeText(link).then(() => {
                alert('✅ Link copied to clipboard!');
            });
        }
    </script>
</body>
</html>
EOF
    
    echo "Template files created."
fi

# Build and run Docker containers
echo "Building Docker image..."
docker-compose build

echo ""
echo "========================================="
echo "Setup Complete!"
echo "========================================="
echo ""
echo "To start the application, run:"
echo "  docker-compose up -d"
echo ""
echo "To view logs, run:"
echo "  docker-compose logs -f"
echo ""
echo "To stop the application, run:"
echo "  docker-compose down"
echo ""
echo "The application will be available at:"
echo "  Web Interface: http://localhost:5000"
echo "  MongoDB Admin: http://localhost:8081"
echo ""
echo "To deploy to Render:"
echo "  1. Push this code to GitHub"
echo "  2. Go to https://render.com"
echo "  3. Create a new Web Service"
echo "  4. Connect your GitHub repository"
echo "  5. Set environment variables"
echo "  6. Deploy!"
