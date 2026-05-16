#!/usr/bin/env zsh
set -euo pipefail

if [[ $# -ne 1 ]]; then
  print -u2 "usage: ./install-native-host.sh <chrome-extension-id>"
  print -u2 "Load fit-check-extension as an unpacked Chrome extension, then copy its ID from chrome://extensions."
  exit 1
fi

EXTENSION_ID="$1"
HOST_NAME="com.agent_playground.fit_check"
SCRIPT_DIR="${0:A:h}"
NATIVE_HOST_PATH="$SCRIPT_DIR/native-host.sh"
HOST_DIR="${CHROME_NATIVE_HOST_DIR:-$HOME/Library/Application Support/Google/Chrome/NativeMessagingHosts}"
MANIFEST_PATH="$HOST_DIR/$HOST_NAME.json"

if [[ ! "$EXTENSION_ID" =~ '^[a-p]{32}$' ]]; then
  print -u2 "warning: extension id does not look like a Chrome extension id: $EXTENSION_ID"
fi

mkdir -p "$HOST_DIR"
chmod +x "$NATIVE_HOST_PATH"

cat > "$MANIFEST_PATH" <<EOF
{
  "name": "$HOST_NAME",
  "description": "Fit Check Agent Native Messaging host",
  "path": "$NATIVE_HOST_PATH",
  "type": "stdio",
  "allowed_origins": [
    "chrome-extension://$EXTENSION_ID/"
  ]
}
EOF

print "installed $HOST_NAME native host manifest:"
print "$MANIFEST_PATH"
