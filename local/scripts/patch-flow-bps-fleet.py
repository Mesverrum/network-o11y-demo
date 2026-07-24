#!/usr/bin/env python3
"""Patch ktranslate flow BPS: rate(network_io_by_flow*) -> gauge * 8 / 60 (v2-safe)."""
from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads"

NOTE = (
    "Flow bps assumes ktranslate rollup gauges with a 60s NetFlow interval "
    "(bytes x 8 / 60). Do not use rate() on network_io_by_flow_bytes."
)

OLD_EXPR = re.compile(r"rate\s*\(\s*[^)]*network_io_by_flow", re.IGNORECASE)

KNOWN_UIDS = [
    "be8hpir89dds0a",
    "marhvmb",
    "ktrans-preserved-flows",
    "lab-ktranslate-flow",
    "net-o11y-traffic-flows",
    "net-o11y-traffic-sankey",
    "lab-network-join-demo",
]


def rewrite_flow_expr(expr: str) -> tuple[str, bool]:
    if "network_io_by_flow" not in expr or "rate(" not in expr:
        return expr, False
    orig = expr
    new = re.sub(
        r"rate\(\s*(network_io_by_flow(?:_bytes)?(?:\{[^{}]*\})?)\s*\[[^\]]+\]"
        r"(\s+offset\s+[\w]+)?\s*\)",
        lambda m: f"({m.group(1)}{m.group(2) or ''})",
        expr,
    )
    if new == orig:
        return expr, False
    if "* 8 / 60" not in new.replace(" ", ""):
        new2 = re.sub(r"\*\s*8\b(?!\s*/\s*60)", "* 8 / 60", new)
        if new2 == new:
            new2 = re.sub(
                r"\((network_io_by_flow(?:_bytes)?(?:\{[^{}]*\})?)(\s+offset\s+[\w]+)?\)",
                r"(\1\2) * 8 / 60",
                new,
            )
        new = new2
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
    if "60s NetFlow" in base or "bytes x 8 / 60" in base or "bytes × 8 / 60" in base:
        return base
    if not base:
        return NOTE
    return base.rstrip() + "\n\n" + NOTE


def patch_strings(obj, hits: list, name: str) -> bool:
    changed = False

    def walk(o, path: str) -> None:
        nonlocal changed
        if isinstance(o, dict):
            for k, v in o.items():
                if k in ("expr", "spec") and isinstance(v, str) and "network_io_by_flow" in v:
                    new, did = rewrite_flow_expr(v)
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


def discover_uids(context: str) -> list[dict]:
    search = gcx_json(context, ["api", "/api/search?type=dash-db&limit=500"])
    by_uid = {d["uid"]: d for d in search}
    candidates = []
    for uid, meta in by_uid.items():
        title = (meta.get("title") or "").lower()
        folder = (meta.get("folderTitle") or "").lower()
        tags = [t.lower() for t in meta.get("tags") or []]
        if uid in KNOWN_UIDS or any(
            k in title or k in folder or k in tags
            for k in ("ktranslate", "kentik", "network lab", "flow", "traffic", "netterfield")
        ):
            candidates.append(meta)
    for uid in KNOWN_UIDS:
        if uid in by_uid and by_uid[uid] not in candidates:
            candidates.append(by_uid[uid])
    return candidates


def patch_uid(context: str, uid: str, dry_run: bool = False) -> dict:
    try:
        manifest = gcx_json(context, ["dashboards", "get", uid])
    except subprocess.CalledProcessError as e:
        return {"uid": uid, "status": "error", "error": str(e)}
    title = (manifest.get("spec") or {}).get("title") or uid
    layout_before = (manifest.get("spec") or {}).get("layout", {}).get("kind")
    if not OLD_EXPR.search(json.dumps(manifest)):
        return {
            "uid": uid,
            "title": title,
            "status": "skipped",
            "reason": "no rate(network_io_by_flow*) expr",
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
    }
    if dry_run:
        return result
    manifest.setdefault("metadata", {}).setdefault("annotations", {})[
        "grafana.app/message"
    ] = "Flow bps: ktranslate rollup gauges use bytes*8/60 (preserve TabsLayout)"
    tmp = OUT / f"_flow-v2-patch-{context}-{uid}.json"
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
    parser.add_argument("uids", nargs="*", help="optional explicit UIDs")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    targets = [{"uid": u, "title": u} for u in args.uids] if args.uids else discover_uids(args.context)
    print(f"Scanning {len(targets)} dashboards on {args.context}...")
    report = []
    for meta in targets:
        uid = meta["uid"]
        print(f"\n=== {uid} | {meta.get('title', '')} ===")
        res = patch_uid(args.context, uid, dry_run=args.dry_run)
        report.append(res)
        print(json.dumps(res, indent=2))
    out = OUT / f"flow-v2-patch-report-{args.context}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    patched = [r for r in report if r.get("status") == "patched"]
    print(f"Patched {len(patched)} / {len(report)} dashboards")


if __name__ == "__main__":
    main()
