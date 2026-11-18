#!/usr/bin/env bash
# Install secgen as a systemd --user service in WSL. Backfills once, then streams.
set -euo pipefail
SRC="$(cd "$(dirname "$0")" && pwd)/secgen.py"
DEST="$HOME/.local/share/secdemo"
mkdir -p "$DEST" "$HOME/.config/systemd/user"
cp "$SRC" "$DEST/secgen.py"
BACKFILL="${BACKFILL_HOURS:-6}"
if [ ! -f "$DEST/.backfilled" ] && [ "$BACKFILL" != "0" ]; then
  python3 "$DEST/secgen.py" --backfill-hours "$BACKFILL" --once
  touch "$DEST/.backfilled"
fi
cat > "$HOME/.config/systemd/user/secdemo-gen.service" <<EOF
[Unit]
Description=Halvorsen Motors fake security logs to Grafana Cloud

[Service]
ExecStart=/usr/bin/python3 $DEST/secgen.py --env-file $HOME/network-o11y-demo/local/.env
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
EOF
systemctl --user daemon-reload
systemctl --user enable --now secdemo-gen.service
loginctl enable-linger "$USER" 2>/dev/null || true
systemctl --user --no-pager status secdemo-gen.service | head -5
