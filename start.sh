#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
: "${TELEGRAM_BOT_TOKEN:?Set TELEGRAM_BOT_TOKEN in environment settings}"
: "${TELEGRAM_CHAT_ID:?Set TELEGRAM_CHAT_ID in environment settings}"
: "${DASHBOARD_PASSWORD:?Set a strong DASHBOARD_PASSWORD in environment settings}"
export SCANNER_DB="${SCANNER_DB:-$PWD/data/live.sqlite3}"
python_bin="${SCANNER_PYTHON:-python3}"
"$python_bin" scanner.py --check-live
# The preflight above prevents deploying a healthy-looking dashboard on broken inputs.
"$python_bin" scanner.py --db "$SCANNER_DB" &
scanner_pid=$!
"$python_bin" -m gunicorn --bind "0.0.0.0:${PORT:-8000}" --workers 1 --threads 4 --access-logfile - dashboard:app &
web_pid=$!
cleanup() { kill "$scanner_pid" "$web_pid" 2>/dev/null || true; wait "$scanner_pid" "$web_pid" 2>/dev/null || true; }
trap cleanup EXIT
trap 'exit 0' TERM INT
# If either process dies, exit; hosting supervisor restarts the service.
set +e
wait -n "$scanner_pid" "$web_pid"
exit_status=$?
set -e
if [ "$exit_status" -eq 0 ]; then exit_status=1; fi
exit "$exit_status"
