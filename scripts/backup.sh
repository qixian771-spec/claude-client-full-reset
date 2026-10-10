#!/usr/bin/env bash
# Compatibility entry point. Missing Python or script errors stop immediately.
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "$0")" && pwd)"
exec python3 "$SCRIPT_DIR/backup.py" "$@"
