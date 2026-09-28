#!/usr/bin/env bash
# Sourced by project scripts to resolve the workspace and interpreter.
ProjectRoot="$(CDPATH= cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
if [[ -n "${PYTHON_EXECUTABLE:-}" ]]; then
    ProjectPython="$PYTHON_EXECUTABLE"
elif [[ -x "$ProjectRoot/.venv/bin/python" ]]; then
    ProjectPython="$ProjectRoot/.venv/bin/python"
else
    ProjectPython="$(command -v python3 || true)"
fi
if [[ -z "$ProjectPython" ]]; then
    echo "Python 3.11+ was not found. Create .venv or set PYTHON_EXECUTABLE." >&2
    exit 1
fi
