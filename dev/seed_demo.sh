#!/usr/bin/env bash
# Load fictional demo data into the dev instance (run dev/setup.sh first).
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$INVENTREE_SRC/src/backend/InvenTree"
"$PLUGIN_ROOT/.venv/bin/python" "$MANAGE" shell -c "exec(open('$PLUGIN_ROOT/dev/seed_demo.py').read())"
