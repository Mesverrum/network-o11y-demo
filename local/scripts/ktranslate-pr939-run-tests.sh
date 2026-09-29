#!/usr/bin/env bash
set -euo pipefail
SRC="/mnt/c/Users/mesve/projects/network-o11y-demo/local/scripts/ktranslate-pr939-user_device_rule_test.go"
DEST="${HOME}/ktranslate-pr939/pkg/util/rule/user_device_rule_test.go"
sed 's/\r$//' "$SRC" > "$DEST"
cd "${HOME}/ktranslate-pr939"
go test ./pkg/util/rule/ -count=1 -v
