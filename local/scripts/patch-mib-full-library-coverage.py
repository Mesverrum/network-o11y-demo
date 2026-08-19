#!/usr/bin/env python3
"""Rudimentary Device Details coverage for remaining full snmp-profiles library.

One has_* + panel per uncovered MIB (siblings soft-covered by inventory).
Skips SNMPv2 identity scalars. Marc-only with --push.

Usage:
  python3 local/scripts/patch-mib-full-library-coverage.py
  python3 local/scripts/patch-mib-full-library-coverage.py --push
"""
from __future__ import annotations

import argparse
import copy
import importlib.util
import json
import re
import ssl
import sys
import urllib.error
import urllib.request
from collections import defaultdict
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
sys.path.insert(0, str(ROOT / "scripts"))
from ktranslate_upstream import load_local_env, path_for_uid  # noqa: E402

UID = "ktranslate-device-details"
OVERVIEW_TAB = 0
HARDWARE_TAB = 2
CONNECTIONS_TAB = 3

SKIP_MIBS = {"SNMPv2-MIB", "SNMPv2-SMI", "SNMPv2-TC"}

# Curated stable gate names for remaining backlog MIBs
CURATED: dict[str, str] = {
    "CUMULUS-RESOURCE-QUERY-MIB": "has_cumulus_resource",
    "CUMULUS-COUNTERS-MIB": "has_cumulus_counters",
    "BARRACUDA-SPAM-MIB": "has_barracuda_spam",
    "G700-MG-MIB": "has_avaya_g700",
    "EXAGRID-MIB": "has_exagrid",
    "HUAWEI-STACK-MIB": "has_huawei_stack",
    "HUAWEI-DNS-MIB": "has_huawei_dns",
    "HUAWEI-NAT-EXT-MIB": "has_huawei_nat",
    "IB-DNSONE-MIB": "has_infoblox_dns",
    "IB-DHCPONE-MIB": "has_infoblox_dhcp",
    "SILVERPEAK-MGMT-MIB": "has_silverpeak",
    "DigiPower-PDU-MIB": "has_digipower_pdu",
    "PRINTER-MIB": "has_printer",
    "HAWK-I2-MIB": "has_hawki2",
    "BCN-DHCPV4-MIB": "has_bcn_dhcp",
    "BROTHER-MIB": "has_brother",
    "FIBRE-CHANNEL-FE-MIB": "has_fc_fe",
    "PEPLINK-BALANCE-MIB": "has_peplink",
    "UBNT-UniFi-MIB": "has_unifi",
    "AVAYA-RTP-MIB": "has_avaya_rtp",
    "BROCADE-SYSTEM-MIB": "has_brocade",
    "CONFIG-MIB": "has_config_mib",
    "ELEMENTAL-LIVE-MIB": "has_elemental",
    "LIEBERT-GP-FLEXIBLE-MIB": "has_liebert",
    "NETOPTICS-XFAM-HA-MIB": "has_netoptics_ha",
    "PAN-LC-MIB": "has_palo_lc",
    "ROOMALERT3E-MIB": "has_roomalert",
    "SENSORGATEWAY-MIB": "has_sensorgateway",
    "SYNOLOGY-RAID-MIB": "has_synology_raid",
    "SYNOLOGY-SPACEIO-MIB": "has_synology_spaceio",
    "SYNOLOGY-STORAGEIO-MIB": "has_synology_storageio",
    "TERRAGRAPH-RADIO-MIB": "has_terragraph",
    "VELOCLOUD-EDGE-MIB": "has_velocloud",
    "VMWARE-ENV-MIB": "has_vmware_env",
    "VMWARE-RESOURCES-MIB": "has_vmware_resources",
    "WIPIPE-MIB": "has_wipipe",
    "ZEBRA-MIB": "has_zebra",
    "ZSCALER-OSNIC-MIB": "has_zscaler_osnic",
    "ZSCALER-PROCESSWATCHDOG-MIB": "has_zscaler_watchdog",
}

_sib = Path(__file__).with_name("patch-mib-rudimentary-coverage.py")
_spec = importlib.util.spec_from_file_location("mib_rudimentary", _sib)
_mod = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
sys.modules["mib_rudimentary"] = _mod
_spec.loader.exec_module(_mod)

make_gate = _mod.make_gate
make_table_panel = _mod.make_table_panel
make_stat_panel = _mod.make_stat_panel
conditional_row = _mod.conditional_row
grid_item = _mod.grid_item
upsert_variable = _mod.upsert_variable
max_panel_id = _mod.max_panel_id

_ispec = importlib.util.spec_from_file_location(
    "mib_coverage_inventory", ROOT / "scripts" / "mib-coverage-inventory.py"
)
_inv = importlib.util.module_from_spec(_ispec)
assert _ispec and _ispec.loader
sys.modules["mib_coverage_inventory"] = _inv
_ispec.loader.exec_module(_inv)


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


def slug(s: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    base = re.sub(r"_+", "_", base)[:36].strip("_")
    return f"has_{base}"


def pick_tab(mib: str, table: str, metric: str) -> int:
    blob = f"{mib} {table} {metric}".lower()
    if re.search(
        r"ups|pdu|power|fan|temp|sensor|env|battery|raid|storage|disk|room|liebert|"
        r"printer|hardware|vmware.?env",
        blob,
    ):
        return HARDWARE_TAB
    if re.search(
        r"dns|dhcp|wifi|radio|unifi|wlan|wan|nat|stack|fc|fibre|ha|alarm|link|"
        r"peer|tunnel|rtp|spam|mail",
        blob,
    ):
        return CONNECTIONS_TAB
    return OVERVIEW_TAB


def existing_gate_names(dash: dict) -> set[str]:
    return {
        (v.get("spec") or {}).get("name") or ""
        for v in dash.get("spec", {}).get("variables") or []
        if str((v.get("spec") or {}).get("name") or "").startswith("has_")
    }


def build_backlog(dash: dict) -> list[dict[str, Any]]:
    base = REPO.parent / "snmp-profiles" / "profiles" / "kentik_snmp"
    files = [
        p
        for p in sorted(base.rglob("*.yml")) + sorted(base.rglob("*.yaml"))
        if not p.name.startswith("traps") and p.name != "_template.yml"
    ]
    # skip underscore-only dirs except we want device profiles; _general already covered
    search = [base]
    all_metrics = []
    for path in files:
        if path.parent.name.startswith("_") and path.parent.name != "_general":
            continue
        all_metrics.extend(
            _inv.parse_profile_file(path, search, seen_extends=set(), expand_extends=False)
        )
    gates = _inv.extract_gates_from_dashboard(dash)
    panels = _inv.extract_panel_metrics(dash)
    groups: dict[tuple, list] = defaultdict(list)
    for m in all_metrics:
        groups[(m.profile, m.mib, m.kind, m.table_or_scalar)].append(m)
    rows = [
        _inv.classify(k, mets, gates, panels, set())
        for k, mets in sorted(groups.items())
    ]
    rows = _inv.apply_mib_soft_coverage(rows, gates, panels)
    backlog = [r for r in rows if r.status != "covered"]
    by_mib: dict[str, list] = defaultdict(list)
    for r in backlog:
        if r.mib in SKIP_MIBS:
            continue
        by_mib[r.mib].append(r)
    reps: list[dict[str, Any]] = []
    pref = re.compile(
        r"(?i)status|state|health|alarm|error|util|load|cpu|memory|temp|oper|conn|severity"
    )
    for mib, items in sorted(by_mib.items()):
        ranked = sorted(
            items,
            key=lambda r: (
                0 if pref.search(" ".join(r.prom_names[:1] + [r.table_or_scalar])) else 1,
                0 if r.kind == "table" else 1,
                r.table_or_scalar,
            ),
        )
        r = ranked[0]
        prom = r.prom_names[0] if r.prom_names else ""
        if not prom:
            continue
        reps.append(
            {
                "mib": mib,
                "kind": r.kind,
                "table": r.table_or_scalar,
                "prom": prom,
                "n_groups": len(items),
            }
        )
    return reps


def upsert_row(rows: list[dict], title: str, gate: str, items: list[dict]) -> None:
    for i, r in enumerate(rows):
        if (r.get("spec") or {}).get("title") == title:
            rows[i] = conditional_row(title, gate, items)
            print(f"replaced row {title}")
            return
    rows.append(conditional_row(title, gate, items))
    print(f"added row {title}")


def patch(dash: dict) -> tuple[dict, list[dict]]:
    dash = copy.deepcopy(dash)
    elements = dash["spec"]["elements"]
    variables = dash["spec"]["variables"]
    existing = existing_gate_names(dash)
    backlog = build_backlog(dash)
    print(f"uncovered MIBs to gate: {len(backlog)}")

    specs: list[dict] = []
    next_id = max_panel_id(elements) + 1
    for u in backlog:
        gate = CURATED.get(u["mib"]) or slug(u["mib"].replace("-MIB", "").replace("_MIB", ""))
        if gate in existing:
            print(f"skip existing {gate} ({u['mib']})")
            continue
        existing.add(gate)
        value_field = u["prom"].replace("kentik_snmp_", "", 1)
        kind = "table" if u["kind"] == "table" else "stat"
        short = u["table"] if len(u["table"]) < 48 else u["table"][:45] + "…"
        tab = pick_tab(u["mib"], u["table"], u["prom"])
        panel_key = f"panel-{gate}"
        row_title = f"{u['mib']}: {short}"
        desc = f"{u['mib']} ({u['n_groups']} groups; rudimentary full-library coverage)."

        upsert_variable(variables, make_gate(gate, u["prom"]))
        print(f"gate {gate} -> {u['prom']}  [{u['mib']} n={u['n_groups']}]")

        prom = u["prom"]
        if "-" in prom:
            expr = (
                f'{{__name__="{prom}",snmp_group=~"$snmp_group",device_name=~"$instance"}}'
            )
        else:
            expr = f'{prom}{{snmp_group=~"$snmp_group",device_name=~"$instance"}}'
        if kind == "stat":
            panel = make_stat_panel(next_id, short, expr, desc)
        else:
            panel = make_table_panel(
                next_id, short, expr, desc, value_field, {value_field: "Value"}
            )
        # reuse id if panel exists
        if panel_key in elements and isinstance((elements[panel_key].get("spec") or {}).get("id"), int):
            panel["spec"]["id"] = elements[panel_key]["spec"]["id"]
        else:
            next_id += 1
        elements[panel_key] = panel

        rows = dash["spec"]["layout"]["spec"]["tabs"][tab]["spec"]["layout"]["spec"]["rows"]
        h = 5 if kind == "stat" else 8
        w = 8 if kind == "stat" else 24
        upsert_row(rows, row_title, gate, [grid_item(panel_key, 0, 0, w, h)])
        specs.append({"gate": gate, "metric": u["prom"], "mib": u["mib"]})

    return dash, specs


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
        if str((v.get("spec") or {}).get("name") or "").startswith("has_")
    )
    print(f"verify layout={kind} has_*={n_has}")
    if kind != "TabsLayout":
        raise SystemExit(f"layout degraded to {kind}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--push", action="store_true")
    ap.add_argument("--from-live", action="store_true")
    args = ap.parse_args()

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

    patched, specs = patch(base)
    path.write_text(json.dumps(patched, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {path} (+{len(specs)} gates)")

    out = ROOT / ".dash-payloads" / "mib-coverage" / "full-library-gates.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(specs, indent=2) + "\n", encoding="utf-8")
    print(f"wrote {out}")

    # Merge curated names into inventory overrides file snippet for soft-match
    # (MIB_GATE_OVERRIDES is in inventory module — patch file below separately)

    if args.push:
        push_marc(patched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
