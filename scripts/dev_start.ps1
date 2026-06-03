[CmdletBinding()]
param(
    [int]$BackendPort = 8000,
    [int]$FrontendPort = 5173,
    [int]$ActiveRunLookbackHours = 6,
    [switch]$NoDocker,
    [switch]$NoClean,
    [switch]$NoHealthCheck,
    [switch]$Force
)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$Root = Split-Path -Parent $ScriptDir
$RuntimeDir = Join-Path $Root "logs\runtime"
$CondaEnvName = "bd-competiscope-v2"
$CondaRoot = "D:\Anaconda"
$PythonExe = Join-Path $CondaRoot "envs\$CondaEnvName\python.exe"
$NodeExe = "C:\Program Files\nodejs\node.exe"
$ViteJs = Join-Path $Root "frontend\node_modules\vite\bin\vite.js"

function Write-Step {
    param([string]$Message)
    Write-Host "[plan_a] $Message"
}

function Normalize-PathEnvironment {
    $pathValue = [Environment]::GetEnvironmentVariable("PATH", "Process")
    if (-not $pathValue) {
        $pathValue = [Environment]::GetEnvironmentVariable("Path", "Process")
    }

    $envDir = Split-Path -Parent $PythonExe
    $extra = @(
        $envDir,
        (Join-Path $envDir "Scripts"),
        (Join-Path $envDir "Library\bin"),
        (Join-Path $CondaRoot "Library\bin"),
        (Split-Path -Parent $NodeExe)
    ) | Where-Object { $_ -and (Test-Path $_) }

    [Environment]::SetEnvironmentVariable("PATH", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", $null, "Process")
    [Environment]::SetEnvironmentVariable("Path", (($extra + $pathValue) -join ";"), "Process")
}

function Assert-File {
    param(
        [string]$Path,
        [string]$Name
    )
    if (-not (Test-Path $Path)) {
        throw "$Name not found: $Path"
    }
}

function Test-PortCanBind {
    param([int]$Port)
    $listener = $null
    try {
        $listener = [System.Net.Sockets.TcpListener]::new(
            [System.Net.IPAddress]::Parse("127.0.0.1"),
            $Port
        )
        $listener.Start()
        return $true
    } catch {
        return $false
    } finally {
        if ($listener) {
            $listener.Stop()
        }
    }
}

function Wait-PortFree {
    param(
        [int]$Port,
        [int]$TimeoutSeconds = 20
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        if (Test-PortCanBind -Port $Port) {
            return
        }
        Start-Sleep -Milliseconds 500
    } while ((Get-Date) -lt $deadline)

    throw "Port $Port is still occupied after cleanup."
}

function Stop-PlanARuntime {
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
        Write-Step "no previous runtime processes found"
    }

    Wait-PortFree -Port $BackendPort
    Wait-PortFree -Port $FrontendPort
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

    throw "Refusing to restart while active run(s) exist: $summary. Re-run with -Force only if you intentionally want to interrupt them."
}

function Wait-HttpOk {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 40
    )
    $deadline = (Get-Date).AddSeconds($TimeoutSeconds)
    do {
        try {
            $response = Invoke-WebRequest -UseBasicParsing -Uri $Url -TimeoutSec 5
            if ($response.StatusCode -ge 200 -and $response.StatusCode -lt 300) {
                return $response
            }
        } catch {
            Start-Sleep -Milliseconds 750
        }
    } while ((Get-Date) -lt $deadline)

    throw "Timed out waiting for $Url"
}

function Start-BackgroundProcess {
    param(
        [string]$Name,
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$WorkingDirectory,
        [string]$StdoutPath,
        [string]$StderrPath
    )

    $process = Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -RedirectStandardOutput $StdoutPath `
        -RedirectStandardError $StderrPath `
        -WindowStyle Hidden `
        -PassThru

    Write-Step "$Name pid=$($process.Id)"
    return $process
}

Assert-File -Path $PythonExe -Name "Conda env python"
Assert-File -Path $NodeExe -Name "Node.js"
Assert-File -Path $ViteJs -Name "Vite entry"

New-Item -ItemType Directory -Force -Path $RuntimeDir | Out-Null
Normalize-PathEnvironment

if (-not $NoClean) {
    Stop-PlanARuntime
}

if (-not $NoDocker) {
    Write-Step "starting Docker dependencies"
    Push-Location $Root
    try {
        & docker compose up -d postgres temporal temporal-ui
    } finally {
        Pop-Location
    }
}

Write-Step "starting backend, Temporal worker, and frontend"
$backend = Start-BackgroundProcess `
    -Name "backend" `
    -FilePath $PythonExe `
    -ArgumentList @("-m", "uvicorn", "app.main:app", "--port", "$BackendPort", "--app-dir", "backend") `
    -WorkingDirectory $Root `
    -StdoutPath (Join-Path $RuntimeDir "backend.out.log") `
    -StderrPath (Join-Path $RuntimeDir "backend.err.log")

$worker = Start-BackgroundProcess `
    -Name "temporal-worker" `
    -FilePath $PythonExe `
    -ArgumentList @("backend/scripts/run_temporal_worker.py") `
    -WorkingDirectory $Root `
    -StdoutPath (Join-Path $RuntimeDir "temporal-worker.out.log") `
    -StderrPath (Join-Path $RuntimeDir "temporal-worker.err.log")

$frontend = Start-BackgroundProcess `
    -Name "frontend" `
    -FilePath $NodeExe `
    -ArgumentList @($ViteJs, "--host", "127.0.0.1") `
    -WorkingDirectory (Join-Path $Root "frontend") `
    -StdoutPath (Join-Path $RuntimeDir "frontend.out.log") `
    -StderrPath (Join-Path $RuntimeDir "frontend.err.log")

if (-not $NoHealthCheck) {
    Write-Step "waiting for health checks"
    Wait-HttpOk -Url "http://127.0.0.1:$BackendPort/api/health" | Out-Null
    $runtime = (Wait-HttpOk -Url "http://127.0.0.1:$BackendPort/api/runtime").Content | ConvertFrom-Json
    Wait-HttpOk -Url "http://127.0.0.1:$FrontendPort" | Out-Null
    Wait-HttpOk -Url "http://127.0.0.1:8233" | Out-Null

    Write-Step "backend runtime: mode=$($runtime.default_execution_mode), orchestration=$($runtime.run_orchestration_backend), temporal_percent=$($runtime.temporal_traffic_percent), demo=$($runtime.demo_mode)"
}

Write-Step "ready"
Write-Host "Frontend:    http://127.0.0.1:$FrontendPort"
Write-Host "Backend:     http://127.0.0.1:$BackendPort"
Write-Host "Temporal UI: http://127.0.0.1:8233"
