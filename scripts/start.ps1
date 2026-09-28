# Compatibility entry for the full Compose stack.
& (Join-Path $PSScriptRoot "docker_deploy.ps1") @args
exit $LASTEXITCODE
