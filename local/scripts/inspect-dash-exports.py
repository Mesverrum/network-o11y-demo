#!/usr/bin/env python3
import json
from pathlib import Path

root = Path(__file__).resolve().parents[1] / ".dash-payloads"
for path in sorted(root.glob("dashboard-178431*.json")):
    raw = path.read_text(encoding="utf-8")
    data = json.loads(raw)
    meta = data.get("metadata") or {}
    spec = data.get("spec") or {}
    elements = spec.get("elements") or {}
    print(
        f"{path.name}: bytes={len(raw)} elements={len(elements)} "
        f"name={meta.get('name')} title={spec.get('title')}"
    )
    # show metadata annotations keys
    ann = meta.get("annotations") or {}
    print("  annotations:", sorted(ann.keys())[:15])
    print("  labels:", meta.get("labels"))
