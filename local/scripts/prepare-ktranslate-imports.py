#!/usr/bin/env python3
"""Remap Commvault datasource names in v2 exports and import via Grafana API prep."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".dash-payloads"
OUT = ROOT / "ktranslate-import"
OUT.mkdir(parents=True, exist_ok=True)

NAMESPACE = "stacks-1061129"
FOLDER = "network-lab"

# Commvault export labels → your Grafana Cloud datasource UIDs
REPLACEMENTS = {
    "grafanacloud-commvault-prom": "grafanacloud-prom",
    "grafanacloud-commvault-logs": "grafanacloud-logs",
}

FILES = [
    ("dashboard-1784313151319.json", "mavgvqv"),
    ("dashboard-1784313137315.json", "magz6qw1"),
    ("dashboard-1784313167585.json", "be8hpir89dds0a"),
    ("dashboard-1784313199685.json", "masjqrs"),
]


def remap(obj):
    text = json.dumps(obj, separators=(",", ":"))
    for old, new in REPLACEMENTS.items():
        text = text.replace(old, new)
    return json.loads(text)


def prepare(src_name: str, uid: str) -> Path:
    data = json.loads((ROOT / src_name).read_text(encoding="utf-8"))
    data = remap(data)
    meta = data.setdefault("metadata", {})
    meta["name"] = uid
    meta["namespace"] = NAMESPACE
    for k in ("resourceVersion", "generation", "creationTimestamp", "uid"):
        meta.pop(k, None)
    ann = meta.setdefault("annotations", {})
    ann["grafana.app/folder"] = FOLDER
    ann["grafana.app/message"] = f"Import ktranslate dashboard from Commvault ({src_name})"
    out = OUT / f"{uid}.json"
    out.write_text(json.dumps(data, separators=(",", ":")), encoding="utf-8")
    title = (data.get("spec") or {}).get("title")
    print(f"{src_name} -> {out.name} title={title} bytes={out.stat().st_size}")
    return out


def main() -> None:
    for src, uid in FILES:
        prepare(src, uid)


if __name__ == "__main__":
    main()
