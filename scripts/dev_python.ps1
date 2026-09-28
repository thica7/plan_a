# Shared interpreter discovery for project scripts; no machine-specific paths.
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
function Get-ProjectPython {
    if ($env:PYTHON_EXECUTABLE) {
        $explicit = Get-Command $env:PYTHON_EXECUTABLE -ErrorAction SilentlyContinue
        if ($explicit) { return $explicit.Source }
        throw "PYTHON_EXECUTABLE is unavailable: $env:PYTHON_EXECUTABLE"
    }
    $venvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
    if (Test-Path $venvPython) { return $venvPython }
    foreach ($candidate in @("python", "python3")) {
        $command = Get-Command $candidate -ErrorAction SilentlyContinue
        if ($command) { return $command.Source }
    }
    throw "Python 3.11+ was not found. Create .venv or set PYTHON_EXECUTABLE."
}
