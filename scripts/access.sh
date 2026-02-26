#!/usr/bin/env bash
# access.sh — open SSH port forwards through the bastion to cluster services.
# Run this script locally (not on the bastion).
#
# Usage:
#   source scripts/setup-env.sh   # load AWS creds
#   bash scripts/access.sh
#
# Prerequisites:
#   - BASTION_PUBLIC_IP set (or tofu output available in terraform/)
#   - network-o11y-demo.pem in the repo root (gitignored)

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$SCRIPT_DIR/.."
KEY_FILE="$REPO_ROOT/network-o11y-demo.pem"

# Read bastion IP from terraform output if not already set
if [[ -z "${BASTION_PUBLIC_IP:-}" ]]; then
  echo "Fetching bastion IP from Terraform output..."
  BASTION_PUBLIC_IP=$(cd "$REPO_ROOT/terraform" && tofu output -raw bastion_public_ip 2>/dev/null) || {
    echo "ERROR: BASTION_PUBLIC_IP is not set and could not be read from Terraform output." >&2
    echo "       Run: source scripts/setup-env.sh first, or set BASTION_PUBLIC_IP manually." >&2
    exit 1
  }
fi

if [[ ! -f "$KEY_FILE" ]]; then
  echo "ERROR: SSH key not found at $KEY_FILE" >&2
  exit 1
fi

echo ""
echo "Opening port forwards via bastion @ $BASTION_PUBLIC_IP"
echo ""
echo "  http://localhost:8080   → NetBox UI       (network-tools/netbox:80)"
echo "  http://localhost:12345  → Grafana Alloy UI (network-lab/alloy:12345)"
echo "  http://localhost:9273   → gnmic metrics    (network-lab/gnmic:9273)"
echo ""
echo "  Press Ctrl+C to close all tunnels."
echo ""

# Each -L flag is: local-port:localhost:remote-port
# The bastion runs kubectl port-forward to bridge the local port into the cluster.
# We use a single SSH connection with a RemoteCommand that opens all forwards
# on the bastion simultaneously, then keeps the session alive.
ssh -N \
  -i "$KEY_FILE" \
  -o StrictHostKeyChecking=no \
  -o ServerAliveInterval=30 \
  -o ExitOnForwardFailure=yes \
  -L "8080:localhost:8080" \
  -L "12345:localhost:12345" \
  -L "9273:localhost:9273" \
  "ec2-user@$BASTION_PUBLIC_IP" \
  &
SSH_PID=$!

echo "SSH tunnel open (pid $SSH_PID). Starting kubectl port-forwards on bastion..."
echo ""

# Open the kubectl port-forwards on the bastion in the background.
# These bind to localhost on the bastion, which the SSH -L flags then expose locally.
ssh -i "$KEY_FILE" \
    -o StrictHostKeyChecking=no \
    -o ServerAliveInterval=30 \
    "ec2-user@$BASTION_PUBLIC_IP" \
    "kubectl port-forward -n network-tools svc/netbox   8080:80   --address=127.0.0.1 &
     kubectl port-forward -n network-lab   svc/alloy    12345:12345 --address=127.0.0.1 &
     kubectl port-forward -n network-lab   svc/gnmic    9273:9273   --address=127.0.0.1 &
     wait"  &
KUBECTL_PID=$!

echo "Port forwards active:"
echo "  http://localhost:8080   → NetBox"
echo "  http://localhost:12345  → Alloy UI"
echo "  http://localhost:9273   → gnmic metrics"
echo ""
echo "Press Ctrl+C to close all tunnels."

# Wait for either process to exit, then clean up.
trap "kill $SSH_PID $KUBECTL_PID 2>/dev/null; echo 'Tunnels closed.'" EXIT INT TERM
wait $SSH_PID
