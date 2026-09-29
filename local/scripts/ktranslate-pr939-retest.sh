#!/usr/bin/env bash
set -euo pipefail
DEST="${HOME}/ktranslate-pr939"
git -C "$DEST" fetch origin allow-custom-per-device-rules
git -C "$DEST" checkout allow-custom-per-device-rules
git -C "$DEST" reset --hard origin/allow-custom-per-device-rules
echo "HEAD $(git -C "$DEST" rev-parse --short HEAD)"
WIN="/mnt/c/Users/mesve/projects/network-o11y-demo/local/scripts"
sed 's/\r$//' "$WIN/ktranslate-pr939-user_device_rule_test.go" > "$DEST/pkg/util/rule/user_device_rule_test.go"
cd "$DEST"
go test ./pkg/util/rule/ ./pkg/kt/ ./pkg/inputs/snmp/metadata/ -count=1 -v
