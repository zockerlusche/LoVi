#!/bin/bash
set -e

echo "🚀 LoVi Deploy Script"
echo "===================="

# Git Push
echo ""
echo "📦 Pushing to GitHub..."
cd /opt/docker/logviewer
git add .
git commit -m "LoVi Update $(date '+%Y-%m-%d %H:%M')" || echo "Nichts zu committen"
git push

# Docker neu bauen
echo ""
echo "🐳 Building Docker image..."
docker build -t lovi-local .

# Container neu starten
echo ""
echo "🔄 Restarting container..."
docker stop lovi
docker rm lovi
docker run -d --name lovi \
  --restart unless-stopped \
  -p 8095:5000 \
  -v /opt/docker/logs:/logs \
  -v /opt/docker/lovi/data:/data \
  -e TZ=Europe/Berlin \
  lovi-local

echo ""
echo "✅ Done! LoVi läuft auf http://localhost:8095"
