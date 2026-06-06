$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$FrontendDir = Resolve-Path (Join-Path $ScriptDir '..')

Set-Location $FrontendDir

& pnpm openapi-typescript openapi.json -o src/api/types.ts
if ($LASTEXITCODE -ne 0) {
  exit $LASTEXITCODE
}

& git diff --exit-code -- openapi.json src/api/types.ts
exit $LASTEXITCODE
