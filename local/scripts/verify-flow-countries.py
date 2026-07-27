#!/usr/bin/env python3
"""Print distinct network_peer_country values from flow metrics."""
from __future__ import annotations

import json
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")

    q = 'count by (network_peer_country) (network_io_by_flow_bytes{network_peer_country!="Private IP"})'
    base = env["GRAFANA_URL"].rstrip("/")
    prom = env.get("GRAFANA_PROM_UID", "grafanacloud-prom")
    url = f"{base}/api/datasources/proxy/uid/{prom}/api/v1/query?" + urllib.parse.urlencode(
        {"query": q}
    )
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"})
    data = json.loads(urllib.request.urlopen(req, timeout=60).read())
    rows = data.get("data", {}).get("result", [])
    print(f"Public peer countries ({len(rows)}):")
    for r in sorted(rows, key=lambda x: x.get("metric", {}).get("network_peer_country", "")):
        cc = r["metric"].get("network_peer_country", "?")
        print(f"  {cc}: {r['value'][1]} series")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
