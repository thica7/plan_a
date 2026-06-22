#!/bin/bash
set -e

echo "🚀 Starting Competiscope services..."

# Check Docker
if ! command -v docker &> /dev/null; then
    echo "❌ Docker not found. Install from https://docs.docker.com/get-docker/"
    exit 1
fi

if ! docker compose version &> /dev/null; then
    echo "❌ Docker Compose not found."
    exit 1
fi

# Start base services
echo "📦 Starting base services (postgres, temporal, qdrant)..."
docker compose up -d postgres temporal temporal-ui qdrant

# Wait for postgres healthy
echo "⏳ Waiting for postgres to be healthy..."
timeout=60
elapsed=0
until docker compose ps postgres | grep -q "(healthy)" || [ $elapsed -ge $timeout ]; do
    sleep 2
    elapsed=$((elapsed + 2))
    echo "  Waiting... ${elapsed}s/${timeout}s"
done

if [ $elapsed -ge $timeout ]; then
    echo "❌ Postgres health check timeout"
    docker compose logs postgres
    exit 1
fi

echo "✅ Postgres is healthy"

# Start app services
echo "📦 Starting app services (backend, worker, frontend, nginx)..."
docker compose up -d backend temporal-worker frontend nginx

# Wait for backend
echo "⏳ Waiting for backend..."
timeout=120
elapsed=0
until curl -sf http://localhost:8080/api/health &> /dev/null || [ $elapsed -ge $timeout ]; do
    sleep 3
    elapsed=$((elapsed + 3))
    echo "  Waiting... ${elapsed}s/${timeout}s"
done

if [ $elapsed -ge $timeout ]; then
    echo "⚠️  Backend health check timeout. Check logs:"
    docker compose logs backend --tail=50
else
    echo "✅ Backend is ready"
fi

# Status
echo ""
echo "🎉 Services started!"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📍 App:         http://localhost:8080"
echo "📍 API:         http://localhost:8080/api"
echo "📍 Temporal UI: http://localhost:8233"
echo "📍 Qdrant:      http://localhost:6333"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "Run 'docker compose logs -f' to view logs"
echo "Run 'docker compose down' to stop all services"
