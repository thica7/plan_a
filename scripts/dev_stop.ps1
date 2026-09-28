[CmdletBinding()]
param(
    [Nullable[int]]$BackendPort,
    [Nullable[int]]$FrontendPort,
    [Nullable[int]]$QdrantPort,
    [int]$ActiveRunLookbackHours = 6,
    [switch]$StopDocker,
    [switch]$Force
)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "dev_python.ps1")
$ProjectPython = Get-ProjectPython
$RuntimeArgs = @((Join-Path $PSScriptRoot "dev_runtime.py"), "stop", "--active-run-lookback-hours", "$ActiveRunLookbackHours")
if ($PSBoundParameters.ContainsKey("BackendPort")) { $RuntimeArgs += @("--backend-port", "$BackendPort") }
if ($PSBoundParameters.ContainsKey("FrontendPort")) { $RuntimeArgs += @("--frontend-port", "$FrontendPort") }
if ($PSBoundParameters.ContainsKey("QdrantPort")) { $RuntimeArgs += @("--qdrant-port", "$QdrantPort") }
if ($StopDocker) { $RuntimeArgs += "--stop-docker" }
if ($Force) { $RuntimeArgs += "--force" }
& $ProjectPython @RuntimeArgs
exit $LASTEXITCODE
