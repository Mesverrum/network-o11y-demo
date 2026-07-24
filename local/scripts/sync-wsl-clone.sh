#!/usr/bin/env bash
# Sync Windows checkout → WSL ext4 clone (rsync excludes secrets/state).
set -euo pipefail
WIN="${1:-/mnt/c/Users/mesve/projects/network-o11y-demo}"
WSL="${2:-$HOME/network-o11y-demo}"
[[ -d "$WIN" ]] || { echo "missing Windows repo: $WIN" >&2; exit 1; }
mkdir -p "$WSL"
rsync -a --delete \
  --exclude '.git/' \
  --exclude 'local/.env' \
  --exclude 'local/groups/*.env' \
  --exclude 'local/config/' \
  --exclude 'local/state/' \
  "$WIN/" "$WSL/"
# Preserve WSL-local secrets if present
for f in .env groups/srl.env; do
  if [[ -f "$WSL/local/$f" ]]; then
    : # keep existing WSL copy
  elif [[ -f "$WIN/local/$f" ]]; then
    cp "$WIN/local/$f" "$WSL/local/$f" 2>/dev/null || true
  fi
done
find "$WSL/local/scripts" -name '*.sh' -exec sed -i 's/\r$//' {} +
echo "Synced $WIN → $WSL (secrets/state preserved on WSL)"
