#!/usr/bin/env bash
# Run the plugin test suite inside InvenTree's Django test runner.
#   dev/test.sh                     run everything
#   dev/test.sh bill_scanner.tests.test_plugin
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/env.sh"
export INVENTREE_PLUGIN_TESTING=True INVENTREE_PLUGIN_TESTING_SETUP=True
PY="$PLUGIN_ROOT/.venv/bin/python"
cd "$INVENTREE_SRC/src/backend/InvenTree"
# InvenTree reads the dev database at startup to load plugins. On a fresh
# clone (or in CI) it does not exist yet, and without it the plugin's app is
# never registered, so create it first.
if [[ ! -f "$INVENTREE_DB_NAME" ]]; then
  "$PY" "$MANAGE" migrate --noinput
fi
export COVERAGE_FILE="$PLUGIN_ROOT/.coverage"
if [[ "${COVERAGE:-0}" == "1" ]]; then
  "$PY" -m coverage run --rcfile="$PLUGIN_ROOT/.coveragerc" "$MANAGE" test --noinput "${@:-bill_scanner}"
  "$PY" -m coverage report --rcfile="$PLUGIN_ROOT/.coveragerc"
else
  "$PY" "$MANAGE" test --noinput "${@:-bill_scanner}"
fi
