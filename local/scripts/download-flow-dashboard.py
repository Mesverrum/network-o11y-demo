#!/usr/bin/env python3
"""Download ktranslate-flow-summary v2 manifest from Grafana Cloud."""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UID = "ktranslate-flow-summary"
NS = "stacks-1061129"
OUT = ROOT / ".dash-payloads" / "marcnetterfield-live" / f"{UID}.json"


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def main() -> int:
    env = load_env()
    base = env["GRAFANA_URL"].rstrip("/")
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{UID}"
    req = urllib.request.Request(
        base + path,
        headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        dash = json.loads(resp.read())
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(dash, indent=2), encoding="utf-8")
    gen = dash.get("metadata", {}).get("generation", "?")
    print(f"Wrote {OUT} (generation={gen})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
