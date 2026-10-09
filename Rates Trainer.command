#!/bin/bash
# Rates Trainer: double-click to start the application and open it in your browser (macOS).
# It finds the project from its own location (following symlinks), uses the project's .venv, builds the frontend only if its sources changed,
# starts `./trainer ui`, and opens http://127.0.0.1:8765 once the server answers. Stop it with Ctrl-C in this window, or close the window.
# The logic is in scripts/launch.py. RATES_TRAINER_ROOT overrides where the project is (the Desktop copy sets it).

pause() { if [ -t 0 ]; then echo; read -r -p "Press Return to close this window. " _; fi; }

SRC="${BASH_SOURCE[0]}"
while [ -h "$SRC" ]; do
  DIR="$(cd -P "$(dirname "$SRC")" && pwd)"
  SRC="$(readlink "$SRC")"
  case "$SRC" in /*) ;; *) SRC="$DIR/$SRC" ;; esac
done
ROOT="${RATES_TRAINER_ROOT:-$(cd -P "$(dirname "$SRC")" && pwd)}"

if [ ! -f "$ROOT/trainer" ] || [ ! -f "$ROOT/scripts/launch.py" ]; then
  echo "Rates Trainer: the project folder was not found at: $ROOT"
  echo "If you moved it, run  scripts/install_launcher.sh  from its new location to refresh the Desktop launcher."
  pause; exit 2
fi
cd "$ROOT" || { echo "Rates Trainer: cannot enter $ROOT"; pause; exit 2; }

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"     # a double-clicked script may not see Homebrew's node
PY="$ROOT/.venv/bin/python"
if [ ! -x "$PY" ]; then
  echo "Rates Trainer: no Python environment at $ROOT/.venv"
  echo "Create it once, in the project folder:"
  echo "    python3 -m venv .venv && .venv/bin/pip install -e '.[ui]'"
  pause; exit 2
fi

"$PY" "$ROOT/scripts/launch.py" "$@"
code=$?
if [ "$code" -ne 0 ]; then
  echo
  echo "Rates Trainer did not start (exit code $code). The messages above say why."
  pause
fi
exit "$code"
