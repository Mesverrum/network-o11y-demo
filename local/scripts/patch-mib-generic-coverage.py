#!/usr/bin/env python3
"""Add rudimentary has_* gates + panels for kentik snmp-profiles _general/*.yml.

Covers every generic MIB profile that exports metrics (skips empty system-mib /
extends-only net-snmp). Writes KtransToGrafana Device Details; --push GETs live
marc first, patches, PUTs back (marcnetterfield1 only).

Usage:
  python3 local/scripts/patch-mib-generic-coverage.py
  python3 local/scripts/patch-mib-generic-coverage.py --push
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
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
OVERVIEW_TAB = 0
HARDWARE_TAB = 2
CONNECTIONS_TAB = 3

# Load shared panel helpers from sibling script
_sib = Path(__file__).with_name("patch-mib-rudimentary-coverage.py")
_spec = importlib.util.spec_from_file_location("mib_rudimentary", _sib)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(_mod)

make_gate = _mod.make_gate
make_table_panel = _mod.make_table_panel
make_stat_panel = _mod.make_stat_panel
conditional_row = _mod.conditional_row
grid_item = _mod.grid_item
upsert_variable = _mod.upsert_variable
max_panel_id = _mod.max_panel_id


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


def sel(metric: str) -> str:
    return f'{metric}{{snmp_group=~"$snmp_group",device_name=~"$instance"}}'


# (gate_name, gate_metric, panel_key, panel_builder_kwargs-ish)
# Each entry: tab_idx, gate, metric, row_title, panel_name, kind(stat|table), title, expr_metric, desc, value_field?, rename?
CoverageSpec = dict[str, Any]


def coverage_specs() -> list[CoverageSpec]:
    """One rudimentary panel per _general table/scalar family."""
    return [
        # --- IF-MIB already has Interfaces panels; gate uses tag if_OperStatus ---
        # --- BGP4-MIB (standard; separate from Nokia has_bgp) ---
        {
            "tab": CONNECTIONS_TAB,
            "gate": "has_bgp4",
            "metric": "kentik_snmp_bgpPeerState",
            "row": "BGP4 Peers (RFC 4273)",
            "panel": "panel-bgp4-peers",
            "kind": "table",
            "title": "BGP4 Peer State",
            "value_field": "bgpPeerState",
            "rename": {"bgpPeerState": "State"},
            "desc": "BGP4-MIB bgpPeerTable (generic). Separate from Nokia TIMETRA BGP.",
        },
        # --- ENTITY-SENSOR-MIB (entPhy* / sensor_value tag) ---
        {
            "tab": HARDWARE_TAB,
            "gate": "has_entity_phy",
            "metric": "kentik_snmp_sensor_value",
            "row": "ENTITY-SENSOR (entPhy)",
            "panel": "panel-entity-phy",
            "kind": "table",
            "title": "Physical Sensors (ENTITY-SENSOR-MIB)",
            "value_field": "sensor_value",
            "rename": {"sensor_value": "Value"},
            "desc": "Generic ENTITY-SENSOR-MIB entPhySensorValue (tag sensor_value).",
        },
        # --- HOST-RESOURCES-MIB ---
        {
            "tab": OVERVIEW_TAB,
            "gate": "has_hr_system",
            "metric": "kentik_snmp_hrSystemProcesses",
            "row": "Host Resources (system)",
            "panel": "panel-hr-system",
            "kind": "stat",
            "title": "HR System Processes",
            "desc": "HOST-RESOURCES-MIB hrSystemProcesses (rudimentary).",
        },
        {
            "tab": OVERVIEW_TAB,
            "gate": "has_hr_storage",
            "metric": "kentik_snmp_hrStorageUsed",
            "row": "Host Resources (storage)",
            "panel": "panel-hr-storage",
            "kind": "table",
            "title": "HR Storage Used",
            "value_field": "hrStorageUsed",
            "rename": {"hrStorageUsed": "Used"},
            "desc": "HOST-RESOURCES-MIB hrStorageTable (rudimentary).",
        },
        {
            "tab": OVERVIEW_TAB,
            "gate": "has_hr_processor",
            "metric": "kentik_snmp_hrProcessorLoad",
            "row": "Host Resources (processor)",
            "panel": "panel-hr-processor",
            "kind": "table",
            "title": "HR Processor Load",
            "value_field": "hrProcessorLoad",
            "rename": {"hrProcessorLoad": "Load %"},
            "desc": "HOST-RESOURCES-MIB hrProcessorTable (rudimentary).",
        },
        # --- IP-MIB ---
        {
            "tab": OVERVIEW_TAB,
            "gate": "has_ip_system_stats",
            "metric": "kentik_snmp_ipSystemStatsHCInReceives",
            "row": "IP System Stats",
            "panel": "panel-ip-system",
            "kind": "stat",
            "title": "IP System In Receives (HC)",
            "desc": "IP-MIB ipSystemStatsTable (rudimentary).",
        },
        {
            "tab": OVERVIEW_TAB,
            "gate": "has_ip_if_stats",
            "metric": "kentik_snmp_ipIfStatsHCInOctets",
            "row": "IP Interface Stats",
            "panel": "panel-ip-if",
            "kind": "table",
            "title": "IP If Stats In Octets (HC)",
            "value_field": "ipIfStatsHCInOctets",
            "rename": {"ipIfStatsHCInOctets": "In Octets"},
            "desc": "IP-MIB ipIfStatsTable (rudimentary).",
        },
        # --- LLDP-MIB ---
        {
            "tab": CONNECTIONS_TAB,
            "gate": "has_lldp",
            "metric": "kentik_snmp_lldpRemSysName",
            "row": "LLDP Remotes",
            "panel": "panel-lldp-rem",
            "kind": "table",
            "title": "LLDP Remote Systems",
            "value_field": "lldpRemSysName",
            "rename": {"lldpRemSysName": "Remote SysName"},
            "desc": "LLDP-MIB lldpRemTable (rudimentary).",
        },
        # --- OSPF-MIB ospfIfTable (nbrs already has_ospf) ---
        {
            "tab": CONNECTIONS_TAB,
            "gate": "has_ospf_if",
            "metric": "kentik_snmp_ospfIfState",
            "row": "OSPF Interfaces",
            "panel": "panel-ospf-if",
            "kind": "table",
            "title": "OSPF Interface State",
            "value_field": "ospfIfState",
            "rename": {"ospfIfState": "State"},
            "desc": "OSPF-MIB ospfIfTable (rudimentary; neighbors use has_ospf).",
        },
        # --- TCP-MIB ---
        {
            "tab": OVERVIEW_TAB,
            "gate": "has_tcp",
            "metric": "kentik_snmp_tcpCurrEstab",
            "row": "TCP (MIB-II)",
            "panel": "panel-tcp-estab",
            "kind": "stat",
            "title": "TCP Current Established",
            "desc": "TCP-MIB tcpCurrEstab (rudimentary).",
        },
        # --- UDP-MIB ---
        {
            "tab": OVERVIEW_TAB,
            "gate": "has_udp",
            "metric": "kentik_snmp_udpHCInDatagrams",
            "row": "UDP (MIB-II)",
            "panel": "panel-udp-in",
            "kind": "stat",
            "title": "UDP In Datagrams (HC)",
            "desc": "UDP-MIB udpHCInDatagrams (rudimentary).",
        },
        # --- UCD-SNMP-MIB disks / diskio / swap / cpu detail ---
        {
            "tab": HARDWARE_TAB,
            "gate": "has_ucd_disk",
            "metric": "kentik_snmp_dskPercent",
            "row": "UCD Disk %",
            "panel": "panel-ucd-disk",
            "kind": "table",
            "title": "UCD Disk Percent Used",
            "value_field": "dskPercent",
            "rename": {"dskPercent": "% Used"},
            "desc": "UCD-SNMP-MIB dskTable (rudimentary).",
        },
        {
            "tab": HARDWARE_TAB,
            "gate": "has_ucd_diskio",
            "metric": "kentik_snmp_diskIOReads",
            "row": "UCD Disk I/O",
            "panel": "panel-ucd-diskio",
            "kind": "table",
            "title": "UCD Disk I/O Reads",
            "value_field": "diskIOReads",
            "rename": {"diskIOReads": "Reads"},
            "desc": "UCD-DISKIO-MIB diskIOTable (rudimentary).",
        },
        {
            "tab": OVERVIEW_TAB,
            "gate": "has_ucd_swap",
            "metric": "kentik_snmp_memAvailSwap",
            "row": "UCD Swap",
            "panel": "panel-ucd-swap",
            "kind": "stat",
            "title": "UCD Available Swap",
            "desc": "UCD-SNMP-MIB memAvailSwap (rudimentary).",
        },
        {
            "tab": OVERVIEW_TAB,
            "gate": "has_ucd_mem_detail",
            "metric": "kentik_snmp_memCached",
            "row": "UCD Memory Detail",
            "panel": "panel-ucd-mem-detail",
            "kind": "stat",
            "title": "UCD memCached",
            "desc": "UCD-SNMP-MIB memCached / buffer / shared (rudimentary).",
        },
        {
            "tab": OVERVIEW_TAB,
            "gate": "has_ucd_cpu_detail",
            "metric": "kentik_snmp_ssCpuIdle",
            "row": "UCD CPU Detail",
            "panel": "panel-ucd-cpu",
            "kind": "stat",
            "title": "UCD ssCpuIdle",
            "desc": "UCD-SNMP-MIB ssCpu* scalars (rudimentary; load avg uses has_cpu).",
        },
        # --- UPS-MIB ---
        {
            "tab": HARDWARE_TAB,
            "gate": "has_ups",
            "metric": "kentik_snmp_upsBatteryStatus",
            "row": "UPS Battery",
            "panel": "panel-ups-battery",
            "kind": "stat",
            "title": "UPS Battery Status",
            "desc": "UPS-MIB upsBatteryStatus (rudimentary).",
        },
        {
            "tab": HARDWARE_TAB,
            "gate": "has_ups_output",
            "metric": "kentik_snmp_upsOutputPercentLoad",
            "row": "UPS Output",
            "panel": "panel-ups-output",
            "kind": "table",
            "title": "UPS Output % Load",
            "value_field": "upsOutputPercentLoad",
            "rename": {"upsOutputPercentLoad": "% Load"},
            "desc": "UPS-MIB upsOutputTable (rudimentary).",
        },
        {
            "tab": HARDWARE_TAB,
            "gate": "has_ups_input",
            "metric": "kentik_snmp_upsInputVoltage",
            "row": "UPS Input",
            "panel": "panel-ups-input",
            "kind": "table",
            "title": "UPS Input Voltage",
            "value_field": "upsInputVoltage",
            "rename": {"upsInputVoltage": "Voltage"},
            "desc": "UPS-MIB upsInputTable (rudimentary).",
        },
        {
            "tab": HARDWARE_TAB,
            "gate": "has_ups_bypass",
            "metric": "kentik_snmp_upsBypassVoltage",
            "row": "UPS Bypass",
            "panel": "panel-ups-bypass",
            "kind": "table",
            "title": "UPS Bypass Voltage",
            "value_field": "upsBypassVoltage",
            "rename": {"upsBypassVoltage": "Voltage"},
            "desc": "UPS-MIB upsBypassTable (rudimentary).",
        },
        {
            "tab": HARDWARE_TAB,
            "gate": "has_ups_alarms",
            "metric": "kentik_snmp_upsAlarmTime",
            "row": "UPS Alarms",
            "panel": "panel-ups-alarms",
            "kind": "table",
            "title": "UPS Alarm Time",
            "value_field": "upsAlarmTime",
            "rename": {"upsAlarmTime": "Alarm Time"},
            "desc": "UPS-MIB upsAlarmTable (rudimentary).",
        },
    ]


def upsert_row(rows: list[dict], title: str, gate: str, items: list[dict]) -> None:
    for i, r in enumerate(rows):
        if (r.get("spec") or {}).get("title") == title:
            rows[i] = conditional_row(title, gate, items)
            print(f"replaced row {title}")
            return
    rows.append(conditional_row(title, gate, items))
    print(f"added row {title}")


def patch(dash: dict) -> dict:
    dash = copy.deepcopy(dash)
    elements = dash["spec"]["elements"]
    variables = dash["spec"]["variables"]
    specs = coverage_specs()

    # Ensure IF-MIB gate metric stays on tag export (if_OperStatus)
    upsert_variable(variables, make_gate("has_interfaces", "kentik_snmp_if_OperStatus"))
    print("gate has_interfaces -> kentik_snmp_if_OperStatus")

    next_id = max_panel_id(elements) + 1
    for spec in specs:
        upsert_variable(variables, make_gate(spec["gate"], spec["metric"]))
        print(f"gate {spec['gate']} -> {spec['metric']}")

        expr = sel(spec["metric"])
        if spec["kind"] == "stat":
            panel = make_stat_panel(next_id, spec["title"], expr, spec["desc"])
        else:
            panel = make_table_panel(
                next_id,
                spec["title"],
                expr,
                spec["desc"],
                spec["value_field"],
                spec.get("rename"),
            )
        elements[spec["panel"]] = panel
        print(f"panel {spec['panel']} id={next_id}")
        next_id += 1

        tab = dash["spec"]["layout"]["spec"]["tabs"][spec["tab"]]
        rows = tab["spec"]["layout"]["spec"]["rows"]
        h = 5 if spec["kind"] == "stat" else 8
        w = 8 if spec["kind"] == "stat" else 24
        upsert_row(rows, spec["row"], spec["gate"], [grid_item(spec["panel"], 0, 0, w, h)])

    return dash


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
    layout = (body.get("spec") or {}).get("layout", {}).get("kind")
    status, data = api(
        url, token, "PUT", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}", body
    )
    print(
        f"PUT marc -> {status} gen={(data or {}).get('metadata', {}).get('generation')} layout={layout}"
    )
    if status not in (200, 201):
        raise SystemExit(data)
    # verify layout
    status2, after = api(
        url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}"
    )
    kind = ((after or {}).get("spec") or {}).get("layout", {}).get("kind")
    print(f"verify layout.kind={kind}")
    if kind != "TabsLayout":
        raise SystemExit(f"layout degraded to {kind}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--push", action="store_true", help="GET live marc → patch → PUT (marc only)")
    parser.add_argument(
        "--from-live",
        action="store_true",
        help="Start from live marc GET instead of KtransToGrafana file",
    )
    args = parser.parse_args()

    path = path_for_uid(UID)
    if args.push or args.from_live:
        env = load_env()
        url = env["GRAFANA_URL"]
        token = env["GRAFANA_TOKEN"]
        ns = f"stacks-{env.get('GC_OTLP_ACCOUNT', '1061129')}"
        status, live = api(
            url, token, "GET", f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{UID}"
        )
        if status != 200:
            raise SystemExit(f"GET live failed {status}")
        print(f"pulled live gen={live['metadata'].get('generation')}")
        base = live
    else:
        base = json.loads(path.read_text(encoding="utf-8"))

    patched = patch(base)
    path.write_text(json.dumps(patched, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")

    if args.push:
        push_marc(patched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
