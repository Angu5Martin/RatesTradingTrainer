#!/bin/bash
# The same as scripts/app_launcher.sh, but in a Terminal window. The desktop app hands over to this when macOS has not (yet) allowed it to read the project folder
# (System Settings > Privacy & Security > Files and Folders); Terminal can read it. The server runs in the background either way: you may close this window.
DIR="$(cd -P "$(dirname "$0")" && pwd)"
"$DIR/app_launcher.sh" "$@"
rc=$?
echo
if [ $rc -eq 0 ]; then
  echo "You can close this window: Rates Trainer keeps running. Stop it any time with: $DIR/stop_server.sh"
else
  read -r -p "Press Return to close this window. " _
fi
exit $rc
