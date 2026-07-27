#!/usr/bin/env python3
"""Scan and patch kentik ifHC* BPS queries on a Grafana Cloud stack (v2-safe).

Uses gcx ``dashboards get`` / ``dashboards update`` so ``TabsLayout`` is preserved.
Do not use legacy ``POST /api/dashboards/db`` on tabbed v2 dashboards.

Playbook: docs/grafana-dashboard-playbook.md · AGENTS.md → Grafana dashboard updates.
"""
from __future__ import annotations

import argparse
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

OLD_EXPR = re.compile(
    r"(?:rate|irate)\s*\(\s*[^)]*kentik_snmp_ifHC(?:In|Out)Octets", re.IGNORECASE
)

KNOWN_UIDS = [
    "ktranslate-device-summary",
    "ktranslate-device-details",
    "ktranslate-flow-summary",
    "ktranslate-health",
    "ktranslate-architecture",
    "mavgvqv",
    "ma7zxqw",
    "magz6qw1",
    "mah4cjt",
    "marhvmb",
    "masvw96",
    "masjqrs",
    "be8hpir89dds0a",
    "ktrans-arch-replication",
    "ktrans-preserved-summary",
    "ktrans-preserved-details",
    "ktrans-preserved-flows",
    "ktrans-preserved-health",
    "lab-topology-graph",
    "lab-topology-health",
    "lab-network-join-demo",
    "lab-ktranslate-flow",
]


def gcx_json(context: str, args: list[str]) -> dict | list:
    cmd = ["gcx", "--context", context, "--agent", *args, "-o", "json"]
    out = subprocess.check_output(cmd, text=True, encoding="utf-8", errors="replace")
    start = out.find("{")
    bracket = out.find("[")
    if bracket != -1 and (start == -1 or bracket < start):
        start = bracket
    if start < 0:
        raise RuntimeError(f"no JSON from gcx {' '.join(args)}: {out[:300]}")
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


def manifest_has_old_bps(manifest: dict) -> bool:
  blob = json.dumps(manifest)
  return bool(OLD_EXPR.search(blob))


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
            for k in ("ktranslate", "kentik", "network lab", "netterfield", "topology", "device")
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
    if not manifest_has_old_bps(manifest):
        return {
            "uid": uid,
            "title": title,
            "status": "skipped",
            "reason": "no old ifHC rate() expr",
            "layout": layout_before,
        }
    hits = patch_dashboard(manifest)
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
    ] = "Interface bps: ktranslate delta gauges use *8/60 (preserve TabsLayout)"
    tmp = OUT / f"_bps-v2-patch-{context}-{uid}.json"
    tmp.write_text(json.dumps(manifest), encoding="utf-8")
    proc = subprocess.run(
        [
            "gcx",
            "--context",
            context,
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

    if args.uids:
        targets = [{"uid": u, "title": u} for u in args.uids]
    else:
        targets = discover_uids(args.context)

    print(f"Scanning {len(targets)} dashboards on {args.context}...")
    report = []
    for meta in targets:
        uid = meta["uid"]
        print(f"\n=== {uid} | {meta.get('title', '')} ===")
        res = patch_uid(args.context, uid, dry_run=args.dry_run)
        report.append(res)
        print(json.dumps(res, indent=2))

    out = OUT / f"bps-v2-patch-report-{args.context}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    patched = [r for r in report if r.get("status") == "patched"]
    print(f"Patched {len(patched)} / {len(report)} dashboards")


if __name__ == "__main__":
    main()
