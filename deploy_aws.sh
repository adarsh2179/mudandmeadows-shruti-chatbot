#!/usr/bin/env bash
# ==============================================================================
# AWS Free Tier Deployment Automation Script
# Deploys Mud & Meadows AI Concierge to AWS (EC2 / Lightsail / App Runner)
# ==============================================================================

set -e

echo "🚀 Starting Mud & Meadows Concierge AWS Deployment..."

# 1. Check Docker installation
if ! command -v docker &> /dev/null; then
    echo "📦 Docker not found. Installing Docker engine..."
    sudo apt-get update
    sudo apt-get install -y ca-certificates curl gnupg lsb-release
    sudo mkdir -p /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" | sudo tee /etc/apt/sources.list.d/docker.list > /dev/null
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
    sudo usermod -aG docker $USER
    echo "✅ Docker successfully installed."
fi

# 2. Verify .env file exists
if [ ! -f .env ]; then
    echo "⚠️ .env file not found! Copying from .env.example..."
    cp .env.example .env
    echo "❗ Please edit .env with your live GEMINI_API_KEY before starting."
    exit 1
fi

# 3. Build & launch with Docker Compose
echo "🔨 Building Docker image..."
docker compose build --no-cache

echo "🚀 Starting containerized services in background..."
docker compose down || true
docker compose up -d

# 4. Healthcheck verification
echo "⏳ Waiting for health check verification on http://localhost:8000/health..."
sleep 5
curl -f http://localhost:8000/health || (echo "❌ Healthcheck failed!" && exit 1)

echo "🎉 Deployment Successful!"
echo "🌐 Chatbot Widget is live and listening on port 8000."
