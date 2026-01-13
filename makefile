.PHONY: help build run stop clean logs shell test deploy

help:
	@echo "Available commands:"
	@echo "  make build     - Build Docker image"
	@echo "  make run       - Run with Docker Compose"
	@echo "  make stop      - Stop Docker Compose"
	@echo "  make clean     - Remove Docker containers and images"
	@echo "  make logs      - View logs"
	@echo "  make shell     - Open shell in container"
	@echo "  make test      - Run tests"
	@echo "  make deploy    - Deploy to Render"

# Build Docker image
build:
	docker build -t telegram-video-bot .

# Run with Docker Compose
run:
	docker-compose up -d

# Stop Docker Compose
stop:
	docker-compose down

# Clean up
clean:
	docker-compose down -v
	docker system prune -f

# View logs
logs:
	docker-compose logs -f web

# Open shell in container
shell:
	docker-compose exec web bash

# Run tests
test:
	docker-compose exec web python -m pytest

# Deploy to Render
deploy:
	@echo "Deploying to Render..."
	@echo "1. Push to GitHub:"
	@echo "   git add ."
	@echo "   git commit -m 'Deploy to Render'"
	@echo "   git push"
	@echo ""
	@echo "2. Go to Render Dashboard:"
	@echo "   https://dashboard.render.com"
	@echo ""
	@echo "3. Manual deploy from latest commit"
