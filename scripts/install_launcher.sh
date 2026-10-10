#!/bin/bash
# One-time setup: put the "Rates Trainer" app (icon and all) on the Desktop.   scripts/install_launcher.sh [--dest DIR] [--root DIR] [--force] [--command]
# The app is a small bundle that POINTS AT this project folder (it copies nothing), so later changes to scripts/app_launcher.sh or launch.py need no reinstall. Run this
# again if you move the project folder, delete the app, or change the icon (scripts/assets/make_icon.sh rebuilds AppIcon.icns first).
# It never overwrites anything it did not create (without --force), needs no administrator rights, and touches nothing else. The older Desktop launcher
# "Rates Trainer.command" that this installer used to create is removed when it carries this installer's own marker, since the app replaces it; --command installs
# that older, Terminal-based launcher instead of the app.
set -eu
ROOT="$(cd -P "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="$HOME/Desktop"
FORCE=0
MODE=app
while [ $# -gt 0 ]; do
  case "$1" in
    --dest) DEST="$2"; shift 2 ;;
    --root) ROOT="$(cd -P "$2" && pwd)"; shift 2 ;;
    --force) FORCE=1; shift ;;
    --command) MODE=command; shift ;;
    -h|--help) sed -n '2,8p' "${BASH_SOURCE[0]}"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done
MARK="# rates-trainer-launcher"
APP_NAME="Rates Trainer"
CMD_TARGET="$DEST/$APP_NAME.command"

[ -d "$DEST" ] || { echo "Destination folder does not exist: $DEST" >&2; exit 1; }
[ -w "$DEST" ] || { echo "Destination folder is not writable: $DEST" >&2; exit 1; }

# ---------------------------------------------------------------------------------------------------------------- the older Terminal launcher
if [ "$MODE" = command ]; then
  [ -f "$ROOT/Rates Trainer.command" ] || { echo "Not found: $ROOT/Rates Trainer.command" >&2; exit 1; }
  if [ -e "$CMD_TARGET" ] && ! grep -q "^$MARK" "$CMD_TARGET" 2>/dev/null && [ "$FORCE" -ne 1 ]; then
    echo "$CMD_TARGET already exists and was not created by this installer; not overwriting it (use --force to replace it)." >&2
    exit 1
  fi
  chmod +x "$ROOT/Rates Trainer.command" "$ROOT/trainer" "$ROOT/scripts/launch.py" "$ROOT/scripts/install_launcher.sh" 2>/dev/null || true
  {
    echo "#!/bin/bash"
    echo "$MARK"
    echo "# Installed by scripts/install_launcher.sh --command. Starts the Rates Trainer project below."
    printf 'export RATES_TRAINER_ROOT=%q\n' "$ROOT"
    # shellcheck disable=SC2016
    echo 'if [ ! -f "$RATES_TRAINER_ROOT/Rates Trainer.command" ]; then'
    echo '  echo "Rates Trainer: the project folder is no longer at $RATES_TRAINER_ROOT."'
    echo '  echo "Run scripts/install_launcher.sh from its new location."'
    echo '  if [ -t 0 ]; then read -r -p "Press Return to close this window. " _; fi'
    echo '  exit 2'
    echo 'fi'
    echo 'exec "$RATES_TRAINER_ROOT/Rates Trainer.command" "$@"'
  } > "$CMD_TARGET"
  chmod 755 "$CMD_TARGET"
  echo "Installed: $CMD_TARGET"
  echo "It starts: $ROOT"
  echo "Double-click it to run. If macOS blocks it the first time: right-click it, choose Open, then Open."
  exit 0
fi

# ---------------------------------------------------------------------------------------------------------------- the app
APP="$DEST/$APP_NAME.app"
RES_MARK="rates-trainer-launcher"
[ -f "$ROOT/trainer" ] || { echo "Not found: $ROOT/trainer (is $ROOT the project folder?)" >&2; exit 1; }
[ -f "$ROOT/scripts/app_launcher.sh" ] || { echo "Not found: $ROOT/scripts/app_launcher.sh" >&2; exit 1; }

REPLACING=0
if [ -e "$APP" ]; then
  if [ -f "$APP/Contents/Resources/$RES_MARK" ] || [ "$FORCE" -eq 1 ]; then
    REPLACING=1
  else
    echo "$APP already exists and was not created by this installer; not overwriting it (use --force to replace it)." >&2
    exit 1
  fi
fi
chmod +x "$ROOT/scripts/app_launcher.sh" "$ROOT/scripts/launch_in_terminal.command" "$ROOT/scripts/stop_server.sh" "$ROOT/scripts/launch.py" "$ROOT/trainer" "$ROOT/Rates Trainer.command" 2>/dev/null || true

# The bundle is built and signed in a clean temporary folder and only then moved into place: the Desktop is usually synced (iCloud Desktop), which stamps Finder and
# file-provider attributes on anything new there, and codesign refuses to sign a bundle that has them. A failed build also leaves an existing app untouched.
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
BUILD="$STAGE/$APP_NAME.app"
mkdir -p "$BUILD/Contents/MacOS" "$BUILD/Contents/Resources"
cat > "$BUILD/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>local.ratestrainer.launcher</string>
  <key>CFBundleExecutable</key><string>launcher</string>
  <key>CFBundleIconFile</key><string>AppIcon</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>1.0</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>10.13</string>
  <key>LSUIElement</key><true/>
</dict>
</plist>
PLIST

# The executable remembers where the project is and runs scripts/app_launcher.sh. macOS keeps a newly created app out of ~/Documents until it is allowed (System Settings >
# Privacy & Security > Files and Folders); until then the app hands over to Terminal, which can read the project, so it always works. With the permission nothing but the browser opens.
{
  echo '#!/bin/bash'
  printf 'PROJECT_DIR=%q\n' "$ROOT"
  cat <<'STUB'
export RATES_TRAINER_ROOT="$PROJECT_DIR"
if [ -x "$PROJECT_DIR/scripts/app_launcher.sh" ] && /bin/ls "$PROJECT_DIR/scripts" >/dev/null 2>&1; then
  exec /bin/bash "$PROJECT_DIR/scripts/app_launcher.sh"
fi
# not readable from here: let Terminal do it (if the folder has moved this fails and the dialog below says so)
if /usr/bin/open -a Terminal "$PROJECT_DIR/scripts/launch_in_terminal.command" 2>/dev/null; then
  exit 0
fi
/usr/bin/osascript - "$PROJECT_DIR" <<'APPLESCRIPT' >/dev/null 2>&1
on run argv
  display dialog "Rates Trainer could not start. The project folder is expected at:" & return & item 1 of argv & return & return & "If you moved it, open the project in its new location and run scripts/install_launcher.sh to recreate this app." with title "Rates Trainer" with icon caution buttons {"OK"} default button "OK"
end run
APPLESCRIPT
exit 2
STUB
} > "$BUILD/Contents/MacOS/launcher"
chmod +x "$BUILD/Contents/MacOS/launcher"
printf 'project=%s\ncreated=%s\n' "$ROOT" "$(date '+%Y-%m-%d %H:%M:%S')" > "$BUILD/Contents/Resources/$RES_MARK"
if [ -f "$ROOT/scripts/assets/AppIcon.icns" ]; then
  cp "$ROOT/scripts/assets/AppIcon.icns" "$BUILD/Contents/Resources/AppIcon.icns"
else
  echo "(scripts/assets/AppIcon.icns is missing: the app will have a generic icon. Run scripts/assets/make_icon.sh and install again.)" >&2
fi

# an ad-hoc signature keeps recent macOS versions happy about a locally built app
if command -v codesign >/dev/null 2>&1; then
  codesign --force --deep --sign - "$BUILD" >/dev/null 2>&1 || echo "(codesign failed; the app should still open)" >&2
fi

if [ "$REPLACING" -eq 1 ]; then
  echo "Replacing the existing launcher at $APP"
  rm -rf "$APP"
fi
mv "$BUILD" "$APP"
touch "$APP"                                           # make Finder notice the new icon

# the app replaces the older Terminal launcher this installer used to put on the Desktop: remove that one, and only if it is this installer's own
if [ -e "$CMD_TARGET" ] && grep -q "^$MARK" "$CMD_TARGET" 2>/dev/null; then
  rm -f "$CMD_TARGET"
  echo "Removed the older launcher $CMD_TARGET (this installer's own; the app replaces it. Use --command to install it again)."
fi

echo "Installed: $APP"
echo "It starts: $ROOT"
echo "Double-click it to start Rates Trainer in your browser. Stop the server with: $ROOT/scripts/stop_server.sh"
