#!/usr/bin/env bash
# snmp-check.sh — quick SNMP path diagnostic (TARGETS vs live IPs, snmpget, poller logs).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
# shellcheck source=lab-path.sh
source "${ROOT}/scripts/lab-path.sh"

echo "=== TARGETS in groups/srl.env ==="
grep '^TARGETS=' groups/srl.env || true

echo ""
echo "=== Live clab mgmt IPs ==="
for n in spine1 leaf1 leaf2; do
  ip=$(docker inspect -f '{{(index .NetworkSettings.Networks "clab").IPAddress}}' "$n" 2>/dev/null || echo missing)
  run=$(docker inspect -f '{{.State.Running}}' "$n" 2>/dev/null || echo false)
  echo "  ${n}: ${ip} running=${run}"
done

echo ""
echo "=== Discovery CIDR (groups/srl.env TARGETS) vs live mgmt IPs ==="
python3 - <<'PY'
import ipaddress
import subprocess
from pathlib import Path

targets = ""
for line in Path("groups/srl.env").read_text().splitlines():
    if line.startswith("TARGETS="):
        targets = line.split("=", 1)[1].strip()
        break
if not targets:
    print("  (no TARGETS= in groups/srl.env)")
    raise SystemExit(0)

nets = []
for part in targets.split(","):
    part = part.strip()
    if not part:
        continue
    try:
        nets.append(ipaddress.ip_network(part, strict=False))
    except ValueError:
        print(f"  invalid TARGETS entry: {part}")
        raise SystemExit(0)

for n in ("spine1", "leaf1", "leaf2"):
    ip = subprocess.check_output(
        ["docker", "inspect", "-f", "{{(index .NetworkSettings.Networks \"clab\").IPAddress}}", n],
        text=True,
    ).strip()
    if not ip or ip == "<no value>":
        print(f"  {n}: (no clab IP)")
        continue
    addr = ipaddress.ip_address(ip)
    ok = any(addr in net for net in nets)
    print(f"  {n} {ip}: {'in TARGETS' if ok else 'OUTSIDE TARGETS — run make snmp-discover'}")
PY

echo ""
echo "=== snmpget sysName (public) ==="
for n in spine1 leaf1 leaf2; do
  ip=$(docker inspect -f '{{(index .NetworkSettings.Networks "clab").IPAddress}}' "$n" 2>/dev/null || true)
  [[ -n "$ip" && "$ip" != "<no value>" ]] || continue
  printf "  %s (%s): " "$n" "$ip"
  snmpget -v2c -c public -t 2 -r 1 "${ip}:161" 1.3.6.1.2.1.1.5.0 2>&1 | head -1
done

echo ""
echo "=== state/devices-srl.yaml IPs ==="
python3 - <<'PY'
import yaml
from pathlib import Path
p = Path("state/devices-srl.yaml")
if not p.exists():
    print("  (missing)")
    raise SystemExit(0)
d = yaml.safe_load(p.read_text()) or {}
devs = d.get("devices", d) if isinstance(d, dict) else d
if isinstance(devs, dict):
    for name, cfg in devs.items():
        ip = cfg.get("device_ip") or cfg.get("ip") or cfg
        print(f"  {name}: {ip}")
else:
    print(f"  ({len(devs)} entries)")
PY

echo ""
echo "=== ktranslate_snmp_srl logs (errors, last 10) ==="
KT=$(docker ps --format '{{.Names}}' | grep -E 'ktranslate_snmp_srl' | head -1)
if [[ -z "$KT" ]]; then
  echo "  (ktranslate_snmp_srl container not running)"
else
  docker logs "$KT" --tail 30 2>&1 \
    | grep -iE 'error|warn|refused|timeout' | tail -10 \
    || docker logs "$KT" --tail 5 2>&1
fi

echo ""
echo "=== Grafana Cloud (ktranslate OTLP path) ==="
python3 - <<'PY'
import json, urllib.parse, urllib.request
from pathlib import Path

env = {}
for line in Path(".env").read_text().splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        env[k] = v
if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
    print("  (skip: GRAFANA_URL / GRAFANA_TOKEN not set in .env)")
    raise SystemExit(0)

def query(q: str):
    qs = urllib.parse.urlencode({"query": q})
    req = urllib.request.Request(
        f"{env['GRAFANA_URL']}/api/datasources/proxy/uid/grafanacloud-prom/api/v1/query?{qs}",
        headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp).get("data", {}).get("result", [])

# ktranslate exports per-metric names (kentik_snmp_CPU, …), not kentik_snmp_DeviceMetrics.
checks = [
    ("count by (device_name) (kentik_snmp_CPU)", "SNMP devices (CPU series)"),
    ('count({__name__=~"kentik_snmp.*"})', "total kentik_snmp_* series"),
]
for promql, label in checks:
    results = query(promql)
    if not results:
        print(f"  {label}: no data")
        continue
    if promql.startswith("count by"):
        names = sorted(r["metric"].get("device_name", "?") for r in results)
        print(f"  {label}: {', '.join(names)}")
    else:
        print(f"  {label}: {results[0]['value'][1]}")
PY
