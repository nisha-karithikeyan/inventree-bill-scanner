#!/usr/bin/env bash
# Source this file to point an InvenTree checkout at a private data folder.
# Nothing is written inside the InvenTree source tree.
#
#   export INVENTREE_SRC=/path/to/InvenTree   (default: ../InvenTree)
#   source dev/env.sh

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
export INVENTREE_SRC="${INVENTREE_SRC:-$(cd "$PLUGIN_ROOT/../InvenTree" && pwd)}"
DATA="$PLUGIN_ROOT/.dev"
mkdir -p "$DATA/media" "$DATA/static" "$DATA/backup"

export INVENTREE_CONFIG_FILE="$DATA/config.yaml"
export INVENTREE_DB_ENGINE=sqlite3
export INVENTREE_DB_NAME="$DATA/inventree.sqlite3"
export INVENTREE_MEDIA_ROOT="$DATA/media"
export INVENTREE_STATIC_ROOT="$DATA/static"
export INVENTREE_BACKUP_DIR="$DATA/backup"
export INVENTREE_SECRET_KEY_FILE="$DATA/secret_key.txt"
export INVENTREE_OIDC_PRIVATE_KEY_FILE="$DATA/oidc.pem"
export INVENTREE_PLUGIN_FILE="$DATA/plugins.txt"
export INVENTREE_PLUGINS_ENABLED=True
export INVENTREE_DEBUG=True
export INVENTREE_SITE_URL="${INVENTREE_SITE_URL:-http://localhost:8000}"
export PYTHONDONTWRITEBYTECODE=1

touch "$INVENTREE_PLUGIN_FILE"
export MANAGE="$INVENTREE_SRC/src/backend/InvenTree/manage.py"
