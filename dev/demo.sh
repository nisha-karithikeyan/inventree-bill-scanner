#!/usr/bin/env bash
# Seed the clean demo (supplier, 12 parts with stock, sample bill).
#   dev/demo.sh            add the demo data to the current dev database
#   dev/demo.sh --fresh    move the current dev database and media to
#                          .dev/backup/<time>/ first, then start from empty
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"

if [[ "${1:-}" == "--fresh" ]]; then
  backup="$DATA/backup/$(date +%Y%m%d-%H%M%S)"
  mkdir -p "$backup"
  [[ -f "$INVENTREE_DB_NAME" ]] && mv "$INVENTREE_DB_NAME" "$backup/"
  [[ -d "$DATA/media" ]] && mv "$DATA/media" "$backup/" && mkdir -p "$DATA/media"
  echo "Previous dev data moved to $backup"
  "$PLUGIN_ROOT/dev/setup.sh"
fi

cd "$INVENTREE_SRC/src/backend/InvenTree"
"$PLUGIN_ROOT/.venv/bin/python" "$MANAGE" shell -c "
exec(open('$PLUGIN_ROOT/dev/demo.py').read())
main('$PLUGIN_ROOT')"
