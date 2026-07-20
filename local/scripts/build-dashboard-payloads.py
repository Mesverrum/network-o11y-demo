#!/usr/bin/env python3
"""Build Grafana dashboard import payloads for MCP/API upload."""
import json
import pathlib
import sys

repo = pathlib.Path(__file__).resolve().parents[2]
src = repo / "grafana" / "dashboards"
out = repo / "local" / ".dash-payloads"
out.mkdir(parents=True, exist_ok=True)

files = sorted(src.glob("*.json"))
if not files:
    print("No dashboard JSON found", file=sys.stderr)
    sys.exit(1)

for f in files:
    dash = json.loads(f.read_text(encoding="utf-8"))
    dash["version"] = 0
    dash["id"] = None
    payload = {
        "dashboard": dash,
        "overwrite": True,
        "message": "network-o11y-demo local lab import",
        "folderUid": "network-lab",
    }
    dest = out / f.name
    dest.write_text(json.dumps(payload, separators=(",", ":")), encoding="utf-8")
    print(f"{f.name}: {dest.stat().st_size} bytes uid={dash.get('uid')}")

print(f"Wrote {len(files)} payloads to {out}")
