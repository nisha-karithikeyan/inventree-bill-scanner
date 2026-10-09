#!/usr/bin/env bash
# Start the django-q2 background worker for the dev instance.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
cd "$INVENTREE_SRC/src/backend/InvenTree"
exec "$PLUGIN_ROOT/.venv/bin/python" "$MANAGE" qcluster
