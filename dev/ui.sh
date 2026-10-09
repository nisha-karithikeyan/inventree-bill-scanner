#!/usr/bin/env bash
# Start InvenTree's React UI (Vite, port 5173) for the dev instance.
# The frontend is copied into .dev/ so node_modules and compiled translations
# are never written into the InvenTree source tree. Needs dev/server.sh too.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
UI="$DATA/inventree-frontend"
mkdir -p "$UI"
rsync -a --exclude node_modules --exclude 'src/locales/*/messages.ts' \
  "$INVENTREE_SRC/src/frontend/" "$UI/"
cd "$UI"
[[ -d node_modules ]] || yarn install --frozen-lockfile
yarn run compile
exec yarn run dev --host 127.0.0.1
