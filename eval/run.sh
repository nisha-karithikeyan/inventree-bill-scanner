#!/usr/bin/env bash
# Run the accuracy evaluation against the dev instance (see eval/README.md).
#   eval/run.sh --check    validate bills and ground truth, no API call
#   eval/run.sh            send every bill in eval/bills/ to Gemini
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/../dev/env.sh"
exec "$PLUGIN_ROOT/.venv/bin/python" "$PLUGIN_ROOT/eval/run_eval.py" "$@"
