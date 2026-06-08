param(
    [switch]$Build,
    [switch]$NoDetach
)

$ErrorActionPreference = "Stop"
$root = Resolve-Path (Join-Path $PSScriptRoot "..")
Set-Location $root

if (-not (Test-Path ".env")) {
    Copy-Item ".env.example" ".env"
    Write-Host "Created .env from .env.example. Edit .env to add real API keys before real runs." -ForegroundColor Yellow
}

$composeArgs = @("compose", "up")
if (-not $NoDetach) {
    $composeArgs += "-d"
}
if ($Build) {
    $composeArgs += "--build"
}

& docker @composeArgs
if ($LASTEXITCODE -ne 0) {
    throw "docker compose up failed."
}

Write-Host ""
Write-Host "Competiscope is starting:" -ForegroundColor Green
Write-Host "  App:         http://localhost:8080"
Write-Host "  Backend:     http://localhost:8080/api/health"
Write-Host "  Temporal UI: http://127.0.0.1:8233"
Write-Host ""
Write-Host "Logs: docker compose logs -f --tail=100"
