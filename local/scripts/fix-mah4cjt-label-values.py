#!/usr/bin/env python3
"""Fix label_values(..., device) -> ..., source on mah4cjt BGP vars."""
import json
import re
import urllib.request
from pathlib import Path

env = {}
for line in (Path(__file__).resolve().parents[1] / ".env").read_text().splitlines():
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()

base = env["GRAFANA_URL"].rstrip("/")
hdr = {
    "Authorization": f"Bearer {env['GRAFANA_TOKEN']}",
    "Content-Type": "application/json",
}


def get(uid):
    req = urllib.request.Request(f"{base}/api/dashboards/uid/{uid}", headers=hdr)
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def post(payload):
    req = urllib.request.Request(
        f"{base}/api/dashboards/db",
        data=json.dumps(payload).encode(),
        method="POST",
        headers=hdr,
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


meta = get("mah4cjt")
dash = meta["dashboard"]
n = 0

def fix_lv(s: str) -> str:
    global n
    if not isinstance(s, str):
        return s
    # Replace trailing ,device) in label_values(..., device)
    new = re.sub(
        r"(label_values\s*\(.+),\s*device\s*\)",
        r"\1, source)",
        s,
        flags=re.DOTALL,
    )
    if new != s:
        n += 1
    return new

for t in dash.get("templating", {}).get("list", []):
    if isinstance(t.get("definition"), str) and "label_values" in t["definition"] and "device)" in t["definition"]:
        t["definition"] = fix_lv(t["definition"])
    q = t.get("query")
    if isinstance(q, str) and "label_values" in q and "device)" in q:
        t["query"] = fix_lv(q)
    elif isinstance(q, dict) and isinstance(q.get("query"), str):
        if "label_values" in q["query"] and "device)" in q["query"]:
            q["query"] = fix_lv(q["query"])

post(
    {
        "dashboard": dash,
        "folderUid": meta.get("meta", {}).get("folderUid") or "",
        "message": "Fix BGP label_values to use source label (gnmic OTEL)",
        "overwrite": True,
    }
)
print(f"fixed {n} label_values device->source")
