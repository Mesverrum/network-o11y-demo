#!/usr/bin/env python3
"""Probe Prometheus auth paths and iperf traffic health."""
from __future__ import annotations

import base64
import json
import subprocess
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def try_get(url: str, headers: dict[str, str]) -> None:
    try:
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read()[:300]
            print(f"OK {resp.status} {url[:100]}")
            print(f"   {body[:200]!r}")
    except urllib.error.HTTPError as e:
        print(f"HTTP {e.code} {url[:100]} {e.read()[:200]!r}")
    except Exception as e:
        print(f"ERR {type(e).__name__} {url[:100]} {e}")


def main() -> None:
    env = load_env()
    u = env["GC_PROM_URL"].rstrip("/")
    user = env["GC_PROM_USER"]
    tok = env.get("GC_PROM_TOKEN") or env["GC_OTLP_KEY"]
    print(f"PROM ends with: ...{u[-50:]}")
    print(f"user={user} token_len={len(tok)}")

    basic = {"Authorization": "Basic " + base64.b64encode(f"{user}:{tok}".encode()).decode()}
    q = urllib.parse.urlencode({"query": 'count(kentik_snmp_ifHCInOctets)'})
    candidates = [
        f"{u}/api/v1/query?{q}",
        f"{u}/api/prom/api/v1/query?{q}",
    ]
    # strip trailing /api/prom if doubled
    if u.endswith("/api/prom"):
        candidates.append(f"{u}/api/v1/query?{q}")
    else:
        candidates.append(f"{u}/api/prom/api/v1/query?{q}")

    for c in dict.fromkeys(candidates):
        try_get(c, basic)

    gurl = env.get("GRAFANA_URL", "").rstrip("/")
    gtok = env.get("GRAFANA_TOKEN", "")
    if gurl and gtok:
        # discover prometheus datasource uid on the target stack
        req = urllib.request.Request(
            f"{gurl}/api/datasources",
            headers={"Authorization": f"Bearer {gtok}"},
        )
        with urllib.request.urlopen(req, timeout=45) as resp:
            ds = json.loads(resp.read().decode())
        prom = [d for d in ds if d.get("type") == "prometheus"]
        print("stack prometheus datasources:")
        for d in prom:
            print(f"  uid={d['uid']} name={d['name']} isDefault={d.get('isDefault')}")
        for d in prom[:3]:
            try_get(
                f"{gurl}/api/datasources/proxy/uid/{d['uid']}/api/v1/query?{q}",
                {"Authorization": f"Bearer {gtok}"},
            )

    print("\n=== iperf logs ===")
    for cmd in (
        ["docker", "exec", "client2", "tail", "-30", "/tmp/iperf3.log"],
        ["docker", "exec", "client1", "tail", "-30", "/tmp/iperf3_5201.log"],
    ):
        r = subprocess.run(cmd, capture_output=True, text=True)
        print(" ".join(cmd))
        print(r.stdout or r.stderr)


if __name__ == "__main__":
    main()
