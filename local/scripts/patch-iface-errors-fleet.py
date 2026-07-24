#!/usr/bin/env python3
"""Patch ktranslate interface error panels on Grafana v2 dashboards (TabsLayout-safe).

- rate(ifIn/OutErrors) -> (metric) / 60  (ktranslate poll deltas, 60s)
- ifIn/OutErrorPercent -> clamp_max(100 * errors / (ifHC*UcastPkts + 1), 100)

Uses gcx dashboards get/update. See AGENTS.md -> Grafana dashboard updates.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads"

NOTE = (
    "Error/s assumes ktranslate delta gauges with a 60s SNMP poll (errors / 60). "
    "Error % is recomputed as clamp_max(100 * errors / (ifHC*UcastPkts + 1), 100) "
    "instead of ktranslate if*ErrorPercent (can exceed 100%)."
)

OLD_RATE = re.compile(
    r"(?:rate|irate)\s*\(\s*[^)]*kentik_snmp_if(?:In|Out)Errors", re.IGNORECASE
)
OLD_PERCENT = re.compile(r"kentik_snmp_if(?:In|Out)ErrorPercent", re.IGNORECASE)


def rewrite_error_expr(expr: str) -> tuple[str, bool]:
    orig = expr
    new = re.sub(
        r"(?:rate|irate)\(\s*(kentik_snmp_if(?:In|Out)Errors(?:\{[^{}]*\})?)\s*\[\$__rate_interval\]\s*\)",
        r"(\1) / 60",
        expr,
        flags=re.IGNORECASE,
    )
    new = re.sub(
        r"kentik_snmp_ifInErrorPercent(\{[^{}]*\})",
        r"clamp_max(100 * kentik_snmp_ifInErrors\1 / (kentik_snmp_ifHCInUcastPkts\1 + 1), 100)",
        new,
        flags=re.IGNORECASE,
    )
    new = re.sub(
        r"kentik_snmp_ifOutErrorPercent(\{[^{}]*\})",
        r"clamp_max(100 * kentik_snmp_ifOutErrors\1 / (kentik_snmp_ifHCOutUcastPkts\1 + 1), 100)",
        new,
        flags=re.IGNORECASE,
    )
    return new, new != orig


def gcx_json(context: str, args: list[str]) -> dict | list:
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


def ensure_desc(desc: str | None) -> str:
    base = (desc or "").strip()
    if "if*ErrorPercent" in base or "errors / 60" in base or "clamp_max" in base:
        return base
    if not base:
        return NOTE
    return base.rstrip() + "\n\n" + NOTE


def manifest_needs_patch(manifest: dict) -> bool:
    blob = json.dumps(manifest)
    return bool(OLD_RATE.search(blob) or OLD_PERCENT.search(blob))


def patch_strings(obj, hits: list, name: str) -> bool:
    changed = False

    def walk(o, path: str) -> None:
        nonlocal changed
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("expr", "spec") and isinstance(v, str):
                    if OLD_RATE.search(v) or OLD_PERCENT.search(v):
                        new, did = rewrite_error_expr(v)
                        if did:
                            hits.append({"panel": name, "path": path, "from": v, "to": new})
                            o[k] = new
                            changed = True
                else:
                    walk(v, f"{path}.{k}" if path else k)
        elif isinstance(o, list):
            for i, v in enumerate(o):
                walk(v, f"{path}[{i}]")

    walk(obj, name)
    return changed


def patch_uid(context: str, uid: str, dry_run: bool = False) -> dict:
    try:
        manifest = gcx_json(context, ["dashboards", "get", uid])
    except subprocess.CalledProcessError as e:
        return {"uid": uid, "status": "error", "error": str(e)}
    title = (manifest.get("spec") or {}).get("title") or uid
    layout_before = (manifest.get("spec") or {}).get("layout", {}).get("kind")
    if not manifest_needs_patch(manifest):
        return {
            "uid": uid,
            "title": title,
            "status": "skipped",
            "reason": "no error rate/percent queries to patch",
            "layout": layout_before,
        }
    hits: list[dict] = []
    elements = (manifest.get("spec") or {}).get("elements") or {}
    for name, el in elements.items():
        if patch_strings(el, hits, name):
            spec = el.get("spec") or {}
            new_desc = ensure_desc(panel_description(spec))
            if new_desc != (panel_description(spec) or ""):
                set_panel_description(spec, new_desc)
                hits.append({"panel": name, "desc_updated": True})
    expr_hits = [h for h in hits if "to" in h]
    if not expr_hits:
        return {
            "uid": uid,
            "title": title,
            "status": "skipped",
            "reason": "rewrite produced no changes",
            "layout": layout_before,
        }
    result = {
        "uid": uid,
        "title": title,
        "status": "patched" if not dry_run else "would_patch",
        "layout_before": layout_before,
        "expr_changes": len(expr_hits),
        "desc_changes": len([h for h in hits if h.get("desc_updated")]),
        "samples": expr_hits[:4],
    }
    if dry_run:
        return result
    manifest.setdefault("metadata", {}).setdefault("annotations", {})[
        "grafana.app/message"
    ] = "Interface errors: /60 + clamped error % (preserve TabsLayout)"
    tmp = OUT / f"_errors-v2-patch-{context}-{uid}.json"
    tmp.write_text(json.dumps(manifest), encoding="utf-8")
    proc = subprocess.run(
        ["gcx", "--context", context, "--agent", "dashboards", "update", uid, "-f", str(tmp)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if proc.returncode != 0:
        result["status"] = "error"
        result["error"] = (proc.stdout + proc.stderr)[-500:]
        return result
    verify = gcx_json(context, ["dashboards", "get", uid])
    result["layout_after"] = (verify.get("spec") or {}).get("layout", {}).get("kind")
    result["generation"] = verify.get("metadata", {}).get("generation")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("context", help="gcx context name")
    parser.add_argument("uids", nargs="+", help="dashboard UIDs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    report = []
    for uid in args.uids:
        print(f"\n=== {uid} ===")
        res = patch_uid(args.context, uid, dry_run=args.dry_run)
        report.append(res)
        print(json.dumps({k: v for k, v in res.items() if k != "samples"}, indent=2))
        for s in res.get("samples", []):
            print("FROM:", s["from"][:120], "...")
            print("TO:  ", s["to"][:200], "...")
    out = OUT / f"errors-v2-patch-report-{args.context}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")


if __name__ == "__main__":
    main()
