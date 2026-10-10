#!/bin/bash
# What the desktop app "Rates Trainer.app" runs: start the application in the background (or find it already running), open it in the browser, and say clearly if that
# was not possible. The logic is scripts/launch.py --detach; this wrapper finds the project and the virtualenv and, when there is no terminal (a double-click), shows an
# error as a dialog instead of printing it where nobody will see it.
#
#   scripts/app_launcher.sh [launch.py options]       RATES_TRAINER_ROOT overrides where the project is (the app sets it)
#
# Logs: ${RATES_TRAINER_LOG_DIR:-~/Library/Logs/Rates Trainer}: server.log (the server's output) and launcher.log (what this did).
# RATES_TRAINER_NO_DIALOG=1 prints errors instead of showing a dialog (used by the tests).

set -u
SRC="${BASH_SOURCE[0]}"
while [ -h "$SRC" ]; do
  DIR="$(cd -P "$(dirname "$SRC")" && pwd)"
  SRC="$(readlink "$SRC")"
  case "$SRC" in /*) ;; *) SRC="$DIR/$SRC" ;; esac
done
ROOT="${RATES_TRAINER_ROOT:-$(cd -P "$(dirname "$SRC")/.." && pwd)}"
LOGS="${RATES_TRAINER_LOG_DIR:-$HOME/Library/Logs/Rates Trainer}"
LAUNCHER_LOG="$LOGS/launcher.log"
mkdir -p "$LOGS" 2>/dev/null || LOGS=""
[ -n "$LOGS" ] && [ -f "$LAUNCHER_LOG" ] && [ "$(wc -c < "$LAUNCHER_LOG")" -gt 1000000 ] && : > "$LAUNCHER_LOG"

note() { [ -n "$LOGS" ] && printf '%s %s\n' "$(date '+%Y-%m-%d %H:%M:%S')" "$*" >> "$LAUNCHER_LOG"; return 0; }

# fail "what went wrong" "details": a dialog from the desktop app, plain text in a terminal
fail() {
  local what="$1" detail="${2:-}"
  note "FAILED: $what $detail"
  if [ -t 2 ] || [ -n "${RATES_TRAINER_NO_DIALOG:-}" ] || ! command -v osascript >/dev/null 2>&1; then
    printf 'Rates Trainer could not start: %s\n' "$what" >&2
    [ -n "$detail" ] && printf '%s\n' "$detail" >&2
    [ -n "$LOGS" ] && printf 'Logs: %s\n' "$LOGS" >&2
  else
    local text="$what"
    [ -n "$detail" ] && text="$text"$'\n\n'"$detail"
    [ -n "$LOGS" ] && text="$text"$'\n\n'"Logs: $LOGS"
    osascript - "$text" "$LOGS" <<'APPLESCRIPT' >/dev/null 2>&1
on run argv
  set theText to item 1 of argv
  set theLogs to item 2 of argv
  set theButtons to {"OK"}
  if theLogs is not "" then set theButtons to {"Open logs", "OK"}
  set answer to button returned of (display dialog theText with title "Rates Trainer" with icon caution buttons theButtons default button "OK")
  if answer is "Open logs" then do shell script "open " & quoted form of theLogs
end run
APPLESCRIPT
  fi
  exit "${3:-1}"
}

[ -f "$ROOT/trainer" ] && [ -f "$ROOT/scripts/launch.py" ] || fail "The project folder was not found." \
  "Expected it at: $ROOT"$'\n'"If you moved it, run scripts/install_launcher.sh from its new location to recreate this app." 2

export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"       # an app starts with a minimal PATH; the frontend build needs Homebrew's node
PY="$ROOT/.venv/bin/python"
[ -x "$PY" ] || fail "There is no Python environment in the project." \
  "Create it once, in $ROOT:"$'\n'"python3 -m venv .venv && .venv/bin/pip install -e '.[ui]'" 2

cd "$ROOT" || fail "Cannot enter $ROOT."
note "launching: $PY scripts/launch.py --detach $*"
OUT="$(mktemp -t rates-trainer-launch)"
trap 'rm -f "$OUT"' EXIT
"$PY" "$ROOT/scripts/launch.py" --detach "$@" > "$OUT" 2>&1
code=$?
[ -n "$LOGS" ] && cat "$OUT" >> "$LAUNCHER_LOG"
if [ "$code" -ne 0 ]; then
  # the launcher's own explanation (what it printed to stderr last), without the progress lines before it
  detail="$(grep -v -e '^Rates Trainer$' -e '^Project: ' -e '^Data: ' -e '^Starting the server' "$OUT" | grep -v '^$' | tail -n 14)"
  fail "It did not start (exit code $code)." "$detail" "$code"
fi
cat "$OUT"
note "ok"
exit 0
