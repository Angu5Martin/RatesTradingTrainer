#!/bin/bash
# One-time setup: put a launcher on the Desktop.   scripts/install_launcher.sh [--dest DIR] [--root DIR] [--force]
# The Desktop file is a few lines that point at this project's "Rates Trainer.command", so later updates to the launcher need no reinstall.
# It never overwrites a file it did not create (without --force) and touches nothing else.
set -eu
ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HOME/Desktop"
FORCE=0
while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --root) ROOT="$(cd -P "$2" && pwd)"; shift 2 ;;
    --force) FORCE=1; shift ;;
    -h|--help) sed -n '2,4p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
MARK="# rates-trainer-launcher"
TARGET="$DEST/Rates Trainer.command"

[ -f "$ROOT/Rates Trainer.command" ] || { echo "Not found: $ROOT/Rates Trainer.command" >&2; exit 1; }
[ -d "$DEST" ] || { echo "Destination folder does not exist: $DEST" >&2; exit 1; }
if [ -e "$TARGET" ] && ! grep -q "^$MARK" "$TARGET" 2>/dev/null && [ "$FORCE" -ne 1 ]; then
  echo "$TARGET already exists and was not created by this installer; not overwriting it (use --force to replace it)." >&2
  exit 1
fi

chmod +x "$ROOT/Rates Trainer.command" "$ROOT/trainer" "$ROOT/scripts/launch.py" "$ROOT/scripts/install_launcher.sh" 2>/dev/null || true
{
  echo "#!/bin/bash"
  echo "$MARK"
  echo "# Installed by scripts/install_launcher.sh. Starts the Rates Trainer project below."
  printf 'export RATES_TRAINER_ROOT=%q\n' "$ROOT"
  # shellcheck disable=SC2016
  echo 'if [ ! -f "$RATES_TRAINER_ROOT/Rates Trainer.command" ]; then'
  echo '  echo "Rates Trainer: the project folder is no longer at $RATES_TRAINER_ROOT."'
  echo '  echo "Run scripts/install_launcher.sh from its new location."'
  echo '  if [ -t 0 ]; then read -r -p "Press Return to close this window. " _; fi'
  echo '  exit 2'
  echo 'fi'
  echo 'exec "$RATES_TRAINER_ROOT/Rates Trainer.command" "$@"'
} > "$TARGET"
chmod 755 "$TARGET"
echo "Installed: $TARGET"
echo "It starts: $ROOT"
echo "Double-click it to run. If macOS blocks it the first time: right-click it, choose Open, then Open."
