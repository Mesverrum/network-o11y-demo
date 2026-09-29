#!/usr/bin/env bash
set -euo pipefail
DEST="${HOME}/ktranslate-pr939"
if [[ ! -d "${DEST}/.git" ]]; then
  git clone --depth 1 --branch allow-custom-per-device-rules \
    https://github.com/kentik/ktranslate.git "${DEST}"
else
  git -C "${DEST}" fetch origin allow-custom-per-device-rules
  git -C "${DEST}" checkout allow-custom-per-device-rules
  git -C "${DEST}" reset --hard origin/allow-custom-per-device-rules
fi
echo "cloned ${DEST} @ $(git -C "${DEST}" rev-parse --short HEAD)"
