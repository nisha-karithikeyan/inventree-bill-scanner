#!/usr/bin/env bash
# Start the dev web server (port 8000). Run dev/worker.sh in another terminal
# to process extractions in the background; without it tasks run inline.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$INVENTREE_SRC/src/backend/InvenTree"
exec "$PLUGIN_ROOT/.venv/bin/python" "$MANAGE" runserver "${1:-127.0.0.1:8000}"
