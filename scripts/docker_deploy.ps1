[CmdletBinding()]
param([switch]$Build, [switch]$NoDetach, [switch]$UrlsOnly)
$ErrorActionPreference = "Stop"
. (Join-Path $PSScriptRoot "dev_python.ps1")
$ProjectPython = Get-ProjectPython
$DeployArgs = @((Join-Path $PSScriptRoot "docker_deploy.py"))
if ($Build) { $DeployArgs += "--build" }
if ($NoDetach) { $DeployArgs += "--no-detach" }
if ($UrlsOnly) { $DeployArgs += "--urls-only" }
& $ProjectPython @DeployArgs
exit $LASTEXITCODE
