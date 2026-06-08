[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [int]$ActiveRunLookbackHours = 6,
    [switch]$StopDocker,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$RuntimeDir = Join-Path $Root "logs\runtime"
$CondaEnvName = "bd-competiscope-v2"

function Write-Step {
    param([string]$Message)
    Write-Host "[plan_a] $Message"
}

function Get-ActiveRuns {
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$BackendPort/api/runs" -TimeoutSec 5
        $runs = $response.Content | ConvertFrom-Json
        $cutoff = [DateTimeOffset]::UtcNow.AddHours(-1 * $ActiveRunLookbackHours)
        return @($runs | Where-Object {
            if ($_.status -notin @("queued", "running")) {
                return $false
            }
            $timestamp = $_.updated_at
            if (-not $timestamp) {
                $timestamp = $_.created_at
            }
            if (-not $timestamp) {
                return $true
            }
            try {
                return (Convert-RunTimestamp $timestamp) -ge $cutoff
            } catch {
                return $true
            }
        })
    } catch {
        return @()
    }
}

function Convert-RunTimestamp {
    param([string]$Timestamp)
    $styles = [System.Globalization.DateTimeStyles]::AssumeUniversal -bor
        [System.Globalization.DateTimeStyles]::AdjustToUniversal
    return [DateTimeOffset]::Parse($Timestamp, [System.Globalization.CultureInfo]::InvariantCulture, $styles)
}

function Assert-NoActiveRuns {
    $activeRuns = @(Get-ActiveRuns)
    if ($activeRuns.Count -eq 0) {
        return
    }

    $summary = ($activeRuns | Select-Object -First 5 | ForEach-Object {
        "$($_.id) status=$($_.status) topic=$($_.topic)"
    }) -join "; "

    throw "Refusing to stop while active run(s) exist: $summary. Re-run with -Force only if you intentionally want to interrupt them."
}

if (-not $Force) {
    Assert-NoActiveRuns
}

$currentPid = $PID
$patterns = @(
    "cmd\.exe.*conda run -n $CondaEnvName",
    "cmd\.exe.*pnpm\.cmd dev",
    "conda.*run -n $CondaEnvName",
    "uvicorn.*app\.main:app",
    "run_temporal_worker\.py",
    "vite\.js.*--host",
    "node_modules.*vite",
    "spawn_main\(parent_pid=",
    [regex]::Escape((Join-Path $RuntimeDir "backend.cmd")),
    [regex]::Escape((Join-Path $RuntimeDir "temporal-worker.cmd")),
    [regex]::Escape((Join-Path $RuntimeDir "frontend.cmd"))
)

$targets = @(Get-CimInstance Win32_Process | Where-Object {
    $cmd = $_.CommandLine
    $_.ProcessId -ne $currentPid -and $cmd -and ($patterns | Where-Object { $cmd -match $_ })
})

$portOwners = @(Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -ErrorAction SilentlyContinue |
    Where-Object { $_.OwningProcess -ne 0 } |
    Select-Object -ExpandProperty OwningProcess -Unique)

$ids = @($targets.ProcessId + $portOwners |
    Where-Object { $_ -and $_ -ne $currentPid } |
    Select-Object -Unique)

foreach ($id in $ids) {
    Stop-Process -Id $id -Force -ErrorAction SilentlyContinue
}

if ($ids.Count -gt 0) {
    Write-Step ("stopped runtime pids: " + (($ids | ForEach-Object { [string]$_ }) -join ", "))
} else {
    Write-Step "no runtime processes found"
}

if ($StopDocker) {
    Write-Step "stopping Docker dependencies"
    Push-Location $Root
    try {
        & docker compose stop temporal-ui temporal postgres
    } finally {
        Pop-Location
    }
}

Write-Step "stopped"
