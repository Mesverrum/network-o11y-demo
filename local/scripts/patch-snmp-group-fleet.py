#!/usr/bin/env python3
"""Add snmp_group template variable and PromQL filters on ktranslate SNMP dashboards.

Uses gcx dashboards get/update (v2-safe; preserves TabsLayout). Can also patch
JSON in the KtransToGrafana checkout with --local.

Playbook: AGENTS.md → Grafana dashboard updates.
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from copy import deepcopy
from pathlib import Path

from ktranslate_upstream import dashboard_dir

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads"

SNMP_GROUP_FILTER = 'snmp_group=~"$snmp_group"'
KENTIK_SNMP_SELECTOR = re.compile(r"(kentik_snmp_\w+)(\{([^}]*)\})?")


def patch_expr(expr: str) -> tuple[str, bool]:
    if "kentik_snmp_" not in expr or "snmp_group=~" in expr:
        return expr, False

    def repl(match: re.Match[str]) -> str:
        metric = match.group(1)
        if match.group(2):
            inner = match.group(3) or ""
            if "snmp_group=~" in inner:
                return match.group(0)
            if inner.strip():
                return f"{metric}{{{SNMP_GROUP_FILTER},{inner}}}"
            return f"{metric}{{{SNMP_GROUP_FILTER}}}"
        return f"{metric}{{{SNMP_GROUP_FILTER}}}"

    new = KENTIK_SNMP_SELECTOR.sub(repl, expr)
    return new, new != expr

KNOWN_UIDS = [
    "ktranslate-health",
    "ktranslate-device-summary",
    "ktranslate-device-details",
    "ktranslate-architecture",
    "mavgvqv",
    "magz6qw1",
    "masjqrs",
    "ktranslate-flow-summary",
    "lab-ktranslate-flow",
]

SNMP_GROUP_VARIABLE = {
    "kind": "QueryVariable",
    "spec": {
        "name": "snmp_group",
        "current": {"text": "All", "value": ["$__all"]},
        "label": "SNMP group",
        "hide": "dontHide",
        "refresh": "onTimeRangeChanged",
        "skipUrlSync": False,
        "query": {
            "kind": "DataQuery",
            "group": "prometheus",
            "version": "v0",
            "datasource": {"name": "$datasource"},
            "spec": {
                "label": "snmp_group",
                "metric": "kentik_snmp_PollingHealth",
                "qryType": 1,
                "query": "label_values(kentik_snmp_PollingHealth,snmp_group)",
                "refId": "PrometheusVariableQueryEditor-VariableQuery",
            },
        },
        "regex": "",
        "regexApplyTo": "value",
        "sort": "alphabeticalAsc",
        "options": [],
        "multi": True,
        "includeAll": True,
        "allValue": ".*",
        "allowCustomValue": True,
    },
}

SNMP_GROUP_VARIABLE_HEALTH = deepcopy(SNMP_GROUP_VARIABLE)
SNMP_GROUP_VARIABLE_HEALTH["spec"]["query"]["datasource"] = {"name": "grafanacloud-prom"}
SNMP_GROUP_VARIABLE_HEALTH["spec"]["query"]["spec"].pop("labelFilters", None)


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


def walk_patch(obj, hits: list, path: str = "") -> bool:
    changed = False
    if isinstance(obj, dict):
        if "expr" in obj and isinstance(obj["expr"], str):
            new, did = patch_expr(obj["expr"])
            if did:
                hits.append({"path": path, "from": obj["expr"], "to": new})
                obj["expr"] = new
                changed = True
        for k, v in obj.items():
            if walk_patch(v, hits, f"{path}.{k}" if path else k):
                changed = True
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if walk_patch(v, hits, f"{path}[{i}]"):
                changed = True
    return changed


def variable_names(variables: list) -> set[str]:
    names: set[str] = set()
    for var in variables or []:
        spec = var.get("spec") or {}
        name = spec.get("name")
        if name:
            names.add(name)
    return names


def insert_snmp_group_variable(variables: list, *, health_style: bool = False) -> bool:
    if "snmp_group" in variable_names(variables):
        return False
    template = SNMP_GROUP_VARIABLE_HEALTH if health_style else SNMP_GROUP_VARIABLE
    insert_at = 0
    for i, var in enumerate(variables):
        spec = var.get("spec") or {}
        if spec.get("name") == "datasource":
            insert_at = i + 1
            break
        if spec.get("name") == "provider":
            insert_at = i
            break
    variables.insert(insert_at, deepcopy(template))
    return True


def patch_device_variable_filters(variables: list) -> bool:
    changed = False
    for var in variables or []:
        spec = var.get("spec") or {}
        if spec.get("name") not in {"device_name", "instance"}:
            continue
        query = (spec.get("query") or {}).get("spec") or {}
        filters = query.setdefault("labelFilters", [])
        if any(f.get("label") == "snmp_group" for f in filters):
            continue
        filters.insert(
            0,
            {"label": "snmp_group", "op": "=~", "value": "$snmp_group"},
        )
        q = query.get("query") or ""
        if "snmp_group=~" not in q and "kentik_snmp_" in q:
            q = re.sub(
                r"(kentik_snmp_\w+)(\{)",
                r'\1{snmp_group=~"$snmp_group",',
                q,
                count=1,
            )
            query["query"] = q
        changed = True
    return changed


def patch_manifest(manifest: dict) -> dict:
    spec = manifest.setdefault("spec", {})
    variables = spec.setdefault("variables", [])
    title = (spec.get("title") or "").lower()
    health_style = "health" in title and "device" not in title
    hits: list[dict] = []
    var_added = insert_snmp_group_variable(variables, health_style=health_style)
    var_filters = patch_device_variable_filters(variables)
    expr_changed = walk_patch(spec.get("elements") or {}, hits, "elements")
    layout_kind = (spec.get("layout") or {}).get("kind")
    return {
        "title": spec.get("title"),
        "layout": layout_kind,
        "variable_added": var_added,
        "variable_filters": var_filters,
        "expr_changes": len(hits),
        "hits": hits[:20],
    }


def patch_uid(context: str, uid: str, *, dry_run: bool = False) -> dict:
    manifest = gcx_json(context, ["dashboards", "get", uid])
    summary = patch_manifest(manifest)
    if not any(
        summary[k]
        for k in ("variable_added", "variable_filters", "expr_changes")
        if summary.get(k)
    ):
        return {"uid": uid, "status": "skipped", **summary}
    result = {"uid": uid, "status": "patched" if not dry_run else "would_patch", **summary}
    if dry_run:
        return result
    manifest.setdefault("metadata", {}).setdefault("annotations", {})[
        "grafana.app/message"
    ] = "Add snmp_group credential-group filter (KtransToGrafana global.user_tags)"
    tmp = OUT / f"_snmp-group-patch-{context}-{uid}.json"
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
        result["error"] = (proc.stdout + proc.stderr)[-800:]
        return result
    verify = gcx_json(context, ["dashboards", "get", uid])
    result["layout_after"] = (verify.get("spec") or {}).get("layout", {}).get("kind")
    result["generation"] = verify.get("metadata", {}).get("generation")
    return result


def patch_local_file(path: Path, *, dry_run: bool = False) -> dict:
    manifest = json.loads(path.read_text(encoding="utf-8"))
    uid = (manifest.get("metadata") or {}).get("name") or path.stem
    summary = patch_manifest(manifest)
    if not any(summary.get(k) for k in ("variable_added", "variable_filters", "expr_changes")):
        return {"uid": uid, "file": str(path), "status": "skipped", **summary}
    result = {"uid": uid, "file": str(path), "status": "patched" if not dry_run else "would_patch", **summary}
    if not dry_run:
        path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return result


def discover_uids(context: str) -> list[str]:
    search = gcx_json(context, ["api", "/api/search?type=dash-db&limit=500"])
    uids: list[str] = []
    for d in search:
        uid = d.get("uid") or ""
        title = (d.get("title") or "").lower()
        folder = (d.get("folderTitle") or "").lower()
        if uid in KNOWN_UIDS or any(
            k in title or k in folder for k in ("ktranslate", "network device", "network lab")
        ):
            if "flow" in title and "device" not in title:
                continue
            uids.append(uid)
    for uid in KNOWN_UIDS:
        if uid not in uids:
            uids.append(uid)
    return sorted(set(uids))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("context", nargs="?", help="gcx context (omit with --local)")
    parser.add_argument("uids", nargs="*", help="optional explicit dashboard UIDs")
    parser.add_argument("--local", action="store_true", help="patch JSON in KtransToGrafana dashboards/")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if args.local:
        targets = sorted(dashboard_dir().glob("*.json"))
        report = []
        for path in targets:
            if "Flow" in path.name:
                print(f"skip flow dashboard {path.name}")
                continue
            print(f"=== {path.name} ===")
            report.append(patch_local_file(path, dry_run=args.dry_run))
        out = OUT / "snmp-group-patch-report-local.json"
        out.write_text(json.dumps(report, indent=2), encoding="utf-8")
        print(f"\nWrote {out}")
        patched = [r for r in report if r.get("status") == "patched"]
        print(f"Patched {len(patched)} / {len(report)} local dashboards")
        return

    if not args.context:
        parser.error("context required unless --local")

    uids = args.uids or discover_uids(args.context)
    report = []
    for uid in uids:
        if "flow" in uid:
            continue
        print(f"\n=== {uid} ===")
        try:
            res = patch_uid(args.context, uid, dry_run=args.dry_run)
        except subprocess.CalledProcessError as e:
            res = {"uid": uid, "status": "error", "error": str(e)}
        report.append(res)
        print(json.dumps(res, indent=2))

    out = OUT / f"snmp-group-patch-report-{args.context}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(f"\nWrote {out}")
    patched = [r for r in report if r.get("status") == "patched"]
    print(f"Patched {len(patched)} / {len(report)} dashboards")


if __name__ == "__main__":
    main()
