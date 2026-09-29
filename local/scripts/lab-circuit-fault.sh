#!/usr/bin/env bash
# lab-circuit-fault.sh — admin-disable/enable a catalogued Clos circuit.
#
# Usage:
#   ./scripts/lab-circuit-fault.sh disable WAN-HQ-BR1
#   ./scripts/lab-circuit-fault.sh enable WAN-HQ-BR1
#   ./scripts/lab-circuit-fault.sh status WAN-HQ-BR1
#   ./scripts/lab-circuit-fault.sh list
#
# Catalog: local/fixtures/lab-circuits.json (override LAB_CIRCUITS_FILE).

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CATALOG="${LAB_CIRCUITS_FILE:-$ROOT/fixtures/lab-circuits.json}"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

cmd="${1:-status}"
circuit="${2:-}"

[[ -f "$CATALOG" ]] || die "missing catalog $CATALOG"

lookup() {
  local cid="$1"
  python3 - "$CATALOG" "$cid" <<'PY'
import json, sys
path, cid = sys.argv[1], sys.argv[2]
data = json.load(open(path, encoding="utf-8"))
circuits = data.get("circuits") or {}
if cid == "__default__":
    cid = data.get("default_circuit") or next(iter(circuits))
    print(cid)
    raise SystemExit(0)
if cid == "__list__":
    for k, v in circuits.items():
        print(f"{k}\t{v.get('node')}\t{v.get('iface')}\t{v.get('description','')}")
    raise SystemExit(0)
c = circuits.get(cid)
if not c:
    print(f"unknown circuit {cid}", file=sys.stderr)
    raise SystemExit(2)
for key in ("node", "iface", "peer_node", "peer_iface", "description"):
    print(c.get(key) or "")
PY
}

sr_admin() {
  local node="$1" iface="$2" state="$3"
  printf 'set / interface %s admin-state %s\ncommit stay\n' "$iface" "$state" \
    | docker exec -i "$node" bash -c 'sr_cli -ed'
}

read_admin() {
  local node="$1" iface="$2"
  docker exec "$node" bash -c "sr_cli -c 'info from running interface ${iface} admin-state'" \
    | tr -s '[:space:]' ' ' | sed 's/^[[:space:]]*//;s/[[:space:]]*$//'
}

case "$cmd" in
  list)
    lookup __list__
    exit 0
    ;;
  disable|enable|status)
    if [[ -z "$circuit" ]]; then
      circuit="$(lookup __default__)"
    fi
    ;;
  *)
    die "usage: $0 disable|enable|status|list [CIRCUIT]"
    ;;
esac

mapfile -t fields < <(lookup "$circuit")
NODE="${fields[0]:-}"
IFACE="${fields[1]:-}"
PEER_NODE="${fields[2]:-}"
PEER_IFACE="${fields[3]:-}"
DESC="${fields[4]:-}"
[[ -n "$NODE" && -n "$IFACE" ]] || die "catalog missing node/iface for $circuit"

docker inspect "$NODE" >/dev/null 2>&1 || die "container ${NODE} not found"

emit_status() {
  echo "circuit=${circuit}"
  echo "description=${DESC}"
  echo "node=${NODE}"
  echo "iface=${IFACE}"
  echo "peer=${PEER_NODE:-} ${PEER_IFACE:-}"
  echo -n "admin_state="
  read_admin "$NODE" "$IFACE" || echo "(unavailable)"
}

case "$cmd" in
  disable)
    info "Disabling ${circuit} (${NODE} ${IFACE}) — ${DESC}"
    sr_admin "$NODE" "$IFACE" disable
    emit_status
    ;;
  enable)
    info "Enabling ${circuit} (${NODE} ${IFACE})"
    sr_admin "$NODE" "$IFACE" enable
    emit_status
    ;;
  status)
    emit_status
    ;;
esac
