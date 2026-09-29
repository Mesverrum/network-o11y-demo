#!/usr/bin/env bash
# Clone Ian's PR #939 on WSL ext4 and run pkg/util/rule tests.
set -euo pipefail
DEST="${KTRANSLATE_PR939_DIR:-$HOME/ktranslate-pr939}"
if [[ ! -d "$DEST/.git" ]]; then
  git clone --depth 1 --branch allow-custom-per-device-rules \
    https://github.com/kentik/ktranslate.git "$DEST"
else
  git -C "$DEST" fetch origin allow-custom-per-device-rules
  git -C "$DEST" checkout allow-custom-per-device-rules
  git -C "$DEST" reset --hard origin/allow-custom-per-device-rules
fi
cd "$DEST"
go test ./pkg/util/rule/ ./pkg/kt/ ./pkg/inputs/snmp/metadata/ -count=1
