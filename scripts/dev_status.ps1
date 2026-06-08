[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [int]$ActiveRunLookbackHours = 6
)

$ErrorActionPreference = "Continue"

function Convert-RunTimestamp {
    param([string]$Timestamp)
    $styles = [System.Globalization.DateTimeStyles]::AssumeUniversal -bor
        [System.Globalization.DateTimeStyles]::AdjustToUniversal
    return [DateTimeOffset]::Parse($Timestamp, [System.Globalization.CultureInfo]::InvariantCulture, $styles)
}

function Test-Http {
    param([string]$Url)
    try {
        $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
        return [PSCustomObject]@{ url = $Url; status = $response.StatusCode }
    } catch {
        return [PSCustomObject]@{ url = $Url; status = "ERR"; error = $_.Exception.Message }
    }
}

Write-Host "[plan_a] HTTP"
Test-Http -Url "http://127.0.0.1:$BackendPort/api/health" | Format-List
Test-Http -Url "http://127.0.0.1:$FrontendPort" | Format-List
Test-Http -Url "http://127.0.0.1:8233" | Format-List

try {
    $runtime = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$BackendPort/api/runtime" -TimeoutSec 5).Content | ConvertFrom-Json
    [PSCustomObject]@{
        default_execution_mode = $runtime.default_execution_mode
        run_orchestration_backend = $runtime.run_orchestration_backend
        temporal_traffic_percent = $runtime.temporal_traffic_percent
        demo_mode = $runtime.demo_mode
        web_search_provider = $runtime.web_search_provider
    } | Format-List
} catch {
    Write-Warning "runtime endpoint unavailable: $($_.Exception.Message)"
}

Write-Host "[plan_a] Active runs"
try {
    $runs = (Invoke-WebRequest -UseBasicParsing -Uri "http://127.0.0.1:$BackendPort/api/runs" -TimeoutSec 5).Content | ConvertFrom-Json
    $cutoff = [DateTimeOffset]::UtcNow.AddHours(-1 * $ActiveRunLookbackHours)
    $activeRuns = @($runs | Where-Object {
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
    if ($activeRuns.Count -eq 0) {
        Write-Host "none"
    } else {
        $activeRuns |
            Select-Object id, status, topic, created_at, updated_at |
            Format-Table -AutoSize
    }
} catch {
    Write-Warning "run list unavailable: $($_.Exception.Message)"
}

Write-Host "[plan_a] Ports"
foreach ($port in @($BackendPort, $FrontendPort, 7233, 8233, 55432)) {
    Get-NetTCPConnection -LocalPort $port -ErrorAction SilentlyContinue |
        Where-Object { $_.State -eq "Listen" } |
        Select-Object @{n = "Port"; e = { $port } }, OwningProcess
}

Write-Host "[plan_a] Service owners"
$owners = @(Get-NetTCPConnection -LocalPort $BackendPort, $FrontendPort -ErrorAction SilentlyContinue |
    Where-Object { $_.State -eq "Listen" -and $_.OwningProcess -ne 0 } |
    Select-Object -ExpandProperty OwningProcess -Unique)

Get-CimInstance Win32_Process |
    Where-Object { $_.ProcessId -in $owners } |
    Select-Object ProcessId, Name, CommandLine |
    Format-List

Write-Host "[plan_a] Runtime chain"
Get-CimInstance Win32_Process |
    Where-Object {
        $_.CommandLine -and (
            $_.CommandLine -match "uvicorn.*app\.main:app" -or
            $_.CommandLine -match "run_temporal_worker\.py" -or
            $_.CommandLine -match "vite\.js.*--host" -or
            $_.CommandLine -match "spawn_main\(parent_pid="
        )
    } |
    Select-Object ProcessId, ParentProcessId, Name, CommandLine |
    Format-List

Write-Host "[plan_a] Docker"
Push-Location (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path))
try {
    & docker compose ps
} finally {
    Pop-Location
}
