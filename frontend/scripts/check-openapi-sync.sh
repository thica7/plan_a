#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "$0")/.."

pnpm openapi-typescript openapi.json -o src/api/types.ts
git diff --exit-code -- openapi.json src/api/types.ts
