#!/usr/bin/env bash
# One-time setup of the private dev InvenTree instance in .dev/.
# Creates a local superuser (default admin / admin) - for local development only.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
PY="$PLUGIN_ROOT/.venv/bin/python"
cd "$INVENTREE_SRC/src/backend/InvenTree"

"$PY" "$MANAGE" migrate --noinput
"$PY" "$MANAGE" shell -c "
from common.models import InvenTreeSetting
for key in ('ENABLE_PLUGINS_APP', 'ENABLE_PLUGINS_URL', 'ENABLE_PLUGINS_INTERFACE', 'ENABLE_PLUGINS_SCHEDULE'):
    InvenTreeSetting.set_setting(key, True, None)
from plugin import registry
registry.reload_plugins(full_reload=True, force_reload=True, collect=True)
registry.set_plugin_state('bill-scanner', True)
print('plugin active:', registry.get_plugin('bill-scanner') is not None)
"
# createsuperuser (not 'shell') so InvenTree also creates the user profile.
DJANGO_SUPERUSER_PASSWORD="${DEV_ADMIN_PASSWORD:-admin}" "$PY" "$MANAGE" createsuperuser \
  --noinput --username "${DEV_ADMIN_USER:-admin}" --email admin@example.com 2>/dev/null || true
# Second pass: the plugin app is now enabled, so its tables get created.
"$PY" "$MANAGE" migrate --noinput
"$PY" "$MANAGE" collectplugins 2>/dev/null || "$PY" "$MANAGE" shell -c "
from plugin.staticfiles import collect_plugins_static_files; collect_plugins_static_files()"
echo 'Dev instance ready. Run: dev/server.sh'
