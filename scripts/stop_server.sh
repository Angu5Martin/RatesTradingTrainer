#!/bin/bash
# Stop the Rates Trainer server that the desktop app (or launch.py) started. It stops only a server that answers /api/health as this application on this data directory;
# anything else on any port is left alone. (A server running in a Terminal window: press Ctrl-C there.)
ROOT="${RATES_TRAINER_ROOT:-$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)}"
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || PY=python3
exec "$PY" "$ROOT/scripts/launch.py" --stop "$@"
