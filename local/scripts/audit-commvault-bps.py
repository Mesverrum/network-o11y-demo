#!/usr/bin/env python3
"""DEPRECATED — strips TabsLayout on v2 dashboards. Use patch-iface-bps-fleet.py instead.

Legacy audit (and optionally patch) interface BPS queries in Commvault Ktranslate folder.
"""
from __future__ import annotations

import copy
import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import importlib.util

_spec = importlib.util.spec_from_file_location(
    "patch_iface_bps_60s", ROOT / "scripts" / "patch-iface-bps-60s.py"
)
_patch = importlib.util.module_from_spec(_spec)
assert _spec.loader is not None
_spec.loader.exec_module(_patch)
ensure_desc = _patch.ensure_desc
rewrite_expr = _patch.rewrite_expr
walk_panels = _patch.walk_panels

KTRANSLATE_UIDS = [
    "ktranslate-device-summary",  # 03. Network Device Summary
    "ktranslate-device-details",  # 04. Network Device Details
    "ktranslate-flow-summary",  # 02. Network Flow Summary
    "ktranslate-architecture",  # 00. Ktranslate Architecture
    "ktranslate-health",  # 01. Ktranslate Health
]

OLD_PATTERNS = [
    re.compile(r"rate\s*\(\s*[^)]*kentik_snmp_ifHC(?:In|Out)Octets", re.I),
    re.compile(r"rate\s*\(\s*[^)]*ifHC(?:In|Out)Octets", re.I),
]


def gcx_api(path: str, method: str = "GET", body: dict | None = None) -> dict:
    cmd = ["gcx", "--context", "commvault", "--agent", "api", path, "-o", "json"]
    if method != "GET":
        cmd.extend(["-X", method])
    tmp: Path | None = None
    if body is not None:
        tmp = ROOT / ".dash-payloads" / "_gcx-api-body.json"
        tmp.write_text(json.dumps(body), encoding="utf-8")
        cmd.extend(["-d", f"@{tmp}"])
    try:
        out = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace")
    finally:
        if tmp and tmp.exists():
            tmp.unlink(missing_ok=True)
    # gcx may prepend hints; find JSON start
    start = out.find("{")
    bracket = out.find("[")
    if bracket != -1 and (start == -1 or bracket < start):
        start = bracket
    if start == -1:
        raise RuntimeError(f"no JSON in gcx output: {out[:300]}")
    return json.loads(out[start:])


def collect_exprs(obj, hits: list, path: str = "") -> None:
    if isinstance(obj, dict):
        if "expr" in obj and isinstance(obj["expr"], str):
            expr = obj["expr"]
            if "ifHC" in expr or "ifHCIn" in expr or "ifHCOut" in expr:
                hits.append({"path": path, "expr": expr})
        for k, v in obj.items():
            collect_exprs(v, hits, f"{path}/{k}" if path else k)
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            collect_exprs(v, hits, f"{path}[{i}]")


def classify(expr: str) -> str:
    if any(p.search(expr) for p in OLD_PATTERNS):
        return "OLD_rate"
    if "kentik_snmp_ifHC" in expr and ("* 8 / 60" in expr or "*8/60" in expr.replace(" ", "")):
        return "OK_delta"
    if "kentik_snmp_ifHC" in expr and "* 8" in expr:
        return "SUSPECT_no_div60"
    if "ifHC" in expr:
        return "OTHER_ifHC"
    return "skip"


def audit_uid(uid: str) -> dict:
    data = gcx_api(f"/api/dashboards/uid/{uid}")
    dash = data["dashboard"]
    meta = data.get("meta") or {}
    title = dash.get("title") or uid

    all_exprs: list[dict] = []
    collect_exprs(dash, all_exprs)

    iface_exprs = [e for e in all_exprs if "kentik_snmp_ifHC" in e["expr"] or re.search(r"ifHC(?:In|Out)Octets", e["expr"])]
    by_class: dict[str, list] = {}
    for e in iface_exprs:
        cls = classify(e["expr"])
        by_class.setdefault(cls, []).append(e)

    return {
        "uid": uid,
        "title": title,
        "folderUid": meta.get("folderUid"),
        "iface_expr_count": len(iface_exprs),
        "by_class": {k: len(v) for k, v in by_class.items()},
        "old_samples": [e["expr"][:180] for e in by_class.get("OLD_rate", [])[:3]],
        "suspect_samples": [e["expr"][:180] for e in by_class.get("SUSPECT_no_div60", [])[:3]],
        "dashboard": dash,
        "meta": meta,
    }


def patch_uid(report: dict) -> dict:
    dash = copy.deepcopy(report["dashboard"])
    hits: list = []
    walk_panels(dash.get("panels") or [], hits)
    expr_hits = [h for h in hits if "to" in h]
    if not expr_hits:
        return {"patched": False, "expr_changes": 0}

    payload = {
        "dashboard": dash,
        "folderUid": report["meta"].get("folderUid") or "",
        "message": "Interface bps: ktranslate delta gauges use *8/60 not rate()*8 (60s poll)",
        "overwrite": True,
    }
    result = gcx_api("/api/dashboards/db", method="POST", body=payload)
    return {
        "patched": True,
        "expr_changes": len(expr_hits),
        "desc_changes": len([h for h in hits if h.get("desc_updated")]),
        "status": result.get("status"),
        "version": result.get("version"),
        "changes": expr_hits,
    }


def main() -> None:
    do_patch = "--patch" in sys.argv
    reports = []
    for uid in KTRANSLATE_UIDS:
        print(f"\n=== {uid} ===")
        try:
            r = audit_uid(uid)
        except Exception as e:
            print(f"  ERROR: {e}")
            reports.append({"uid": uid, "error": str(e)})
            continue
        print(f"  {r['title']}")
        print(f"  iface expressions: {r['iface_expr_count']}")
        print(f"  classes: {r['by_class']}")
        if r.get("old_samples"):
            print("  OLD rate() samples:")
            for s in r["old_samples"]:
                print(f"    - {s}")
        if r.get("suspect_samples"):
            print("  SUSPECT (*8 without /60):")
            for s in r["suspect_samples"]:
                print(f"    - {s}")

        entry = {k: v for k, v in r.items() if k not in ("dashboard", "meta")}
        if do_patch and r["by_class"].get("OLD_rate"):
            patch_result = patch_uid(r)
            entry["patch"] = {
                k: v
                for k, v in patch_result.items()
                if k != "changes"
            }
            entry["patch_expr_count"] = patch_result.get("expr_changes", 0)
            print(f"  PATCHED: expr={patch_result.get('expr_changes')} desc={patch_result.get('desc_changes')} status={patch_result.get('status')}")
        reports.append(entry)

    out = ROOT / ".dash-payloads" / "commvault-bps-audit.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(reports, indent=2))
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
