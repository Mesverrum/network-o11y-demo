#!/usr/bin/env python3
"""Turn SolarWinds raw exports into Grafana recreation reference docs.

Consumes the tree produced by Export-SwReferenceInventory.ps1:

  raw/classic-views/**/view.json
  raw/modern-dashboards/*.json
  raw/manifest.json

Writes:

  docs/README.md                 - catalog + mapping cheat sheet
  docs/classic-views/<slug>.md   - one page per classic view
  docs/modern-dashboards/<slug>.md
  docs/inventory.json            - machine-readable summary
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

# Rough SolarWinds resource -> Grafana panel hints (classic Orion widgets).
RESOURCE_HINTS: dict[str, str] = {
    "Custom Chart": "timeseries / heatmap - port SWQL/SQL series into PromQL or Infinity/SQL",
    "Custom Object Resource": "stat / table - map NetObject fields to labels",
    "Custom Query": "table - SWQL -> Grafana Infinity/SQL or convert to PromQL",
    "Custom HTML": "text (markdown/html) or canvas",
    "Top XX": "bar gauge / table - topk() in PromQL",
    "List of Nodes": "table - inventory from kentik_snmp_* / entity metrics",
    "List of Interfaces": "table - interface metrics (ifHC* / errors)",
    "Map": "geomap / nodeGraph - topology_exporter + LLDP edges",
    "Active Alerts": "alert list / table - Grafana Alerting or Loki",
    "Events": "logs panel - Loki",
    "PerfStack": "timeseries dashboard - multi-entity explore",
    "Chart for": "timeseries",
    "Gauge": "gauge / stat",
    "Availability": "stat / status history",
}


def slugify(text: str, fallback: str = "item") -> str:
    s = re.sub(r"[^\w\s-]", "", text or "", flags=re.UNICODE)
    s = re.sub(r"[-\s]+", "-", s.strip()).strip("-").lower()
    return s or fallback


def load_json(path: Path) -> Any:
    # PowerShell Set-Content -Encoding UTF8 writes a BOM on Windows.
    return json.loads(path.read_text(encoding="utf-8-sig"))


def hint_for_resource(resource_name: str, resource_file: str) -> str:
    name = resource_name or ""
    for key, hint in RESOURCE_HINTS.items():
        if key.lower() in name.lower():
            return hint
    if resource_file:
        return f"Inspect `{resource_file}` widget type; map to closest Grafana panel"
    return "Map to Grafana panel by widget purpose (table / timeseries / stat / text)"


def interesting_props(props: dict[str, Any]) -> list[tuple[str, str]]:
    """Prefer query/entity props that matter for Grafana recreation."""
    priority_keys = (
        "SWQL",
        "SqlQuery",
        "SQL",
        "Query",
        "EntityUri",
        "NetObject",
        "Filter",
        "WhereClause",
        "Title",
        "Subtitle",
        "ChartTitle",
        "ResourceTitle",
        "Period",
        "SampleSize",
        "DataSource",
        "Metric",
        "Columns",
    )
    out: list[tuple[str, str]] = []
    seen: set[str] = set()
    lower_map = {str(k).lower(): (str(k), str(v) if v is not None else "") for k, v in props.items()}

    for want in priority_keys:
        for lk, (orig, val) in lower_map.items():
            if want.lower() in lk and orig not in seen and val.strip():
                seen.add(orig)
                out.append((orig, val))
    # Include remaining short props (skip huge blobs already covered)
    for orig, val in ((str(k), str(v) if v is not None else "") for k, v in props.items()):
        if orig in seen or not val.strip():
            continue
        if len(val) > 2000:
            out.append((orig, val[:2000] + "\n... [truncated]"))
            seen.add(orig)
        elif len(out) < 40:
            out.append((orig, val))
            seen.add(orig)
    return out


def md_escape(s: str) -> str:
    return s.replace("|", "\\|")


def write_classic_view_doc(view: dict[str, Any], out_path: Path) -> dict[str, Any]:
    title = view.get("viewTitle") or f"View {view.get('viewId')}"
    group = view.get("viewGroupName") or "NoViewGroup"
    resources = view.get("resources") or []

    lines: list[str] = [
        f"# {title}",
        "",
        f"- **Kind:** classic Orion view",
        f"- **View ID:** `{view.get('viewId')}`",
        f"- **View group:** {group}",
        f"- **View type:** `{view.get('viewType')}`",
        f"- **Columns:** `{view.get('columns')}` widths `{view.get('columnWidths')}`",
        f"- **Resources:** {len(resources)}",
        "",
        "## Grafana recreation notes",
        "",
        "Rebuild as a Grafana dashboard (prefer TabsLayout if the view group is a multi-tab NOC set).",
        "Treat each resource as one panel; preserve column/position as grid x/y.",
        "",
        "## Layout (column -> position)",
        "",
        "| Col | Pos | Title | Resource type | Grafana hint |",
        "|-----|-----|-------|---------------|--------------|",
    ]

    for r in sorted(resources, key=lambda x: (x.get("viewColumn") or 0, x.get("position") or 0)):
        rtitle = r.get("resourceTitle") or r.get("resourceName") or ""
        rname = r.get("resourceName") or ""
        hint = hint_for_resource(rname, r.get("resourceFile") or "")
        lines.append(
            f"| {r.get('viewColumn')} | {r.get('position')} | {md_escape(rtitle)} | "
            f"`{md_escape(rname)}` | {md_escape(hint)} |"
        )

    lines += ["", "## Resources (detail)", ""]
    for idx, r in enumerate(sorted(resources, key=lambda x: (x.get("viewColumn") or 0, x.get("position") or 0)), 1):
        rtitle = r.get("resourceTitle") or r.get("resourceName") or f"resource-{idx}"
        lines += [
            f"### {idx}. {rtitle}",
            "",
            f"- Resource ID: `{r.get('resourceId')}`",
            f"- Type: `{r.get('resourceName')}`",
            f"- File: `{r.get('resourceFile')}`",
            f"- Subtitle: {r.get('resourceSubTitle') or '-'}",
            f"- Grafana hint: {hint_for_resource(r.get('resourceName') or '', r.get('resourceFile') or '')}",
            "",
        ]
        props = interesting_props(r.get("properties") or {})
        if props:
            lines += ["**Properties (queries / filters first):**", ""]
            for pk, pv in props:
                fence = "sql" if any(x in pk.lower() for x in ("sql", "swql", "query")) else ""
                if "\n" in pv or len(pv) > 120:
                    lines += [f"- `{pk}`:", "", f"```{fence}", pv.rstrip(), "```", ""]
                else:
                    lines.append(f"- `{pk}`: `{pv}`")
            lines.append("")
        else:
            lines += ["_No resource properties exported._", ""]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "kind": "classic-view",
        "id": view.get("viewId"),
        "title": title,
        "group": group,
        "resourceCount": len(resources),
        "doc": str(out_path),
    }


def iter_modern_widgets(obj: dict[str, Any]) -> list[dict[str, Any]]:
    """Best-effort walk of modern dashboard JSON for widget-like nodes."""
    found: list[dict[str, Any]] = []

    def walk(node: Any, trail: str = "") -> None:
        if isinstance(node, dict):
            keys = {k.lower() for k in node}
            looks_widget = (
                ("type" in node and ("title" in node or "name" in node))
                or "visualization" in keys
                or "widgetid" in keys
                or ("configuration" in keys and "type" in keys)
            )
            if looks_widget and ("type" in node or "visualization" in node):
                found.append(
                    {
                        "trail": trail,
                        "type": node.get("type") or node.get("visualization"),
                        "title": node.get("title") or node.get("name") or "",
                        "id": node.get("id") or node.get("widgetId") or node.get("unique_key"),
                        "raw": node,
                    }
                )
            for k, v in node.items():
                walk(v, f"{trail}.{k}" if trail else k)
        elif isinstance(node, list):
            for i, v in enumerate(node):
                walk(v, f"{trail}[{i}]")

    walk(obj)
    # de-dupe by id/title/type
    uniq: list[dict[str, Any]] = []
    seen: set[str] = set()
    for w in found:
        key = f"{w.get('id')}|{w.get('title')}|{w.get('type')}"
        if key in seen:
            continue
        seen.add(key)
        uniq.append(w)
    return uniq


def extract_queries_from_widget(widget: dict[str, Any]) -> list[str]:
    queries: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                lk = str(k).lower()
                if lk in {"swql", "query", "sql", "promql", "expression"} and isinstance(v, str) and v.strip():
                    queries.append(f"{k}: {v.strip()}")
                else:
                    walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(widget.get("raw") or widget)
    return queries[:12]


def write_modern_dash_doc(obj: dict[str, Any], meta: dict[str, Any], out_path: Path) -> dict[str, Any]:
    dash = obj.get("dashboards") or {}
    if isinstance(dash, list):
        dash = dash[0] if dash else {}
    name = dash.get("name") or meta.get("name") or "Modern dashboard"
    widgets = iter_modern_widgets(obj)

    lines: list[str] = [
        f"# {name}",
        "",
        f"- **Kind:** modern dashboard (Fusion)",
        f"- **Dashboard ID:** `{meta.get('dashboardId', '-')}`",
        f"- **Unique key:** `{dash.get('unique_key') or meta.get('uniqueKey') or '-'}`",
        f"- **System:** `{meta.get('isSystem', False)}`",
        f"- **Widgets detected:** {len(widgets)}",
        "",
        "## Grafana recreation notes",
        "",
        "Modern dashboards map more cleanly 1:1 to Grafana panels than classic views.",
        "Preserve widget titles; translate SWQL data providers to Prometheus / Loki / Infinity.",
        "Tabbed/grouped modern dashboards may need per-tab exports (ParentID children).",
        "",
        "## Widgets",
        "",
        "| Title | Type | Queries / config cues |",
        "|-------|------|------------------------|",
    ]

    for w in widgets:
        qs = extract_queries_from_widget(w)
        cue = "<br>".join(md_escape(q[:200]) for q in qs) if qs else "-"
        lines.append(
            f"| {md_escape(str(w.get('title') or ''))} | `{md_escape(str(w.get('type') or ''))}` | {cue} |"
        )

    lines += ["", "## Widget detail", ""]
    for idx, w in enumerate(widgets, 1):
        lines += [
            f"### {idx}. {w.get('title') or '(untitled)'}",
            "",
            f"- Type: `{w.get('type')}`",
            f"- Id: `{w.get('id')}`",
            f"- JSON path: `{w.get('trail')}`",
            "",
        ]
        qs = extract_queries_from_widget(w)
        if qs:
            lines += ["```", *qs, "```", ""]

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")
    return {
        "kind": "modern-dashboard",
        "id": meta.get("dashboardId"),
        "title": name,
        "widgetCount": len(widgets),
        "doc": str(out_path),
    }


def build_catalog(
    manifest: dict[str, Any],
    classic_entries: list[dict[str, Any]],
    modern_entries: list[dict[str, Any]],
    resource_type_counts: Counter[str],
    out_dir: Path,
) -> None:
    lines = [
        "# SolarWinds -> Grafana reference catalog",
        "",
        f"Generated: `{datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}`",
        "",
        "## Source inventory",
        "",
        f"- Orion host: `{manifest.get('hostname', 'unknown')}`",
        f"- Exported at: `{manifest.get('exportedAt', 'unknown')}`",
        f"- Classic views: **{len(classic_entries)}**",
        f"- Modern dashboards: **{len(modern_entries)}**",
        "",
        "## How to use these docs",
        "",
        "1. Pick a high-value view/dashboard from the tables below.",
        "2. Open its markdown page - layout + widget properties/queries are the recreation contract.",
        "3. Rebuild in Grafana on marcnetterfield1 (or your stack) using the SolarWinds datasource "
        "plugin where SWQL still applies, or retarget to ktranslate/PromQL for the network-o11y lab model.",
        "",
        "## Classic resource type frequency",
        "",
        "| Resource type | Count | Default Grafana hint |",
        "|---------------|------:|----------------------|",
    ]
    for rtype, count in resource_type_counts.most_common():
        lines.append(f"| `{md_escape(rtype)}` | {count} | {md_escape(hint_for_resource(rtype, ''))} |")

    lines += ["", "## Classic views", "", "| Group | View | Resources | Doc |", "|-------|------|----------:|-----|"]
    for e in sorted(classic_entries, key=lambda x: (x.get("group") or "", x.get("title") or "")):
        rel = Path(e["doc"]).relative_to(out_dir).as_posix()
        lines.append(
            f"| {md_escape(e.get('group') or '')} | {md_escape(e.get('title') or '')} | "
            f"{e.get('resourceCount', 0)} | [{rel}]({rel}) |"
        )

    lines += ["", "## Modern dashboards", "", "| Name | Widgets | Doc |", "|------|--------:|-----|"]
    for e in sorted(modern_entries, key=lambda x: x.get("title") or ""):
        rel = Path(e["doc"]).relative_to(out_dir).as_posix()
        lines.append(
            f"| {md_escape(e.get('title') or '')} | {e.get('widgetCount', 0)} | [{rel}]({rel}) |"
        )

    lines += [
        "",
        "## Mapping cheat sheet (classic)",
        "",
        "| SolarWinds concept | Grafana target |",
        "|--------------------|----------------|",
        "| View group (tabs/menu) | Folder + dashboard links, or TabsLayout |",
        "| View column / position | Panel gridPos |",
        "| Resource (widget) | Panel |",
        "| ResourceProperties SWQL/SQL | Panel query (SolarWinds DS, Infinity, or PromQL rewrite) |",
        "| NOC view rotation | Playlist or dashboard links |",
        "| Modern dashboard JSON | Near 1:1 panel model |",
        "",
    ]
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True, type=Path, help="Path to raw/ export root")
    ap.add_argument("--output", required=True, type=Path, help="Path to write docs/")
    args = ap.parse_args()

    raw: Path = args.input
    out: Path = args.output
    out.mkdir(parents=True, exist_ok=True)
    (out / "classic-views").mkdir(exist_ok=True)
    (out / "modern-dashboards").mkdir(exist_ok=True)

    manifest_path = raw / "manifest.json"
    manifest = load_json(manifest_path) if manifest_path.exists() else {}

    classic_entries: list[dict[str, Any]] = []
    modern_entries: list[dict[str, Any]] = []
    resource_types: Counter[str] = Counter()
    used_slugs: dict[str, int] = defaultdict(int)

    def unique_slug(base: str) -> str:
        used_slugs[base] += 1
        n = used_slugs[base]
        return base if n == 1 else f"{base}-{n}"

    for view_path in sorted((raw / "classic-views").glob("**/view.json")):
        view = load_json(view_path)
        for r in view.get("resources") or []:
            resource_types[r.get("resourceName") or "(unknown)"] += 1
        base = slugify(f"{view.get('viewGroupName', 'group')}-{view.get('viewTitle', view_path.stem)}")
        doc_path = out / "classic-views" / f"{unique_slug(base)}.md"
        classic_entries.append(write_classic_view_doc(view, doc_path))

    md_index_path = raw / "modern-dashboards" / "index.json"
    md_index = {str(e.get("dashboardId")): e for e in (load_json(md_index_path) if md_index_path.exists() else [])}

    for dash_path in sorted((raw / "modern-dashboards").glob("*.json")):
        if dash_path.name == "index.json":
            continue
        obj = load_json(dash_path)
        # filename starts with id_
        m = re.match(r"^(\d+)_", dash_path.name)
        meta = md_index.get(m.group(1), {}) if m else {}
        if not meta:
            meta = {"dashboardId": int(m.group(1)) if m else None, "name": dash_path.stem}
        dash = obj.get("dashboards") or {}
        if isinstance(dash, list):
            dash = dash[0] if dash else {}
        base = slugify(dash.get("name") or meta.get("name") or dash_path.stem)
        doc_path = out / "modern-dashboards" / f"{unique_slug(base)}.md"
        modern_entries.append(write_modern_dash_doc(obj, meta, doc_path))

    build_catalog(manifest, classic_entries, modern_entries, resource_types, out)

    inventory = {
        "manifest": manifest,
        "classicViews": [
            {k: v for k, v in e.items() if k != "doc"} | {"doc": Path(e["doc"]).relative_to(out).as_posix()}
            for e in classic_entries
        ],
        "modernDashboards": [
            {k: v for k, v in e.items() if k != "doc"} | {"doc": Path(e["doc"]).relative_to(out).as_posix()}
            for e in modern_entries
        ],
        "resourceTypeCounts": dict(resource_types.most_common()),
    }
    (out / "inventory.json").write_text(json.dumps(inventory, indent=2), encoding="utf-8")

    print(f"Wrote catalog: {out / 'README.md'}")
    print(f"Classic view docs: {len(classic_entries)}")
    print(f"Modern dashboard docs: {len(modern_entries)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
