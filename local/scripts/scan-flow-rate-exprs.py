#!/usr/bin/env python3
"""Scan dashboards for rate(network_io_by_flow*) expressions."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

OLD = re.compile(r"rate\s*\(\s*[^)]*network_io_by_flow", re.IGNORECASE)
OLD_SNMP = re.compile(r"rate\s*\(\s*[^)]*kentik_snmp_ifHC(?:In|Out)Octets", re.IGNORECASE)


def gcx_json(context: str, args: list[str]):
    out = subprocess.check_output(
        ["gcx", "--context", context, "--agent", *args, "-o", "json"],
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    start = out.find("{")
    bracket = out.find("[")
    if bracket != -1 and (start == -1 or bracket < start):
        start = bracket
    return json.loads(out[start:])


def find_exprs(obj, hits: list, path: str = "") -> None:
    if isinstance(obj, dict):
        if "expr" in obj and isinstance(obj["expr"], str):
            e = obj["expr"]
            if OLD.search(e) or OLD_SNMP.search(e):
                hits.append({"path": path, "expr": e})
        if "spec" in obj and isinstance(obj["spec"], str) and ("query" in path.lower() or "expr" in path.lower()):
            e = obj["spec"]
            if OLD.search(e) or OLD_SNMP.search(e):
                hits.append({"path": path + ".spec", "expr": e})
        for k, v in obj.items():
            find_exprs(v, hits, f"{path}.{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            find_exprs(v, hits, f"{path}[{i}]")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("contexts", nargs="+")
    args = parser.parse_args()
    for ctx in args.contexts:
        print(f"\n######## {ctx} ########")
        search = gcx_json(ctx, ["api", "/api/search?type=dash-db&limit=500"])
        for d in search:
            uid = d["uid"]
            title = d.get("title", "")
            try:
                manifest = gcx_json(ctx, ["dashboards", "get", uid])
            except subprocess.CalledProcessError:
                continue
            hits: list[dict] = []
            find_exprs(manifest, hits)
            if hits:
                print(f"\n{uid} | {title} | {len(hits)} hit(s)")
                for h in hits[:8]:
                    print(" ", h["expr"][:200])


if __name__ == "__main__":
    main()
