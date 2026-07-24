#!/usr/bin/env python3
"""Patch interface BPS in Grafana v2 dashboards without touching TabsLayout.

Prefer ``patch-iface-bps-fleet.py`` for multi-stack / fleet scans. Pattern doc:
``AGENTS.md`` → *Grafana dashboard updates — preserve TabsLayout*.
"""
from __future__ import annotations

import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads"

_spec = importlib.util.spec_from_file_location(
    "patch_iface_bps_60s", ROOT / "scripts" / "patch-iface-bps-60s.py"
)
_patch = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_patch)
rewrite_expr = _patch.rewrite_expr
NOTE = _patch.NOTE


def gcx_json(args: list[str]) -> dict:
    cmd = ["gcx", "--context", "commvault", "--agent", *args, "-o", "json"]
    out = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace")
    start = out.find("{")
    if start < 0:
        raise RuntimeError(f"no JSON from gcx: {out[:300]}")
    return json.loads(out[start:])


def ensure_desc(desc: str | None) -> str:
    base = (desc or "").strip()
    if "60s SNMP poll" in base or "octets × 8 / 60" in base or "octets x 8 / 60" in base:
        return base
    if not base:
        return NOTE
    return base.rstrip() + "\n\n" + NOTE


def panel_description(spec: dict) -> str | None:
    desc = spec.get("description")
    if isinstance(desc, str):
        return desc
    if isinstance(desc, dict):
        return desc.get("text")
    return None


def set_panel_description(spec: dict, text: str) -> None:
    desc = spec.get("description")
    if isinstance(desc, dict):
        spec["description"]["text"] = text
    else:
        spec["description"] = text


def patch_element_queries(el: dict, hits: list, name: str) -> bool:
    changed = False

    def walk(obj, path: str) -> None:
        nonlocal changed
        if isinstance(obj, dict):
            if "expr" in obj and isinstance(obj["expr"], str):
                new, did = rewrite_expr(obj["expr"])
                if did:
                    hits.append({"panel": name, "path": path, "from": obj["expr"], "to": new})
                    obj["expr"] = new
                    changed = True
            for k, v in obj.items():
                walk(v, f"{path}.{k}" if path else k)
        elif isinstance(obj, list):
            for i, v in enumerate(obj):
                walk(v, f"{path}[{i}]")

    walk(el, name)
    return changed


def patch_dashboard(manifest: dict) -> list[dict]:
    hits: list[dict] = []
    elements = (manifest.get("spec") or {}).get("elements") or {}
    for name, el in elements.items():
        if patch_element_queries(el, hits, name):
            spec = el.get("spec") or {}
            new_desc = ensure_desc(panel_description(spec))
            old_desc = panel_description(spec) or ""
            if new_desc != old_desc:
                set_panel_description(spec, new_desc)
                hits.append({"panel": name, "desc_updated": True})
    return hits


def main() -> None:
    uids = sys.argv[1:] or ["magz6qw1", "mavgvqv"]
    for uid in uids:
        print(f"\n=== {uid} ===")
        manifest = gcx_json(["dashboards", "get", uid])
        layout_kind = (manifest.get("spec") or {}).get("layout", {}).get("kind")
        print(f"  layout before: {layout_kind}")
        hits = patch_dashboard(manifest)
        expr_hits = [h for h in hits if "to" in h]
        if not expr_hits:
            print("  no changes needed")
            continue
        print(f"  expr changes: {len(expr_hits)}")
        manifest.setdefault("metadata", {}).setdefault("annotations", {})[
            "grafana.app/message"
        ] = "Interface bps: ktranslate delta gauges use *8/60 (preserve TabsLayout)"
        tmp = OUT / f"_bps-v2-patch-{uid}.json"
        tmp.write_text(json.dumps(manifest), encoding="utf-8")
        result = subprocess.run(
            [
                "gcx",
                "--context",
                "commvault",
                "--agent",
                "dashboards",
                "update",
                uid,
                "-f",
                str(tmp),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if result.returncode != 0:
            print(result.stdout)
            print(result.stderr)
            raise SystemExit(result.returncode)
        verify = gcx_json(["dashboards", "get", uid])
        layout_after = (verify.get("spec") or {}).get("layout", {}).get("kind")
        print(f"  layout after: {layout_after}")
        print(f"  updated generation: {verify.get('metadata', {}).get('generation')}")


if __name__ == "__main__":
    main()
