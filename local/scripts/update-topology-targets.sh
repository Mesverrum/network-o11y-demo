#!/usr/bin/env bash
# update-topology-targets.sh — rewrite topology-exporter targets from live clab mgmt IPs.

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CFG="${ROOT}/topology-exporter/config.yaml"
ALLOY="${ROOT}/alloy/config.alloy"
# shellcheck source=fabric-nodes.sh
source "${ROOT}/scripts/fabric-nodes.sh"
TESTER_ID="$(bash "${ROOT}/scripts/lab-tester-id.sh")"

die()  { echo "ERROR: $*" >&2; exit 1; }
info() { echo "==> $*"; }

[[ -f "$CFG" ]] || die "missing ${CFG}"

if ! bash "${ROOT}/scripts/lab-topology-exporter.sh" enabled 2>/dev/null; then
  info "topology_exporter disabled — skipping ${CFG}"
  exit 0
fi

CLAB_NET="${CLAB_NETWORK:-clab}"
docker network inspect "$CLAB_NET" >/dev/null 2>&1 \
  || die "docker network ${CLAB_NET} not found — check CLAB_NETWORK / clab deploy"

declare -A IPS=()
for node in "${SRL_NODES[@]}"; do
  ip="$(docker inspect -f "{{(index .NetworkSettings.Networks \"${CLAB_NET}\").IPAddress}}" "$node" 2>/dev/null || true)"
  [[ -n "$ip" && "$ip" != "<no value>" ]] || die "could not resolve mgmt IP for ${node} on ${CLAB_NET}"
  info "${node} → ${ip}"
  IPS["$node"]="$ip"
done

export TESTER_ID
export CFG TESTER_ID CLAB_NETWORK
export SRL_NODES_STR="${SRL_NODES[*]}"
python3 <<'PY'
import os
import re
import subprocess
from pathlib import Path

cfg = Path(os.environ["CFG"])
tester = os.environ["TESTER_ID"]
nodes = os.environ.get("SRL_NODES_STR", "").split()
if not nodes:
    nodes = os.environ.get("SRL_NODES", "").split()
clab = os.environ.get("CLAB_NETWORK", "clab")

def site(node: str) -> str:
    if node in {"spine1", "leaf1", "leaf2", "client1", "client2"}:
        return "hq"
    if node.startswith("leaf-br1") or node == "client-br1":
        return "branch1"
    if node.startswith("leaf-br2") or node == "client-br2":
        return "branch2"
    return "unknown"

def role(node: str) -> str:
    if node == "spine1":
        return "spine"
    if node in {"leaf1", "leaf2"}:
        return "leaf"
    if node.startswith("leaf-br"):
        return "branch-edge"
    return "unknown"

ips: dict[str, str] = {}
for node in nodes:
    out = subprocess.check_output(
        [
            "docker", "inspect",
            "-f", f"{{{{(index .NetworkSettings.Networks \"{clab}\").IPAddress}}}}",
            node,
        ],
        text=True,
    ).strip()
    ips[node] = out

lines = [
    "targets:",
]
for node in nodes:
    lines += [
        f"  - host: {ips[node]}",
        "    port: 161",
        f"    site: {site(node)}",
        "    labels:",
        f"      role: {role(node)}",
        f"      device_name: {node}",
        f"      tester_id: {tester}",
    ]

text = cfg.read_text(encoding="utf-8")
if not re.search(r"^targets:\s*$", text, re.M):
    raise SystemExit("targets: section not found in config")
new_text = re.sub(r"^targets:\n(?:[ \t].*\n)*", "\n".join(lines) + "\n", text, count=1, flags=re.M)
cfg.write_text(new_text, encoding="utf-8")
print(f"updated {cfg} ({len(nodes)} targets, tester_id={tester})")
PY

if [[ -f "$ALLOY" ]]; then
  perl -pi -e "s/(\\[\"tester_id\"\\], \")[^\"]+(\")/\${1}${TESTER_ID}\${2}/g" "$ALLOY"
  info "synced tester_id in alloy/config.alloy → ${TESTER_ID}"
fi

info "Restarting topology_exporter..."
docker restart topology_exporter >/dev/null 2>&1 || true
