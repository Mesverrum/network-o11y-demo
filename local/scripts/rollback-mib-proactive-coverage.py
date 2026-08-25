#!/usr/bin/env python3
"""Roll back vendor/full-library has_* gates on Device Details.

Empty Prometheus label_values (metric does not exist) is slower than a hit on
a series that exists. ~200 dashboard-level has_* QueryVariables all fire on
open, so a stack with no kentik_snmp_* data waits out the miss path for every
proactive MIB row.

Keep capability + original sensor/protocol + lab Nokia/Lenovo + generic RFC
MIBs. Drop per-vendor / full-library remainder gates and the rows they gate.

Usage:
  python3 local/scripts/rollback-mib-proactive-coverage.py
  python3 local/scripts/rollback-mib-proactive-coverage.py --push
  python3 local/scripts/rollback-mib-proactive-coverage.py --push --write-local
"""
from __future__ import annotations

import argparse
import copy
import json
import ssl
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from ktranslate_upstream import load_local_env, path_for_uid  # noqa: E402

UID = "ktranslate-device-details"

# Capability-first keep list (bench SHORT_GATES) plus original Device Details
# extras, lab Nokia/Lenovo, and generic RFC/_general rows that are not vendor MIBs.
KEEP_EXACT = {
    "has_ping",
    "has_cpu",
    "has_cpu_percore",
    "has_cpu_breakdown",
    "has_memory",
    "has_memory_detail",
    "has_interfaces",
    "has_disk",
    "has_sensors",
    "has_polling",
    "has_temp",
    "has_temp_sensor",
    "has_fan_speed",
    "has_psu_state",
    "has_fan_state",
    "has_fru_fantray",
    "has_fru_module",
    "has_fru_power",
    "has_ospf",
    "has_ospf_if",
    "has_bgp",
    "has_bgp4",
    "has_firewall",
    "has_ntp",
    "has_hsrp",
    "has_csw",
    "has_ipsla",
    "has_connections",
    "has_cie_drops",
    "has_redundancy",
    "has_ups",
    "has_ups_alarms",
    "has_ups_bypass",
    "has_ups_input",
    "has_ups_output",
    "has_entity_phy",
    "has_hr_storage",
    "has_hr_system",
    "has_hr_processor",
    "has_lldp",
    "has_ip_if_stats",
    "has_ip_system_stats",
    "has_tcp",
    "has_udp",
    "has_ucd_disk",
    "has_ucd_diskio",
    "has_ucd_swap",
    "has_ucd_mem_detail",
    "has_ucd_cpu_detail",
    "has_tmnx_hw",
    "has_tmnx_chassis",
    "has_lenovo_health",
    "has_lenovo_fan",
    "has_lenovo_psu",
    "has_power_state",
    "has_hrswruntable",
}

KEEP_PREFIXES = (
    "has_sensor_",  # original unit-based ENTITY-SENSOR rows
    "has_flow_",  # Network Flow tab — not MIB coverage
)


def load_env() -> dict[str, str]:
    load_local_env()
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#") and "=" in s:
            k, _, v = s.partition("=")
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def api(base: str, token: str, method: str, path: str, body: Any | None = None) -> tuple[int, Any]:
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(
        base.rstrip("/") + path,
        data=data,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, context=ssl.create_default_context(), timeout=180) as resp:
            raw = resp.read().decode()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:3000]}


def keep_gate(name: str) -> bool:
    if name in KEEP_EXACT:
        return True
    return any(name.startswith(p) for p in KEEP_PREFIXES)


def has_var_name(v: dict) -> str:
    return str((v.get("spec") or {}).get("name") or "")


def gate_metric(v: dict) -> str:
    q = ((v.get("spec") or {}).get("query") or {}).get("spec") or {}
    return str(q.get("metric") or q.get("query") or "")


def row_gate(row: dict) -> str | None:
    cr = row.get("spec", {}).get("conditionalRendering") or row.get("conditionalRendering")
    if not cr:
        return None
    stack = [cr]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for key in ("variable", "name"):
                val = cur.get(key)
                if val and str(val).startswith("has_"):
                    return str(val)
            spec = cur.get("spec") or {}
            if isinstance(spec, dict):
                val = spec.get("variable") or spec.get("name")
                if val and str(val).startswith("has_"):
                    return str(val)
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def collect_element_refs(obj: Any, out: set[str]) -> None:
    if isinstance(obj, dict):
        if obj.get("kind") == "ElementReference" and obj.get("name"):
            out.add(str(obj["name"]))
        for v in obj.values():
            collect_element_refs(v, out)
    elif isinstance(obj, list):
        for item in obj:
            collect_element_refs(item, out)


def tab_rows(tab: dict) -> list[dict]:
    layout = (tab.get("spec") or {}).get("layout") or {}
    spec = layout.get("spec") or {}
    return spec.get("rows") or []


def classify_variables(dash: dict) -> tuple[list[str], list[tuple[str, str]]]:
    keep: list[str] = []
    drop: list[tuple[str, str]] = []
    for v in dash.get("spec", {}).get("variables") or []:
        name = has_var_name(v)
        if not name.startswith("has_"):
            continue
        if keep_gate(name):
            keep.append(name)
        else:
            drop.append((name, gate_metric(v)))
    return keep, drop


def strip_dashboard(dash: dict) -> dict[str, Any]:
    keep, drop = classify_variables(dash)
    drop_names = {n for n, _ in drop}

    dash["spec"]["variables"] = [
        v
        for v in dash["spec"].get("variables") or []
        if not has_var_name(v).startswith("has_") or keep_gate(has_var_name(v))
    ]

    tabs = dash["spec"]["layout"]["spec"]["tabs"]
    dropped_rows: list[dict[str, str]] = []
    dropped_refs: set[str] = set()
    surviving_refs: set[str] = set()

    for tab in tabs:
        title = str((tab.get("spec") or {}).get("title") or "")
        rows = tab_rows(tab)
        kept_rows: list[dict] = []
        for row in rows:
            g = row_gate(row)
            refs: set[str] = set()
            collect_element_refs(row, refs)
            if g and g in drop_names:
                dropped_rows.append(
                    {
                        "gate": g,
                        "tab": title,
                        "title": str((row.get("spec") or {}).get("title") or ""),
                    }
                )
                dropped_refs |= refs
            else:
                kept_rows.append(row)
                surviving_refs |= refs
        layout = tab["spec"]["layout"]
        layout["spec"]["rows"] = kept_rows

    # Elements only used by dropped rows
    orphan = dropped_refs - surviving_refs
    elements = dash["spec"].get("elements") or {}
    if isinstance(elements, dict):
        for name in orphan:
            elements.pop(name, None)

    return {
        "keep": keep,
        "drop_vars": drop,
        "dropped_rows": dropped_rows,
        "orphan_elements": sorted(orphan),
        "surviving_has": [
            has_var_name(v)
            for v in dash["spec"]["variables"]
            if has_var_name(v).startswith("has_")
        ],
    }


def push_marc(patched: dict) -> None:
    env = load_env()
    url = env["GRAFANA_URL"]
    token = env["GRAFANA_TOKEN"]
    ns = f"stacks-{env.get('GC_OTLP_ACCOUNT', '1061129')}"
    status, existing = api(
        url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}"
    )
    if status != 200:
        raise SystemExit(f"GET marc failed {status}")
    body = copy.deepcopy(patched)
    body["metadata"]["namespace"] = ns
    body["metadata"]["name"] = UID
    body["metadata"]["resourceVersion"] = existing["metadata"]["resourceVersion"]
    for k in ("generation", "creationTimestamp", "uid", "managedFields"):
        body["metadata"].pop(k, None)
    body.pop("status", None)
    ann = body["metadata"].setdefault("annotations", {})
    ann["grafana.app/folder"] = existing.get("metadata", {}).get("annotations", {}).get(
        "grafana.app/folder", "network-lab"
    )
    status, data = api(
        url, token, "PUT", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}", body
    )
    print(f"PUT marc -> {status} gen={(data or {}).get('metadata', {}).get('generation')}")
    if status not in (200, 201):
        raise SystemExit(data)
    status2, after = api(
        url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}"
    )
    kind = ((after or {}).get("spec") or {}).get("layout", {}).get("kind")
    n_has = sum(
        1
        for v in (after or {}).get("spec", {}).get("variables") or []
        if has_var_name(v).startswith("has_")
    )
    print(f"verify layout={kind} has_*={n_has}")
    if kind != "TabsLayout":
        raise SystemExit(f"layout degraded to {kind}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--write-local", action="store_true")
    args = ap.parse_args()

    env = load_env()
    url = env["GRAFANA_URL"]
    token = env["GRAFANA_TOKEN"]
    ns = f"stacks-{env.get('GC_OTLP_ACCOUNT', '1061129')}"
    status, live = api(
        url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}"
    )
    if status != 200:
        raise SystemExit(f"GET live failed {status}: {live}")
    print(
        f"pulled live gen={live['metadata'].get('generation')} "
        f"layout={live['spec']['layout']['kind']}"
    )

    keep, drop = classify_variables(live)
    print(f"before: has_*={len(keep) + len(drop)} keep={len(keep)} drop={len(drop)}")

    patched = copy.deepcopy(live)
    report = strip_dashboard(patched)
    print(f"after:  has_*={len(report['surviving_has'])}")
    print(f"dropped rows: {len(report['dropped_rows'])}")
    print(f"orphan elements removed: {len(report['orphan_elements'])}")

    out = ROOT / ".dash-payloads" / "mib-coverage" / "rollback-proactive-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")
    print("drop vars:")
    for name, metric in report["drop_vars"]:
        print(f"  {name}  <-  {metric[:80]}")

    if args.write_local:
        path = path_for_uid(UID)
        path.write_text(json.dumps(patched, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {path}")

    if args.push:
        push_marc(patched)
    else:
        print("dry-run only (pass --push to PUT marc)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
