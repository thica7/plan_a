# PowerShell startup script for Competiscope
$ErrorActionPreference = "Stop"

Write-Host "🚀 Starting Competiscope services..." -ForegroundColor Cyan

# Check Docker
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) {
    Write-Host "❌ Docker not found. Install from https://docs.docker.com/get-docker/" -ForegroundColor Red
    exit 1
}

if (-not (docker compose version 2>$null)) {
    Write-Host "❌ Docker Compose not found." -ForegroundColor Red
    exit 1
}

# Start base services
Write-Host "📦 Starting base services (postgres, temporal, qdrant)..." -ForegroundColor Yellow
docker compose up -d postgres temporal temporal-ui qdrant

# Wait for postgres healthy
Write-Host "⏳ Waiting for postgres to be healthy..." -ForegroundColor Yellow
$timeout = 60
$elapsed = 0
while ($elapsed -lt $timeout) {
    $status = docker compose ps postgres 2>$null
    if ($status -match "\(healthy\)") { break }
    Start-Sleep -Seconds 2
    $elapsed += 2
    Write-Host "  Waiting... ${elapsed}s/${timeout}s"
}

if ($elapsed -ge $timeout) {
    Write-Host "❌ Postgres health check timeout" -ForegroundColor Red
    docker compose logs postgres
    exit 1
}

Write-Host "✅ Postgres is healthy" -ForegroundColor Green

# Start app services
Write-Host "📦 Starting app services (backend, worker, frontend, nginx)..." -ForegroundColor Yellow
docker compose up -d backend temporal-worker frontend nginx

# Wait for backend
Write-Host "⏳ Waiting for backend..." -ForegroundColor Yellow
$timeout = 120
$elapsed = 0
while ($elapsed -lt $timeout) {
    try {
        $response = Invoke-WebRequest -Uri "http://localhost:8080/api/health" -UseBasicParsing -TimeoutSec 2 -ErrorAction SilentlyContinue
        if ($response.StatusCode -eq 200) { break }
    } catch {}
    Start-Sleep -Seconds 3
    $elapsed += 3
    Write-Host "  Waiting... ${elapsed}s/${timeout}s"
}

if ($elapsed -ge $timeout) {
    Write-Host "⚠️  Backend health check timeout. Check logs:" -ForegroundColor Yellow
    docker compose logs backend --tail=50
} else {
    Write-Host "✅ Backend is ready" -ForegroundColor Green
}

# Status
Write-Host ""
Write-Host "🎉 Services started!" -ForegroundColor Green
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host "📍 App:         http://localhost:8080"
Write-Host "📍 API:         http://localhost:8080/api"
Write-Host "📍 Temporal UI: http://localhost:8233"
Write-Host "📍 Qdrant:      http://localhost:6333"
Write-Host "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━" -ForegroundColor Cyan
Write-Host ""
Write-Host "Run 'docker compose logs -f' to view logs"
Write-Host "Run 'docker compose down' to stop all services"
