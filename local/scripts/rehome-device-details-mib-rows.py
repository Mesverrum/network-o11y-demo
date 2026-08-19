#!/usr/bin/env python3
"""Re-home MIB coverage rows on Device Details tabs (v2 TabsLayout-safe).

Pulls live marc dashboard, moves rows by has_* gate between tabs, writes
KtransToGrafana JSON, optionally PUTs back.

Usage:
  python3 local/scripts/rehome-device-details-mib-rows.py --dry-run
  python3 local/scripts/rehome-device-details-mib-rows.py --push
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

OVERVIEW = 0
INTERFACES = 1
HARDWARE = 2
CONNECTIONS = 3
FLOW = 4
EVENTS = 5
TELEMETRY = 6

# gate -> destination tab index (from placement review; alarms -> Events)
MOVES: dict[str, int] = {
    # Overview -> Connections
    "has_checkpoint_fw": CONNECTIONS,
    "has_f5_ltm": CONNECTIONS,
    "has_juniper_ive": CONNECTIONS,
    "has_fortinet_fortiap": CONNECTIONS,
    # Cisco CCM / content-engine expose alarm severity/counts → Events
    "has_cisco_ccm": EVENTS,
    "has_cisco_content_engine": EVENTS,
    "has_cccapimtable": CONNECTIONS,
    "has_cccaroutertable": CONNECTIONS,
    "has_cisco_cvp": CONNECTIONS,
    "has_cisco_voice_dial": CONNECTIONS,
    "has_cmqvoipcallactivetable": CONNECTIONS,
    "has_cisco_wan_optimization": CONNECTIONS,
    "has_cwceltecurrrsrq": CONNECTIONS,
    "has_wipipe": CONNECTIONS,
    "has_sonicwall_sma_appliance_security_history": CONNECTIONS,
    "has_servicetable": CONNECTIONS,
    # Overview -> Hardware
    "has_cpqrackcommonenclosurefusetable": HARDWARE,
    "has_cpqrackcommonenclosuremanagertable": HARDWARE,
    "has_cucsequipmenthealthledtable": HARDWARE,
    "has_cachedevicetable": HARDWARE,
    "has_processordevicetable": HARDWARE,
    "has_networkdevicetable": HARDWARE,
    "has_vmware_resources": HARDWARE,
    "has_synology_spaceio": HARDWARE,
    # Overview -> Interfaces
    "has_config_mib": INTERFACES,
    "has_cumulus_counters": INTERFACES,
    "has_cumulus_resource": INTERFACES,
    "has_syn100ghpenlpserverportstatstable": INTERFACES,
    "has_syn100ghpenlpserverporttable": INTERFACES,
    "has_zscaler_osnic": INTERFACES,
    "has_zscaler_zscalernic": INTERFACES,
    # Overview -> Events (alarms / error history)
    "has_elemental": EVENTS,
    "has_brother": EVENTS,
    "has_zebra": EVENTS,
    "has_juniper_alarm": EVENTS,
    # Hardware -> Connections
    "has_cisco_wlc_ap": CONNECTIONS,
    "has_f5_system": CONNECTIONS,
    "has_jnx_vc": CONNECTIONS,
    "has_cvschassistable": CONNECTIONS,
    # Hardware -> Interfaces
    "has_sonicwall_sma_appliance_system_health": INTERFACES,
    # Connections -> Overview
    "has_ironport_mail": OVERVIEW,
    "has_exagrid": OVERVIEW,
    # Connections -> Hardware
    "has_cfwhardwarestatustable": HARDWARE,
    # Connections -> Interfaces
    "has_arista_queue": INTERFACES,
    "has_jnx_cos": INTERFACES,
    "has_jnx_dcu": INTERFACES,
    "has_jnxscustatstable": INTERFACES,
    # Connections -> Events (alarms)
    "has_silverpeak": EVENTS,
    # Pass-2 leftovers still on Overview after first rehome
    "has_cisco_rf": CONNECTIONS,  # HA / redundancy framework
    "has_palo_lc": CONNECTIONS,
    "has_wlsx_systemext": INTERFACES,  # packet loss %
    "has_data_domain": HARDWARE,  # filesystem status
    "has_clmgmtlicenseinfotable": TELEMETRY,  # license inventory
    # Pass-3: Overview declutter
    "has_exagrid": HARDWARE,
    "has_tcp": CONNECTIONS,
    "has_udp": CONNECTIONS,
}

TAB_NAMES = {
    OVERVIEW: "Overview",
    INTERFACES: "Interfaces",
    HARDWARE: "Hardware Sensors",
    CONNECTIONS: "Connections",
    FLOW: "Network Flow",
    EVENTS: "Events",
    TELEMETRY: "Telemetry",
}


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


def row_gate(row: dict) -> str | None:
    """Extract has_* gate from conditionalRendering on a RowsLayout row."""
    cr = row.get("spec", {}).get("conditionalRendering") or row.get("conditionalRendering")
    if not cr:
        return None
    # Walk for variable name
    stack = [cr]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            if cur.get("variable") and str(cur["variable"]).startswith("has_"):
                return str(cur["variable"])
            if cur.get("name") and str(cur["name"]).startswith("has_"):
                return str(cur["name"])
            stack.extend(cur.values())
        elif isinstance(cur, list):
            stack.extend(cur)
    return None


def row_title(row: dict) -> str:
    return str((row.get("spec") or {}).get("title") or "")


def find_and_remove(tabs: list[dict], gate: str) -> tuple[int, dict] | None:
    for ti, tab in enumerate(tabs):
        rows = tab["spec"]["layout"]["spec"]["rows"]
        for ri, row in enumerate(rows):
            if row_gate(row) == gate:
                return ti, rows.pop(ri)
    return None


def rehome(dash: dict) -> list[dict[str, Any]]:
    tabs = dash["spec"]["layout"]["spec"]["tabs"]
    report: list[dict[str, Any]] = []
    for gate, dest in MOVES.items():
        found = find_and_remove(tabs, gate)
        if not found:
            report.append({"gate": gate, "status": "missing", "dest": TAB_NAMES[dest]})
            continue
        src_idx, row = found
        if src_idx == dest:
            # put back
            tabs[src_idx]["spec"]["layout"]["spec"]["rows"].append(row)
            report.append(
                {
                    "gate": gate,
                    "status": "already",
                    "title": row_title(row),
                    "tab": TAB_NAMES[dest],
                }
            )
            continue
        tabs[dest]["spec"]["layout"]["spec"]["rows"].append(row)
        report.append(
            {
                "gate": gate,
                "status": "moved",
                "title": row_title(row),
                "from": TAB_NAMES[src_idx],
                "to": TAB_NAMES[dest],
            }
        )
    return report


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
    print(f"verify layout={kind}")
    if kind != "TabsLayout":
        raise SystemExit(f"layout degraded to {kind}")
    # spot-check a few gates landed on expected tabs
    tabs = after["spec"]["layout"]["spec"]["tabs"]
    checks = [
        ("has_silverpeak", EVENTS),
        ("has_juniper_alarm", EVENTS),
        ("has_cisco_ccm", EVENTS),
        ("has_cisco_content_engine", EVENTS),
        ("has_f5_ltm", CONNECTIONS),
        ("has_cisco_rf", CONNECTIONS),
        ("has_palo_lc", CONNECTIONS),
        ("has_arista_queue", INTERFACES),
        ("has_wlsx_systemext", INTERFACES),
        ("has_cfwhardwarestatustable", HARDWARE),
        ("has_data_domain", HARDWARE),
        ("has_ironport_mail", OVERVIEW),
        ("has_clmgmtlicenseinfotable", TELEMETRY),
    ]
    by_gate: dict[str, int] = {}
    for ti, tab in enumerate(tabs):
        for row in tab["spec"]["layout"]["spec"]["rows"]:
            g = row_gate(row)
            if g:
                by_gate[g] = ti
    for gate, expect in checks:
        got = by_gate.get(gate)
        ok = "OK" if got == expect else "FAIL"
        print(f"  check {gate}: tab={TAB_NAMES.get(got, got)} expect={TAB_NAMES[expect]} [{ok}]")
        if got != expect:
            raise SystemExit(f"placement check failed for {gate}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
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
    print(f"pulled live gen={live['metadata'].get('generation')} layout={live['spec']['layout']['kind']}")

    patched = copy.deepcopy(live)
    report = rehome(patched)
    moved = [r for r in report if r["status"] == "moved"]
    missing = [r for r in report if r["status"] == "missing"]
    already = [r for r in report if r["status"] == "already"]
    print(f"moved={len(moved)} already={len(already)} missing={len(missing)}")
    for r in moved:
        print(f"  {r['gate']}: {r['from']} -> {r['to']}  ({r['title']})")
    for r in missing:
        print(f"  MISSING {r['gate']} (wanted {r['dest']})")

    out = ROOT / ".dash-payloads" / "mib-coverage" / "rehome-report.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")

    if args.dry_run:
        print("dry-run: not writing upstream / not pushing")
        return 0

    path = path_for_uid(UID)
    # Strip API metadata noise for local file (keep spec + variables)
    path.write_text(json.dumps(patched, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path}")

    if args.push:
        push_marc(patched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
