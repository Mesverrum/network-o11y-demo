#!/usr/bin/env python3
"""Pull + reorganize marcnetterfield1 ktranslate dashboards (v2 TabsLayout-safe).

Operator playbook: docs/grafana-dashboard-playbook.md

Workflow:
  1. Export live dashboards from marcnetterfield1 (source of truth).
  2. Renumber titles 00–04, migrate to friendly UIDs.
  3. Tune panel heights; preserve legends and TabsLayout.

Uses v2 HTTP API (GRAFANA_URL + GRAFANA_TOKEN from local/.env). Does not use
legacy POST /api/dashboards/db — that flattens TabsLayout.

Usage:
  python3 local/scripts/reorganize-marcnetterfield-dashboards.py pull
  python3 local/scripts/reorganize-marcnetterfield-dashboards.py plan
  python3 local/scripts/reorganize-marcnetterfield-dashboards.py apply
  python3 local/scripts/reorganize-marcnetterfield-dashboards.py apply --dry-run
  python3 local/scripts/reorganize-marcnetterfield-dashboards.py apply --delete-legacy
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / ".dash-payloads" / "marcnetterfield-live"
STAGING = ROOT / ".dash-payloads" / "marcnetterfield-reorg"
NS = "stacks-1061129"
FOLDER = "network-lab"

# Current UIDs on marcnetterfield1 (may include legacy random ids)
SOURCE_UIDS = [
    "ktrans-arch-replication",
    "masjqrs",
    "be8hpir89dds0a",
    "mavgvqv",
    "magz6qw1",
]

# Target ordering and friendly UIDs
CATALOG = [
    {
        "order": "00",
        "title": "00. Ktranslate Architecture",
        "slug": "ktranslate-architecture",
        "sources": ["ktrans-arch-replication", "ktranslate-architecture"],
        "layout": "GridLayout",
    },
    {
        "order": "01",
        "title": "01. Ktranslate Health",
        "slug": "ktranslate-health",
        "sources": ["masjqrs", "ktranslate-health"],
        "layout": "TabsLayout",
    },
    {
        "order": "02",
        "title": "02. Network Flow Summary",
        "slug": "ktranslate-flow-summary",
        "sources": ["be8hpir89dds0a", "ktranslate-flow-summary", "lab-ktranslate-flow"],
        "layout": "RowsLayout",
    },
    {
        "order": "03",
        "title": "03. Network Device Summary",
        "slug": "ktranslate-device-summary",
        "sources": ["mavgvqv", "ktranslate-device-summary"],
        "layout": "TabsLayout",
    },
    {
        "order": "04",
        "title": "04. Network Device Details",
        "slug": "ktranslate-device-details",
        "sources": ["magz6qw1", "ktranslate-device-details"],
        "layout": "TabsLayout",
    },
]

UID_MAP = {
    "ktrans-arch-replication": "ktranslate-architecture",
    "masjqrs": "ktranslate-health",
    "be8hpir89dds0a": "ktranslate-flow-summary",
    "mavgvqv": "ktranslate-device-summary",
    "magz6qw1": "ktranslate-device-details",
    "ktranslate-architecture": "ktranslate-architecture",
    "ktranslate-health": "ktranslate-health",
    "ktranslate-flow-summary": "ktranslate-flow-summary",
    "ktranslate-device-summary": "ktranslate-device-summary",
    "ktranslate-device-details": "ktranslate-device-details",
    "lab-ktranslate-flow": "ktranslate-flow-summary",
}

# Panel height hints (grid units) — avoid huge whitespace on text/markdown, enough for charts
HEIGHT = {
    "text": 10,
    "stat": 6,
    "timeseries": 10,
    "table": 12,
    "barchart": 10,
    "piechart": 10,
    "heatmap": 12,
    "default": 10,
}


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api(env: dict[str, str], method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
    base = env["GRAFANA_URL"].rstrip("/")
    token = env["GRAFANA_TOKEN"]
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"raw": raw[:2000]}
        return e.code, payload


def get_dashboard(env: dict[str, str], uid: str) -> dict | None:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{uid}"
    status, data = api(env, "GET", path)
    if status == 404:
        return None
    if status != 200:
        raise RuntimeError(f"GET {uid} -> {status}: {data}")
    return data


def list_dashboards(env: dict[str, str]) -> list[dict]:
    status, data = api(env, "GET", "/api/search?type=dash-db&limit=500")
    if status != 200:
        raise RuntimeError(f"search failed: {status} {data}")
    return data if isinstance(data, list) else []


def pull_live(env: dict[str, str]) -> None:
    LIVE.mkdir(parents=True, exist_ok=True)
    found: dict[str, str] = {}
    for entry in CATALOG:
        for src in entry["sources"]:
            dash = get_dashboard(env, src)
            if dash:
                found[entry["slug"]] = src
                path = LIVE / f"{src}.json"
                path.write_text(json.dumps(dash, indent=2), encoding="utf-8")
                layout = (dash.get("spec") or {}).get("layout", {}).get("kind", "?")
                title = (dash.get("spec") or {}).get("title", "?")
                print(f"pulled {src} -> {path.name}  layout={layout}  title={title!r}")
                break
        else:
            print(f"WARN: none of {entry['sources']} found for {entry['slug']}")

    manifest = {k: {"source_uid": v, "target_uid": k} for k, v in found.items()}
    (LIVE / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(f"\nWrote {len(found)} dashboards to {LIVE}")


def replace_uid_links(obj: Any) -> Any:
    """Rewrite /d/olduid/ links and uid references in dashboard JSON."""
    if isinstance(obj, str):
        s = obj
        for old, new in UID_MAP.items():
            if old == new:
                continue
            s = s.replace(f"/d/{old}/", f"/d/{new}/")
            s = s.replace(f"`{old}`", f"`{new}`")
        return s
    if isinstance(obj, dict):
        return {k: replace_uid_links(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [replace_uid_links(v) for v in obj]
    return obj


def panel_viz_group(el: dict) -> str:
    try:
        return el["spec"]["vizConfig"]["group"]
    except (KeyError, TypeError):
        return "default"


def tune_layout_heights(dash: dict) -> int:
    """Adjust grid item heights in v2 layout without touching TabsLayout tab structure."""
    spec = dash.get("spec") or {}
    layout = spec.get("layout") or {}
    kind = layout.get("kind", "")
    changed = 0

    if kind == "GridLayout":
        items = layout.get("spec", {}).get("items", [])
        elements = spec.get("elements") or {}
        for item in items:
            if not isinstance(item, dict):
                continue
            key = item.get("element", {}).get("name") or item.get("elementName")
            if not key:
                continue
            el = elements.get(key, {})
            group = panel_viz_group(el)
            target_h = HEIGHT.get(group, HEIGHT["default"])
            pos = item.setdefault("spec", {})
            old_h = pos.get("height")
            # Only shrink oversized text panels; don't inflate charts
            if group == "text" and (old_h is None or old_h > target_h + 2):
                pos["height"] = target_h
                changed += 1
            elif group in ("timeseries", "table", "barchart") and old_h is not None and old_h < 8:
                pos["height"] = target_h
                changed += 1

    elif kind == "TabsLayout":
        # Only tune grid heights inside each tab's nested layout — never reorder tabs/panels
        tabs = layout.get("spec", {}).get("tabs", [])
        for tab in tabs:
            tab_layout = (tab.get("layout") or {}).get("spec", {})
            if (tab.get("layout") or {}).get("kind") != "GridLayout":
                continue
            for item in tab_layout.get("items", []):
                key = item.get("element", {}).get("name") or item.get("elementName")
                if not key:
                    continue
                el = (spec.get("elements") or {}).get(key, {})
                group = panel_viz_group(el)
                pos = item.setdefault("spec", {})
                if group == "text" and pos.get("height", 99) > HEIGHT["text"] + 2:
                    pos["height"] = HEIGHT["text"]
                    changed += 1
                elif group == "timeseries" and pos.get("height", 0) < 8:
                    pos["height"] = HEIGHT["timeseries"]
                    changed += 1

    elif kind == "RowsLayout":
        rows = layout.get("spec", {}).get("rows", [])
        elements = spec.get("elements") or {}
        for row in rows:
            row_layout = row.get("layout") or {}
            if row_layout.get("kind") != "GridLayout":
                continue
            for item in row_layout.get("spec", {}).get("items", []):
                key = item.get("element", {}).get("name") or item.get("elementName")
                if not key:
                    continue
                el = elements.get(key, {})
                group = panel_viz_group(el)
                pos = item.setdefault("spec", {})
                if group == "text" and pos.get("height", 99) > HEIGHT["text"] + 2:
                    pos["height"] = HEIGHT["text"]
                    changed += 1
                elif group in ("timeseries", "table", "barchart") and pos.get("height", 0) < 8:
                    pos["height"] = HEIGHT.get(group, HEIGHT["default"])
                    changed += 1

    return changed


def preserve_legends(dash: dict) -> None:
    """Ensure legendFormat on PromQL queries is never blank when a panel has multiple queries."""
    elements = (dash.get("spec") or {}).get("elements") or {}

    def walk_queries(el: dict) -> None:
        try:
            queries = el["spec"]["data"]["spec"]["queries"]
        except (KeyError, TypeError):
            return
        if not isinstance(queries, list) or len(queries) < 2:
            return
        empty = [
            q
            for q in queries
            if ((q.get("spec") or {}).get("query", {}).get("spec") or {}).get("expr")
            and not ((q.get("spec") or {}).get("query", {}).get("spec") or {}).get("legendFormat")
        ]
        if len(empty) < 2:
            return
        for q in empty:
            qspec = (q.get("spec") or {}).get("query", {}).get("spec") or {}
            expr = qspec.get("expr", "")
            lf = qspec.get("legendFormat")
            if not expr:
                continue
            if lf is None or lf == "":
                if "device_name" in expr and "if_" in expr:
                    qspec["legendFormat"] = "{{device_name}} {{if_Description}}"
                elif "device_name" in expr:
                    qspec["legendFormat"] = "{{device_name}}"
                elif "service_name" in expr or "svc" in expr:
                    qspec["legendFormat"] = "{{service_name}}"

    for el in elements.values():
        if isinstance(el, dict):
            walk_queries(el)


def prepare_dashboard(dash: dict, entry: dict, source_uid: str) -> dict:
    out = copy.deepcopy(dash)
    out = replace_uid_links(out)

    spec = out.setdefault("spec", {})
    spec["title"] = entry["title"]
    spec["description"] = (spec.get("description") or "").strip()
    if spec["description"]:
        spec["description"] += "\n\n"
    spec["description"] += (
        f"Network lab dashboard ({entry['order']}). "
        "Interface bps uses ktranslate delta gauges: `(octets) * 8 / 60`."
    )

    meta = out.setdefault("metadata", {})
    meta["name"] = entry["slug"]
    meta["namespace"] = NS
    for k in ("resourceVersion", "generation", "creationTimestamp", "uid"):
        meta.pop(k, None)
    ann = meta.setdefault("annotations", {})
    ann["grafana.app/folder"] = FOLDER
    ann["grafana.app/message"] = (
        f"Reorganized {entry['order']}: friendly UID {entry['slug']} (from {source_uid})"
    )
    out["_source_uid"] = source_uid

    layout_kind = (spec.get("layout") or {}).get("kind", "")
    if layout_kind != entry["layout"]:
        print(f"  WARN {entry['slug']}: layout is {layout_kind}, expected {entry['layout']}")

    tune_layout_heights(out)
    preserve_legends(out)
    return out


def build_staging(env: dict[str, str]) -> list[Path]:
    manifest_path = LIVE / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(f"Run pull first — missing {manifest_path}")

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    STAGING.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    source_by_slug: dict[str, str] = {}

    for entry in CATALOG:
        slug = entry["slug"]
        info = manifest.get(slug)
        if not info:
            print(f"SKIP {slug}: not in pull manifest")
            continue
        source_uid = info["source_uid"]
        source_by_slug[slug] = source_uid
        src_path = LIVE / f"{source_uid}.json"
        if not src_path.is_file():
            raise SystemExit(f"missing {src_path}")

        dash = json.loads(src_path.read_text(encoding="utf-8"))
        prepared = prepare_dashboard(dash, entry, source_uid)
        out_path = STAGING / f"{slug}.json"
        out_path.write_text(json.dumps(prepared, indent=2), encoding="utf-8")
        written.append(out_path)
        layout = prepared.get("spec", {}).get("layout", {}).get("kind")
        n_elem = len(prepared.get("spec", {}).get("elements") or {})
        print(f"staged {slug}  layout={layout}  elements={n_elem}  <- {source_uid}")

    plan = {
        "target_uids": [e["slug"] for e in CATALOG],
        "retire_uids": [u for u in SOURCE_UIDS if u not in {e["slug"] for e in CATALOG}],
        "source_by_slug": source_by_slug,
        "urls": {e["slug"]: f"{env['GRAFANA_URL'].rstrip('/')}/d/{e['slug']}" for e in CATALOG},
    }
    (STAGING / "plan.json").write_text(json.dumps(plan, indent=2), encoding="utf-8")
    return written, source_by_slug


def upsert_dashboard(env: dict[str, str], dash: dict, uid: str, source_uid: str | None = None) -> str:
    dash = copy.deepcopy(dash)
    dash.pop("_source_uid", None)
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{uid}"
    status, existing = api(env, "GET", path)

    if status == 200 and isinstance(existing, dict):
        rv = (existing.get("metadata") or {}).get("resourceVersion")
        if rv:
            dash["metadata"]["resourceVersion"] = rv
        labels = (existing.get("metadata") or {}).get("labels") or {}
        if "grafana.app/deprecatedInternalID" in labels:
            dash.setdefault("metadata", {}).setdefault("labels", {})
            dash["metadata"]["labels"]["grafana.app/deprecatedInternalID"] = labels[
                "grafana.app/deprecatedInternalID"
            ]
        status, out = api(env, "PUT", path, dash)
        action = "updated"
    elif source_uid and source_uid != uid:
        # v2 API cannot rename metadata.name on PUT — create fresh UID, retire legacy later
        dash["metadata"].pop("resourceVersion", None)
        (dash.get("metadata", {}).get("labels") or {}).pop("grafana.app/deprecatedInternalID", None)
        create = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards"
        status, out = api(env, "POST", create, dash)
        action = "created"
        if status == 409:
            status, existing = api(env, "GET", path)
            if status == 200:
                rv = (existing.get("metadata") or {}).get("resourceVersion")
                if rv:
                    dash["metadata"]["resourceVersion"] = rv
                labels = (existing.get("metadata") or {}).get("labels") or {}
                if "grafana.app/deprecatedInternalID" in labels:
                    dash.setdefault("metadata", {}).setdefault("labels", {})
                    dash["metadata"]["labels"]["grafana.app/deprecatedInternalID"] = labels[
                        "grafana.app/deprecatedInternalID"
                    ]
                status, out = api(env, "PUT", path, dash)
                action = "updated"
    else:
        dash.get("metadata", {}).get("labels", {}).pop("grafana.app/deprecatedInternalID", None)
        create = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards"
        status, out = api(env, "POST", create, dash)
        action = "created"
        if status == 409:
            status, existing = api(env, "GET", path)
            if status == 200:
                rv = (existing.get("metadata") or {}).get("resourceVersion")
                if rv:
                    dash["metadata"]["resourceVersion"] = rv
                labels = (existing.get("metadata") or {}).get("labels") or {}
                if "grafana.app/deprecatedInternalID" in labels:
                    dash.setdefault("metadata", {}).setdefault("labels", {})
                    dash["metadata"]["labels"]["grafana.app/deprecatedInternalID"] = labels[
                        "grafana.app/deprecatedInternalID"
                    ]
                status, out = api(env, "PUT", path, dash)
                action = "updated"

    if not (200 <= int(status) < 300):
        raise RuntimeError(f"{action} {uid} failed {status}: {out}")
    return action


def delete_dashboard(env: dict[str, str], uid: str) -> bool:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{uid}"
    status, _ = api(env, "DELETE", path)
    return status in (200, 202, 204, 404)


def apply(env: dict[str, str], dry_run: bool, delete_legacy: bool) -> None:
    written, source_by_slug = build_staging(env)
    if dry_run:
        print(f"\ndry-run: staged {len(written)} dashboards in {STAGING}")
        return

    for path in written:
        uid = path.stem
        dash = json.loads(path.read_text(encoding="utf-8"))
        layout = dash.get("spec", {}).get("layout", {}).get("kind")
        source_uid = source_by_slug.get(uid) or dash.pop("_source_uid", None)
        action = upsert_dashboard(env, dash, uid, source_uid=source_uid)
        print(f"{action} {uid}  layout={layout}  -> {env['GRAFANA_URL'].rstrip('/')}/d/{uid}")

    if delete_legacy:
        for old in SOURCE_UIDS:
            if old in {e["slug"] for e in CATALOG}:
                continue
            status, _ = api(env, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{old}")
            if status == 200 and delete_dashboard(env, old):
                print(f"deleted legacy {old}")


def cmd_plan(_env: dict[str, str]) -> None:
    build_staging(_env)
    plan = json.loads((STAGING / "plan.json").read_text(encoding="utf-8"))
    print(json.dumps(plan, indent=2))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["pull", "plan", "apply"])
    ap.add_argument("--dry-run", action="store_true", help="Stage only, no writes")
    ap.add_argument(
        "--delete-legacy",
        action="store_true",
        help="Delete old random UIDs after successful apply",
    )
    args = ap.parse_args()

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        raise SystemExit("Set GRAFANA_URL and GRAFANA_TOKEN in local/.env")

    if args.command == "pull":
        pull_live(env)
    elif args.command == "plan":
        cmd_plan(env)
    elif args.command == "apply":
        apply(env, args.dry_run, args.delete_legacy)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
