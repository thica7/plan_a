#!/usr/bin/env bash
set -euo pipefail
source "$(dirname -- "$0")/dev_python.sh"
exec "$ProjectPython" "$ProjectRoot/scripts/dev_runtime.py" stop "$@"
