#!/usr/bin/env python3
"""Patch A4 Alloy Device Details one step at a time (TabsLayout-safe v2).

Always GET live first, then PUT. Never POST /api/dashboards/db.

Usage:
  python local/scripts/patch-alloy-device-details.py --list
  python local/scripts/patch-alloy-device-details.py vars-scope
  python local/scripts/patch-alloy-device-details.py overview-system-info
  python local/scripts/patch-alloy-device-details.py overview-polling
  python local/scripts/patch-alloy-device-details.py overview-scrape-time
  python local/scripts/patch-alloy-device-details.py move-scrape-to-telemetry
  python local/scripts/patch-alloy-device-details.py events
"""
from __future__ import annotations

import argparse
import copy
import json
import os
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / ".dash-payloads" / "alloy-device-details"
NS = os.environ.get("GRAFANA_NAMESPACE", "stacks-1061129")
UID = "alloy-device-details"
JOB = "alloy-snmp"
SEL = f'job="{JOB}",snmp_group=~"$snmp_group",device_name=~"$instance"'


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    env.update({k: v for k, v in os.environ.items() if k.startswith("GRAFANA_")})
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
        with urllib.request.urlopen(req, timeout=300) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            payload = {"raw": raw[:2000]}
        return e.code, payload


def get_live(env: dict[str, str]) -> dict:
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{UID}"
    code, doc = api(env, "GET", path)
    if code != 200 or not isinstance(doc, dict):
        raise RuntimeError(f"GET {UID} failed HTTP {code}: {doc}")
    return doc


def put_live(env: dict[str, str], doc: dict, message: str) -> dict:
    body = copy.deepcopy(doc)
    body.setdefault("metadata", {}).setdefault("annotations", {})["grafana.app/message"] = message
    path = f"/apis/dashboard.grafana.app/v2/namespaces/{NS}/dashboards/{UID}"
    code, out = api(env, "PUT", path, body)
    if code not in (200, 201):
        raise RuntimeError(f"PUT {UID} failed HTTP {code}: {out}")
    kind = ((out or {}).get("spec") or {}).get("layout", {}).get("kind")
    gen = ((out or {}).get("metadata") or {}).get("generation")
    print(f"updated {UID} layout={kind} generation={gen}")
    if kind != "TabsLayout":
        raise RuntimeError("TabsLayout lost — restore from version history")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{UID}-live.json").write_text(json.dumps(out, indent=2), encoding="utf-8")
    return out


def var_by_name(doc: dict, name: str) -> dict:
    for v in (doc.get("spec") or {}).get("variables") or []:
        if (v.get("spec") or {}).get("name") == name:
            return v
    raise KeyError(name)


def set_label_values(
    var: dict,
    *,
    metric: str,
    query: str,
    label: str,
    filters: list[dict] | None = None,
) -> None:
    q = var["spec"]["query"]
    q["datasource"] = {"name": "${datasource}"}
    qspec = q.setdefault("spec", {})
    qspec["metric"] = metric
    qspec["query"] = query
    qspec["label"] = label
    qspec["qryType"] = 1
    if filters is not None:
        qspec["labelFilters"] = filters


def set_prom_expr(
    panel: dict,
    expr: str,
    *,
    ref: str = "A",
    legend: str | None = None,
    instant: bool | None = None,
) -> None:
    queries = ((panel.get("spec") or {}).get("data") or {}).get("spec", {}).get("queries") or []
    for q in queries:
        qspec = q.get("spec") or {}
        if qspec.get("refId") != ref:
            continue
        inner = ((qspec.get("query") or {}).get("spec") or {})
        inner["expr"] = expr
        if legend is not None:
            inner["legendFormat"] = legend
        if instant is not None:
            inner["instant"] = instant
            inner["range"] = not instant
            inner["queryType"] = "instant" if instant else "range"
            qspec["instant"] = instant
        return
    raise KeyError(f"query {ref} not found")


def hide_query(panel: dict, ref: str) -> None:
    queries = ((panel.get("spec") or {}).get("data") or {}).get("spec", {}).get("queries") or []
    for q in queries:
        if (q.get("spec") or {}).get("refId") == ref:
            q["spec"]["hidden"] = True
            return


def set_unit_thresholds(panel: dict, unit: str, steps: list[dict]) -> None:
    defaults = (
        ((panel.get("spec") or {}).get("vizConfig") or {})
        .get("spec", {})
        .get("fieldConfig", {})
        .get("defaults")
    )
    if not isinstance(defaults, dict):
        raise KeyError("fieldConfig.defaults")
    defaults["unit"] = unit
    defaults["thresholds"] = {"mode": "absolute", "steps": steps}


def rename_row(doc: dict, old: str, new: str) -> int:
    found = 0

    def walk(node: Any) -> None:
        nonlocal found
        if isinstance(node, dict):
            spec = node.get("spec")
            if node.get("kind") == "RowsLayoutRow" and isinstance(spec, dict):
                if spec.get("title") == old:
                    spec["title"] = new
                    found += 1
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk((doc.get("spec") or {}).get("layout"))
    return found


def set_sql_expr(panel: dict, expression: str, *, ref: str = "B") -> None:
    queries = ((panel.get("spec") or {}).get("data") or {}).get("spec", {}).get("queries") or []
    for q in queries:
        qspec = q.get("spec") or {}
        if qspec.get("refId") != ref:
            continue
        inner = ((qspec.get("query") or {}).get("spec") or {})
        inner["expression"] = expression
        return
    raise KeyError(f"sql query {ref} not found")


def step_vars_scope(doc: dict) -> str:
    """Point device picker at Alloy SNMP (job=alloy-snmp)."""
    snmp_group = var_by_name(doc, "snmp_group")
    set_label_values(
        snmp_group,
        metric="snmp_CPU",
        query=f'label_values(snmp_CPU{{job="{JOB}"}},snmp_group)',
        label="snmp_group",
        filters=[{"label": "job", "op": "=", "value": JOB}],
    )
    snmp_group["spec"]["hide"] = "dontHide"

    instance = var_by_name(doc, "instance")
    set_label_values(
        instance,
        metric="snmp_CPU",
        query=(
            f'label_values(snmp_CPU{{job="{JOB}",snmp_group=~"$snmp_group"}},device_name)'
        ),
        label="device_name",
        filters=[
            {"label": "job", "op": "=", "value": JOB},
            {"label": "snmp_group", "op": "=~", "value": "$snmp_group"},
        ],
    )
    instance["spec"]["current"] = {"text": "spine1", "value": "spine1"}

    provider = var_by_name(doc, "provider")
    provider["spec"]["hide"] = "hideVariable"
    provider["spec"]["description"] = (
        "ktranslate-only filter; hidden on the Alloy board (no provider label)."
    )

    has_polling = var_by_name(doc, "has_polling")
    set_label_values(
        has_polling,
        metric="up",
        query=f'label_values(up{{job="{JOB}",device_name=~"$instance"}},device_name)',
        label="device_name",
        filters=[
            {"label": "job", "op": "=", "value": JOB},
            {"label": "device_name", "op": "=~", "value": "$instance"},
        ],
    )
    return "vars: snmp_group/instance/has_polling → alloy-snmp; hide provider"


def step_overview_system_info(doc: dict) -> str:
    panel = (doc.get("spec") or {}).get("elements", {}).get("panel-60")
    if not panel:
        raise KeyError("panel-60")
    expr = (
        f"max by (device_name) (snmp_Uptime{{{SEL}}}) "
        f"* on (device_name) group_left(sysName, sysDescr, sysObjectID, snmp_group, deployment_host) "
        f"max by (device_name, sysName, sysDescr, sysObjectID, snmp_group, deployment_host) "
        f"(snmp_device_info{{{SEL}}})"
    )
    set_prom_expr(panel, expr, ref="A")
    set_sql_expr(
        panel,
        "SELECT DISTINCT Field, Details FROM (\n"
        "  SELECT 'Device Name' AS Field, COALESCE(sysName, device_name, 'N/A') AS Details FROM A\n"
        "  UNION ALL SELECT 'sysObjectID', COALESCE(sysObjectID, 'N/A') FROM A\n"
        "  UNION ALL SELECT 'Deployment host', COALESCE(deployment_host, 'N/A') FROM A\n"
        "  UNION ALL SELECT 'SNMP Group', COALESCE(snmp_group, 'N/A') FROM A\n"
        "  UNION ALL SELECT 'Uptime', CONCAT(FLOOR(__value__ / 8640000), 'd ', "
        "FLOOR(__value__ / 100 % 86400 / 3600), 'h ', FLOOR(__value__ / 100 % 3600 / 60), 'm') FROM A\n"
        "  UNION ALL SELECT 'Description', COALESCE(sysDescr, 'N/A') FROM A\n"
        ") t\nLIMIT 10",
        ref="B",
    )
    panel["spec"]["description"] = (
        "Alloy identity from snmp_device_info (sysName/sysDescr/sysObjectID) plus "
        "snmp_Uptime (SNMPv2 TimeTicks). job=alloy-snmp."
    )
    return "panel-60 System Info → snmp_device_info + snmp_Uptime"


def step_overview_polling(doc: dict) -> str:
    health = (doc.get("spec") or {}).get("elements", {}).get("panel-99")
    status = (doc.get("spec") or {}).get("elements", {}).get("panel-100")
    if not health or not status:
        raise KeyError("panel-99/100")
    set_prom_expr(
        health,
        f'min by (device_name) (up{{{SEL}}})',
        ref="A",
    )
    health["spec"]["description"] = (
        "Alloy scrape up across hot+cold targets (min). 1 = both scrapes up, 0 = a target is down."
    )
    # 0/1 mappings already match Healthy/Unknown; drop ktranslate timeout=6
    maps = (
        ((health.get("spec") or {}).get("vizConfig") or {})
        .get("spec", {})
        .get("fieldConfig", {})
        .get("defaults", {})
        .get("mappings")
        or []
    )
    for m in maps:
        opts = m.get("options") or {}
        opts.pop("6", None)
        if "0" in opts:
            opts["0"]["text"] = "Unhealthy"
            opts["0"]["color"] = "red"

    set_prom_expr(
        status,
        f'max by (device_name) (up{{job="{JOB}",snmp_tier="hot",snmp_group=~"$snmp_group",device_name=~"$instance"}})',
        ref="A",
    )
    status["spec"]["description"] = (
        "Alloy hot-tier scrape (60s). 1 = Active, 0 = Inactive. job=alloy-snmp, snmp_tier=hot."
    )
    return "panel-99/100 Polling Health/Status → up{job=alloy-snmp}"


WALK = (
    f"snmp_scrape_walk_duration_seconds{{{SEL}}}"
)
RETRIES = (
    f"snmp_scrape_packets_retried{{{SEL}}}"
)
LEGEND_MODULE = "{{module}} ({{snmp_tier}})"
WALK_STEPS = [
    {"value": 0, "color": "green"},
    {"value": 1, "color": "yellow"},
    {"value": 5, "color": "red"},
]
RETRY_STEPS = [
    {"value": 0, "color": "green"},
    {"value": 1, "color": "yellow"},
    {"value": 5, "color": "red"},
]


def step_overview_scrape_time(doc: dict) -> str:
    """Replace Ping row with per-module SNMP walk time (not ICMP RTT)."""
    has_ping = var_by_name(doc, "has_ping")
    set_label_values(
        has_ping,
        metric="snmp_scrape_walk_duration_seconds",
        query=(
            f'label_values(snmp_scrape_walk_duration_seconds{{job="{JOB}",device_name=~"$instance"}},device_name)'
        ),
        label="device_name",
        filters=[
            {"label": "job", "op": "=", "value": JOB},
            {"label": "device_name", "op": "=~", "value": "$instance"},
        ],
    )
    has_ping["spec"]["description"] = (
        "Gates the SNMP scrape-time row (walk duration exists). Not ICMP ping."
    )

    els = (doc.get("spec") or {}).get("elements") or {}
    current = els.get("panel-66")
    chart = els.get("panel-68")
    loss_chart = els.get("panel-69")
    loss_stat = els.get("panel-70")
    if not all((current, chart, loss_chart, loss_stat)):
        raise KeyError("panel-66/68/69/70")

    current["spec"]["title"] = "SNMP scrape time (current)"
    current["spec"]["description"] = (
        "Last SNMP walk duration per module (if_mib / nokia_srlinux hot, "
        "if_mib_meta / ip_addr cold). Not ICMP ping RTT. job=alloy-snmp."
    )
    set_prom_expr(current, WALK, ref="A", legend=LEGEND_MODULE, instant=True)
    set_unit_thresholds(current, "s", WALK_STEPS)
    opts = ((current.get("spec") or {}).get("vizConfig") or {}).get("spec", {}).get("options") or {}
    reduce = opts.setdefault("reduceOptions", {})
    reduce["values"] = True
    reduce["calcs"] = ["lastNotNull"]

    chart["spec"]["title"] = "SNMP scrape time"
    chart["spec"]["description"] = (
        "snmp_scrape_walk_duration_seconds — one series per SNMP module. "
        "This is walk time, not ping RTT. Hot = 60s if_mib + nokia_srlinux; "
        "cold = 5m if_mib_meta + ip_addr."
    )
    set_prom_expr(chart, WALK, ref="A", legend=LEGEND_MODULE, instant=False)
    hide_query(chart, "B")
    hide_query(chart, "C")
    set_unit_thresholds(chart, "s", WALK_STEPS)

    loss_stat["spec"]["title"] = "SNMP scrape retries (current)"
    loss_stat["spec"]["description"] = (
        "Packets retried on the last SNMP walk, per module. 0 is healthy. "
        "Not ICMP packet loss."
    )
    set_prom_expr(loss_stat, RETRIES, ref="A", legend=LEGEND_MODULE, instant=True)
    set_unit_thresholds(loss_stat, "short", RETRY_STEPS)
    loss_opts = ((loss_stat.get("spec") or {}).get("vizConfig") or {}).get("spec", {}).get("options") or {}
    loss_reduce = loss_opts.setdefault("reduceOptions", {})
    loss_reduce["values"] = True
    loss_reduce["calcs"] = ["lastNotNull"]

    loss_chart["spec"]["title"] = "SNMP scrape retries"
    loss_chart["spec"]["description"] = (
        "snmp_scrape_packets_retried per module. Replaces ping packet loss — "
        "Alloy has no ICMP path yet."
    )
    set_prom_expr(loss_chart, RETRIES, ref="A", legend=LEGEND_MODULE, instant=False)
    set_unit_thresholds(loss_chart, "short", RETRY_STEPS)

    age_ts = els.get("panel-61")
    age_s = els.get("panel-203")
    if age_ts:
        set_prom_expr(
            age_ts,
            f"max by (device_name) (max_over_time(timestamp({WALK})[24h:1m])) * 1000",
            ref="A",
            legend="Last SNMP scrape",
        )
        try:
            set_prom_expr(
                age_ts,
                f"max by (device_name) (max_over_time(timestamp(snmp_Uptime{{{SEL}}})[24h:1m])) * 1000",
                ref="D",
                legend="Last SNMP identity",
            )
        except KeyError:
            pass
        age_ts["spec"]["description"] = (
            "Absolute timestamp of the last SNMP walk and identity sample. "
            "No ping series on the Alloy path."
        )
    if age_s:
        set_prom_expr(
            age_s,
            f"min by (device_name) (time() - max_over_time(timestamp({WALK})[24h:1m]))",
            ref="A",
            legend="SNMP scrape age",
        )
        set_prom_expr(
            age_s,
            f"min by (device_name) (time() - max_over_time(timestamp(snmp_Uptime{{{SEL}}})[24h:1m]))",
            ref="B",
            legend="SNMP identity age",
        )
        age_s["spec"]["description"] = (
            "Seconds since last SNMP walk / snmp_Uptime sample. "
            "Green < 2m, yellow < 5m. Not ping age."
        )

    n = rename_row(doc, "Ping", "SNMP scrape")
    if n != 1:
        raise RuntimeError(f"expected 1 Ping row, renamed {n}")
    return "Ping row → per-module snmp_scrape_walk_duration_seconds + retries"


def tab_rows(doc: dict, title: str) -> list:
    for tab in ((doc.get("spec") or {}).get("layout") or {}).get("spec", {}).get("tabs") or []:
        tspec = tab.get("spec") or {}
        if tspec.get("title") != title:
            continue
        rows = ((tspec.get("layout") or {}).get("spec") or {}).get("rows")
        if not isinstance(rows, list):
            raise KeyError(f"tab {title} has no rows")
        return rows
    raise KeyError(f"tab {title}")


def step_move_scrape_to_telemetry(doc: dict) -> str:
    overview = tab_rows(doc, "Overview")
    telemetry = tab_rows(doc, "Telemetry")
    idx = next(
        (i for i, row in enumerate(overview) if (row.get("spec") or {}).get("title") == "SNMP scrape"),
        None,
    )
    if idx is None:
        raise RuntimeError("Overview has no SNMP scrape row")
    row = overview.pop(idx)
    if any((r.get("spec") or {}).get("title") == "SNMP scrape" for r in telemetry):
        raise RuntimeError("Telemetry already has SNMP scrape")
    telemetry.insert(0, row)
    return "moved SNMP scrape row Overview → Telemetry (first)"


def step_events(doc: dict) -> str:
    """Retarget Events tab Loki from ktranslate to alloy-syslog / alloy-snmptrap."""
    import runpy

    mod = runpy.run_path(str(Path(__file__).resolve().parent / "patch-alloy-event-panels.py"))
    notes = mod["patch_a4"](doc)
    return "events: " + ", ".join(notes)


def step_telemetry_collection_source(doc: dict) -> str:
    els = (doc.get("spec") or {}).get("elements") or {}
    collector = els.get("panel-342")
    group = els.get("panel-343")
    profile = els.get("panel-344")
    if not all((collector, group, profile)):
        raise KeyError("panel-342/343/344")
    collector["spec"]["title"] = "Collector"
    collector["spec"]["description"] = (
        "Alloy instance scraping this device (deployment_host). job=alloy-snmp."
    )
    set_prom_expr(
        collector,
        f"max by (deployment_host) (up{{{SEL}}})",
        ref="A",
        legend="{{deployment_host}}",
        instant=True,
    )
    group["spec"]["description"] = (
        "Discovery job name (snmp_group): hq / branch1 / branch2 on colocated."
    )
    set_prom_expr(
        group,
        f"max by (snmp_group) (snmp_device_info{{{SEL}}})",
        ref="A",
        legend="{{snmp_group}}",
        instant=True,
    )
    profile["spec"]["title"] = "SNMP tier"
    profile["spec"]["description"] = (
        "Hot (60s) vs cold (5m) scrape targets currently up for this device."
    )
    set_prom_expr(
        profile,
        f"max by (snmp_tier) (up{{{SEL}}})",
        ref="A",
        legend="{{snmp_tier}}",
        instant=True,
    )
    opts = ((profile.get("spec") or {}).get("vizConfig") or {}).get("spec", {}).get("options") or {}
    reduce = opts.setdefault("reduceOptions", {})
    reduce["values"] = True
    return "panel-342/343/344 Collection Source → alloy-snmp labels"


STEPS: dict[str, Callable[[dict], str]] = {
    "vars-scope": step_vars_scope,
    "overview-system-info": step_overview_system_info,
    "overview-polling": step_overview_polling,
    "overview-scrape-time": step_overview_scrape_time,
    "move-scrape-to-telemetry": step_move_scrape_to_telemetry,
    "telemetry-collection-source": step_telemetry_collection_source,
    "events": step_events,
}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("steps", nargs="*")
    ap.add_argument("--list", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    if args.list or not args.steps:
        print("steps:")
        for name in STEPS:
            print(f"  {name}")
        if not args.steps:
            return 0 if args.list else 2

    env = load_env()
    if not env.get("GRAFANA_URL") or not env.get("GRAFANA_TOKEN"):
        print("GRAFANA_URL and GRAFANA_TOKEN required", file=sys.stderr)
        return 1

    doc = get_live(env)
    src_kind = ((doc.get("spec") or {}).get("layout") or {}).get("kind")
    src_gen = (doc.get("metadata") or {}).get("generation")
    print(f"live {UID} layout={src_kind} generation={src_gen}")
    if src_kind != "TabsLayout":
        print("refusing to patch a non-TabsLayout board", file=sys.stderr)
        return 1

    notes = []
    for name in args.steps:
        fn = STEPS.get(name)
        if not fn:
            print(f"unknown step {name}", file=sys.stderr)
            return 2
        notes.append(fn(doc))
        print(f"applied {name}: {notes[-1]}")

    if args.dry_run:
        OUT.mkdir(parents=True, exist_ok=True)
        (OUT / f"{UID}-dry-run.json").write_text(json.dumps(doc, indent=2), encoding="utf-8")
        print("dry-run: not PUT")
        return 0

    put_live(env, doc, " | ".join(notes))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
