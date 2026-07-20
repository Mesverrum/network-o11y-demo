#!/usr/bin/env python3
"""Verify patched fleet stacked traffic expr still has * 8 / 60."""
import json
import urllib.request
from pathlib import Path

env = {}
for line in (Path(".env").read_text().splitlines()):
    if "=" in line and not line.strip().startswith("#"):
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip()


def get(uid):
    req = urllib.request.Request(
        f"{env['GRAFANA_URL'].rstrip('/')}/api/dashboards/uid/{uid}",
        headers={"Authorization": f"Bearer {env['GRAFANA_TOKEN']}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["dashboard"]


def find_exprs(panels, title_sub, out=None):
    out = out or []
    for p in panels or []:
        if title_sub.lower() in (p.get("title") or "").lower():
            for t in p.get("targets") or []:
                if t.get("expr"):
                    out.append((p.get("title"), t["expr"]))
        find_exprs(p.get("panels"), title_sub, out)
    return out


for uid in ("mavgvqv", "magz6qw1"):
    dash = get(uid)
    print("===", uid, dash.get("title"), "===")
    for title, expr in find_exprs(dash.get("panels"), "Fleet Traffic by Device"):
        print(title)
        print(expr)
        print("has /60:", "/ 60" in expr or "/60" in expr)
        print("still has rate(:", "rate(" in expr)
        print()
    for title, expr in find_exprs(dash.get("panels"), "Interface Summary"):
        print(title, "—" , "rate(" in expr, "/ 60" in expr)
        print(expr[:300], "...\n")
