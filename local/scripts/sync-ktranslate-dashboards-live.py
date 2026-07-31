#!/usr/bin/env python3
"""Analyze pulled ktranslate dashboards and write agent reference docs.

Reads local/.dash-payloads/marcnetterfield-live/*.json (from reorganize pull).
Dashboard JSON source of truth: KtransToGrafana repo (KTRANS_UPSTREAM).

Writes:
  - local/docs/ktranslate-dashboard-live-snapshot.md  (full per-dashboard inventory)
  - local/docs/dashboard-query-lessons.md             (operator patterns, refreshed)

Usage:
  python3 local/scripts/sync-ktranslate-dashboards-live.py
  python3 local/scripts/sync-ktranslate-dashboards-live.py --pull   # pull then analyze
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ktranslate_upstream import DASHBOARD_FILES, dashboard_dir, resolve_upstream

ROOT = Path(__file__).resolve().parents[1]
LIVE = ROOT / ".dash-payloads" / "marcnetterfield-live"
SNAPSHOT = ROOT / "docs" / "ktranslate-dashboard-live-snapshot.md"
LESSONS = ROOT / "docs" / "dashboard-query-lessons.md"

CATALOG = [
    ("ktranslate-architecture", "00. Ktranslate Architecture", "GridLayout"),
    ("ktranslate-health", "01. Ktranslate Health", "TabsLayout"),
    ("ktranslate-flow-summary", "02. Network Flow Summary", "RowsLayout"),
    ("ktranslate-device-summary", "03. Network Device Summary", "TabsLayout"),
    ("ktranslate-device-details", "04. Network Device Details", "TabsLayout"),
]

# Filenames in KtransToGrafana dashboards/
EXPORT_NAMES = DASHBOARD_FILES


def norm(expr: str) -> str:
    return re.sub(r"\s+", " ", expr.strip())


def walk_classic_panels(panels: list[dict], out: list[dict], path: str = "") -> None:
    for p in panels:
        title = p.get("title") or f"panel-{p.get('id')}"
        ppath = f"{path}/{title}" if path else title
        ptype = p.get("type", "")
        for t in p.get("targets", []):
            expr = t.get("expr")
            if expr:
                out.append(
                    {
                        "path": ppath,
                        "title": title,
                        "type": ptype,
                        "expr": norm(expr),
                        "datasource": (t.get("datasource") or {}).get("type")
                        if isinstance(t.get("datasource"), dict)
                        else t.get("datasource"),
                        "instant": t.get("instant"),
                        "legendFormat": t.get("legendFormat"),
                    }
                )
        for sub in p.get("panels") or []:
            walk_classic_panels([sub], out, ppath)


def walk_v2_elements(manifest: dict, out: list[dict]) -> None:
    elements = manifest.get("spec", {}).get("elements", {})
    for name, el in elements.items():
        if el.get("kind") != "Panel":
            continue
        pspec = el.get("spec", {})
        title = pspec.get("title", name)
        ptype = pspec.get("vizConfig", {}).get("group", "")
        queries = pspec.get("queries") or []
        data = pspec.get("data", {})
        if data.get("kind") == "QueryGroup":
            queries = data.get("spec", {}).get("queries", queries)
        for q in queries:
            qwrap = q.get("spec", q)
            qspec = qwrap.get("query", {}).get("spec", qwrap.get("query", {}))
            if not isinstance(qspec, dict):
                continue
            expr = qspec.get("expr")
            ds = qwrap.get("datasource", {})
            ds_type = ds.get("type") if isinstance(ds, dict) else ds
            if expr:
                out.append(
                    {
                        "path": title,
                        "title": title,
                        "type": ptype,
                        "expr": norm(expr),
                        "datasource": ds_type,
                        "instant": qspec.get("instant"),
                        "legendFormat": qspec.get("legendFormat"),
                    }
                )


def extract_queries(manifest: dict) -> list[dict]:
    rows: list[dict] = []
    spec = manifest.get("spec", manifest.get("dashboard", {}))
    if isinstance(manifest.get("dashboard"), dict):
        spec = manifest["dashboard"].get("spec", manifest["dashboard"])
    if spec.get("panels"):
        walk_classic_panels(spec["panels"], rows)
    if spec.get("elements"):
        walk_v2_elements(manifest if manifest.get("spec") else {"spec": spec}, rows)
    return rows


def extract_variables(manifest: dict) -> list[dict]:
    spec = manifest.get("spec", {})
    vars_: list[dict] = []
    # v2
    for v in spec.get("variables", []) or []:
        vs = v.get("spec", v)
        vars_.append({"name": vs.get("name"), "query": vs.get("query"), "hide": vs.get("hide")})
    # classic templating
    for v in (spec.get("templating") or {}).get("list", []) or []:
        vars_.append({"name": v.get("name"), "query": v.get("query"), "hide": v.get("hide")})
    return vars_


def load_dashboard(uid: str) -> dict:
    path = LIVE / f"{uid}.json"
    if not path.is_file():
        raise FileNotFoundError(f"missing {path} — run: python3 scripts/reorganize-marcnetterfield-dashboards.py pull")
    return json.loads(path.read_text(encoding="utf-8"))


def pattern_flags(rows: list[dict]) -> dict[str, int]:
    exprs = [r["expr"] for r in rows]
    joined = "\n".join(exprs)
    return {
        "promql_queries": len(rows),
        "loki_queries": sum(1 for r in rows if r.get("datasource") == "loki"),
        "memory_utilization": sum(1 for e in exprs if "MemoryUtilization" in e),
        "memory_manual_ratio": sum(
            1 for e in exprs if "MemoryUsed" in e and ("MemoryAvailable" in e or "MemoryFree" in e) and "/" in e
        ),
        "bps_delta_60": sum(1 for e in exprs if "* 8 / 60" in e),
        "errors_per_60": sum(1 for e in exprs if "ifInErrors" in e and "/ 60" in e),
        "rate_kentik_snmp": sum(1 for e in exprs if re.search(r"rate\(kentik_snmp_", e)),
        "max_over_time_flow": sum(1 for e in exprs if "max_over_time(network_io_by_flow" in e),
        "rate_flow": sum(1 for e in exprs if re.search(r"rate\(network_io_by_flow", e)),
        "chf_snmp_traps_rate": sum(1 for e in exprs if "rate(kentik_ktranslate_chf_kkc_snmp_traps" in e),
        "loki_traps": sum(1 for e in exprs if "count_over_time" in e and ("trap" in e.lower() or "KSnmpTrap" in e)),
        "or_vector_0": sum(1 for e in exprs if "OR vector(0)" in e),
        "max_by_device": sum(1 for e in exprs if re.search(r"max by\s*\(\s*device_name\s*\)", e)),
        "ping_metrics": sum(1 for e in exprs if "kentik_ping_" in e),
        "bgp_established_str": sum(1 for e in exprs if 'tBgpPeerNgConnState="established"' in e or "established" in e and "tBgpPeerNgConnState" in e),
        "bgp_established_6": sum(1 for e in exprs if "tBgpPeerNgConnState" in e and "== 6" in e),
        "instant_timeseries": sum(
            1 for r in rows if r.get("instant") is True and "timeseries" in str(r.get("type", "")).lower()
        ),
    }


def summarize_variables(vars_: list[dict]) -> list[str]:
    lines: list[str] = []
    for v in vars_:
        name = v.get("name") or "?"
        q = v.get("query")
        if isinstance(q, dict):
            metric = q.get("metric", "")
            label = q.get("label", "")
            lines.append(f"- `{name}` → label `{label}` on metric `{metric}`")
        elif isinstance(q, str) and q:
            lines.append(f"- `{name}` → `{q[:100]}`")
        elif name and not str(name).startswith("has_"):
            lines.append(f"- `{name}`")
    return lines[:30]


def gate_variables(vars_: list[dict]) -> list[str]:
    out: list[str] = []
    for v in vars_:
        name = v.get("name") or ""
        if not name.startswith("has_"):
            continue
        q = v.get("query")
        metric = q.get("metric", "?") if isinstance(q, dict) else "?"
        out.append(f"| `{name}` | `{metric}` |")
    return out


def build_snapshot(analyses: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines = [
        "# ktranslate dashboards — live snapshot\n",
        f"\nPulled from Grafana Cloud (`local/.env`) on **{now}**.\n",
        "Re-pull: `python3 local/scripts/sync-ktranslate-dashboards-live.py --pull`\n",
        "\n| # | UID | Layout | Generation | PromQL | Loki |\n",
        "|---|-----|--------|------------|--------|------|\n",
    ]
    for a in analyses:
        f = a["flags"]
        lines.append(
            f"| {a['order']} | `{a['uid']}` | {a['layout']} | {a['generation']} | "
            f"{f['promql_queries']} | {f['loki_queries']} |\n"
        )

    for a in analyses:
        lines.append(f"\n## {a['title']} (`{a['uid']}`)\n")
        lines.append(f"- **Generation:** {a['generation']}\n")
        lines.append(f"- **Layout:** {a['layout']}\n")
        lines.append("\n### Pattern counts\n\n")
        lines.append("| Pattern | Count |\n|---------|-------|\n")
        for k, v in sorted(a["flags"].items()):
            if k in ("promql_queries", "loki_queries"):
                continue
            if v:
                lines.append(f"| {k.replace('_', ' ')} | {v} |\n")

        vlines = summarize_variables(a["variables"])
        if vlines:
            lines.append("\n### Key variables\n\n")
            lines.extend(f"{x}\n" for x in vlines)

        gates = gate_variables(a["variables"])
        if gates:
            lines.append("\n### `has_*` gate metrics (device-details)\n\n")
            lines.append("| Variable | Gate metric |\n|----------|-------------|\n")
            lines.extend(f"{g}\n" for g in gates[:20])
            if len(gates) > 20:
                lines.append(f"\n… and {len(gates) - 20} more `has_*` gates\n")

        # Notable unique expr samples
        samples = a.get("notable_exprs", [])
        if samples:
            lines.append("\n### Notable queries (sample)\n\n")
            for title, expr in samples[:12]:
                lines.append(f"- **{title}:** `{expr[:200]}`\n")

    return "".join(lines)


def build_lessons(analyses: list[dict]) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    # Aggregate across all dashboards
    totals: Counter[str] = Counter()
    for a in analyses:
        for k, v in a["flags"].items():
            totals[k] += v

    lines = [
        "# Dashboard query & UI lessons (agent notes)\n",
        f"\n**Dashboard JSON:** [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) `dashboards/` "
        f"(set `KTRANS_UPSTREAM` in `local/.env` if not `../KtransToGrafana`). "
        f"**Live drift check:** `local/.dash-payloads/marcnetterfield-live/` (refreshed {now}). "
        f"Re-pull: `make -C local dash-live-sync`. Push to stack: `make -C local dash-push`.\n",
        "\nCompared prior agent patches vs operator/Assistant edits on all five ktranslate dashboards (00–04).\n",
        "\n## Operator patterns — always use these\n\n",
        "| Topic | Use | Do not use |\n",
        "|-------|-----|------------|\n",
        "| **Memory %** | `kentik_snmp_MemoryUtilization{$sel}` | Manual `MemoryUsed/MemoryAvailable` ratios |\n",
        "| **Interface bps** | `(kentik_snmp_ifHCInOctets{...}) * 8 / 60` | `rate(kentik_snmp_ifHC*Octets[...])` |\n",
        "| **Interface errors/s** | `(kentik_snmp_ifInErrors{...}) / 60` | `rate(kentik_snmp_if*Errors[...])` |\n",
        "| **Flow bytes** | `max_over_time(network_io_by_flow_bytes[...])` | `rate(network_io_by_flow_bytes[...])` |\n",
        "| **Trap volume** | Loki `{service_name=~\"ktranslate.*\"} \\| json \\| eventType=\"KSnmpTrap\"` | `\\|= \"KSnmpTrap\"`, `\\|= \"trapdata\"`, `rate(kentik_ktranslate_chf_kkc_snmp_traps[5m])` |\n",
        "| **Syslog volume** | Loki `{service_name=~\"ktranslate.*\"} \\| json \\| instrumentation_name=\"ktranslate-syslog\"` (+ `severity` for breakdown) | `\\|= \"ktranslate-syslog\"`, keyword regex on message |\n",
        "| **Internal collector logs** | Loki `{service_name=~\"ktranslate.*\"} != \"{\"` (plain-text `ktranslate/<component>` lines) | Mixing with `\\| json` trap/syslog panels |\n",
        "| **CHF metrics** | Collector health / heartbeat only | Device telemetry or event volume |\n",
        "| **Fleet stats** | `count(...) OR vector(0)` | Bare `count(...)` → \"No data\" |\n",
        "| **Stale series** | `max by(device_name)(...)` on device drill-downs | Raw selectors when ghost `src_addr` series exist |\n",
        "| **SNMP inventory** | `count by (device_name) (kentik_snmp_CPU)` | `kentik_snmp_DeviceMetrics` (AWS path) |\n",
        "| **Device drill-down** | `/d/ktranslate-device-details?var-instance=${__data.fields.device_name}` | Legacy `magz6qw1` |\n",
        "\n## Live stack counts (all dashboards)\n\n",
        f"- PromQL panel queries: **{totals['promql_queries']}**\n",
        f"- Loki queries: **{totals['loki_queries']}**\n",
        f"- `MemoryUtilization`: **{totals['memory_utilization']}** vs manual memory ratios: **{totals['memory_manual_ratio']}**\n",
        f"- BPS `* 8 / 60`: **{totals['bps_delta_60']}** vs `rate(kentik_snmp_*`: **{totals['rate_kentik_snmp']}**\n",
        f"- Flow `max_over_time`: **{totals['max_over_time_flow']}** vs `rate(network_io_by_flow`: **{totals['rate_flow']}**\n",
        f"- Loki trap panels: **{totals['loki_traps']}** vs CHF trap rate: **{totals['chf_snmp_traps_rate']}**\n",
        f"- `OR vector(0)` guards: **{totals['or_vector_0']}**\n",
        f"- `max by(device_name)` collapses: **{totals['max_by_device']}**\n",
        f"- Ping (`kentik_ping_*`): **{totals['ping_metrics']}** panels\n",
        "\n## Per-dashboard notes\n\n",
    ]

    per_uid_notes = {
        "ktranslate-architecture": (
            "GridLayout markdown + links. Sync text from `build-ktrans-arch-dashboard.py`; "
            "do not flatten to classic panels API."
        ),
        "ktranslate-health": (
            "TabsLayout CHF/jchf collector health. Facet by `service_name` (`ktranslate-snmp-*`, "
            "`ktranslate-flow-*`, …). `snmp_fail`: **1=healthy**, >1 failure codes. "
            "6h lookback panels can show stale leaf failures after IP recovery."
        ),
        "ktranslate-flow-summary": (
            "RowsLayout. Group flows by `src_host`/`dst_host` **with** IPs in legends. "
            "Country panels: `network_peer_country!~\"Private IP|undefined\"`. "
            "Use `max_over_time` on `network_io_by_flow_bytes`."
        ),
        "ktranslate-device-summary": (
            "TabsLayout fleet view. Selector: `provider` + `device_name`. "
            "Collection Health uses Loki for traps/syslog, CHF for collector counts. "
            "Memory fleet panels use `MemoryUtilization`."
        ),
        "ktranslate-device-details": (
            "TabsLayout per-device drill-down. Variable **`instance`** (= `device_name`), "
            "filtered by **`provider`**. Ping uses `kentik_ping_*`. "
            "Memory panels query `MemoryUtilization` but `has_memory` gate still checks "
            "`hrStorageUsedPercent` (0 on SRL) — memory section visibility can be wrong; "
            "prefer `max by(device_name)` on overview queries to avoid ghost `src_addr` series."
        ),
    }

    for a in analyses:
        lines.append(f"### {a['title']} (`{a['uid']}`, gen {a['generation']})\n\n")
        lines.append(f"{per_uid_notes.get(a['uid'], '')}\n\n")

    lines.extend(
        [
            "## Agent workflow\n\n",
            "1. `python3 local/scripts/sync-ktranslate-dashboards-live.py --pull` before editing patch scripts.\n",
            "2. Edit pulled v2 manifest (`spec.elements` / `spec.layout`) — never `POST /api/dashboards/db` on TabsLayout.\n",
            "3. Verify `spec.layout.kind` unchanged after PUT.\n",
            "4. Update this file + `docs/grafana-dashboard-playbook.md` when operator patterns change.\n",
            "\n## UI design notes\n\n",
            "- **TabsLayout:** keep related panels on one tab; don't duplicate stats on Overview + Resources.\n",
            "- **Tables:** hide SNMP junk labels (`job`, `mib_name`, `src_addr`, `objectIdentifier`) via transformations.\n",
            "- **Timeseries:** `instant: false` for trends; stats/gauges use instant snapshots.\n",
            "- **Δ24h stats:** current expr minus `offset 24h` subquery, both range-capable.\n",
            "- **Thresholds:** percent panels `min:0,max:100`; bps tables need unit on Value column.\n",
        ]
    )
    return "".join(lines)


def pick_notable_exprs(rows: list[dict], uid: str) -> list[tuple[str, str]]:
    """Return distinctive exprs worth documenting."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    keywords = (
        "MemoryUtilization",
        "max by(device_name)",
        "max by (device_name)",
        "count_over_time",
        "max_over_time(network_io",
        "* 8 / 60",
        "kentik_ping_",
        "snmp_fail",
        "OR vector(0)",
        "hrStorageUsedPercent",
    )
    for r in rows:
        e = r["expr"]
        if e in seen:
            continue
        if any(k in e for k in keywords) or uid == "ktranslate-health" and "chf" in e:
            seen.add(e)
            out.append((r["title"], e))
    return out[:15]


def sanitize_manifest(manifest: dict) -> dict:
    """Strip runtime fields before committing or mirroring."""
    out = json.loads(json.dumps(manifest))
    out.pop("status", None)
    meta = out.get("metadata")
    if isinstance(meta, dict):
        for k in ("resourceVersion", "generation", "creationTimestamp", "managedFields"):
            meta.pop(k, None)
    return out


def compare_upstream_drift() -> list[dict]:
    """Report whether live Grafana manifests differ from KtransToGrafana dashboards/."""
    upstream = resolve_upstream()
    dash_dir = dashboard_dir()
    rows: list[dict] = []
    for uid, filename in EXPORT_NAMES.items():
        live_path = LIVE / f"{uid}.json"
        upstream_path = dash_dir / filename
        row = {
            "uid": uid,
            "upstream": str(upstream_path),
            "live": str(live_path),
            "status": "missing-live",
        }
        if not live_path.is_file():
            rows.append(row)
            continue
        if not upstream_path.is_file():
            row["status"] = "missing-upstream"
            rows.append(row)
            continue
        live = sanitize_manifest(json.loads(live_path.read_text(encoding="utf-8")))
        upstream_manifest = sanitize_manifest(json.loads(upstream_path.read_text(encoding="utf-8")))
        if live == upstream_manifest:
            row["status"] = "in-sync"
        else:
            row["status"] = "drift"
        rows.append(row)
    return rows


def analyze_all() -> list[dict]:
    analyses: list[dict] = []
    for uid, title, layout in CATALOG:
        dash = load_dashboard(uid)
        gen = dash.get("metadata", {}).get("generation", "?")
        rows = extract_queries(dash)
        # Also try classic API shape if embedded
        if not rows and dash.get("dashboard"):
            rows = extract_queries(dash["dashboard"])
        vars_ = extract_variables(dash)
        flags = pattern_flags(rows)
        analyses.append(
            {
                "uid": uid,
                "title": title,
                "order": title[:2].strip("."),
                "layout": layout,
                "generation": gen,
                "flags": flags,
                "variables": vars_,
                "notable_exprs": pick_notable_exprs(rows, uid),
                "query_count": len(rows),
            }
        )
    return analyses


def main() -> int:
    parser = argparse.ArgumentParser(description="Sync ktranslate dashboard live snapshots to docs")
    parser.add_argument("--pull", action="store_true", help="Run reorganize pull before analyze")
    args = parser.parse_args()

    if args.pull:
        subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "reorganize-marcnetterfield-dashboards.py"), "pull"],
            check=True,
            cwd=ROOT,
        )

    analyses = analyze_all()
    SNAPSHOT.parent.mkdir(parents=True, exist_ok=True)
    SNAPSHOT.write_text(build_snapshot(analyses), encoding="utf-8")
    LESSONS.write_text(build_lessons(analyses), encoding="utf-8")
    drift = compare_upstream_drift()

    print(f"Wrote {SNAPSHOT}")
    print(f"Wrote {LESSONS}")
    upstream = resolve_upstream()
    print(f"Dashboard source of truth: {upstream / 'dashboards'}")
    for row in drift:
        print(f"  {row['uid']}: {row['status']}")
    drifted = [r for r in drift if r["status"] == "drift"]
    if drifted:
        print(
            f"WARNING: {len(drifted)} dashboard(s) differ from KtransToGrafana — "
            "edit upstream, then `make -C local dash-push`"
        )
    for a in analyses:
        print(f"  {a['uid']}: gen={a['generation']} queries={a['query_count']} layout={a['layout']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
