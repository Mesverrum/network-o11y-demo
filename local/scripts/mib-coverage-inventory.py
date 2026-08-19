#!/usr/bin/env python3
"""Inventory SNMP profile tables/scalars vs Device Details has_* coverage.

Parses ktranslate snmp-profiles (lab + optional upstream tree), extracts has_*
gate metrics from KtransToGrafana Device Details (or a live Grafana pull),
optionally queries Prometheus for live kentik_snmp_* series, and writes a
coverage matrix (markdown + JSON).

Usage:
  python3 local/scripts/mib-coverage-inventory.py
  python3 local/scripts/mib-coverage-inventory.py --profiles-root ../snmp-profiles/profiles/kentik_snmp
  python3 local/scripts/mib-coverage-inventory.py --live-prom
  python3 local/scripts/mib-coverage-inventory.py --from-grafana   # pull Device Details from GRAFANA_URL

Outputs:
  local/docs/mib-coverage-matrix.md
  local/.dash-payloads/mib-coverage/matrix.json
"""
from __future__ import annotations

import argparse
import json
import os
import re
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
OUT_MD = ROOT / "docs" / "mib-coverage-matrix.md"
OUT_MD_FULL = ROOT / "docs" / "mib-coverage-matrix-full.md"
OUT_JSON = ROOT / ".dash-payloads" / "mib-coverage" / "matrix.json"
OUT_JSON_FULL = ROOT / ".dash-payloads" / "mib-coverage" / "matrix-full.json"
DEFAULT_LAB_PROFILES = [
    ROOT / "snmp-profiles" / "nokia" / "nokia-srlinux.yml",
    ROOT / "snmp-profiles" / "lenovo" / "lenovo-rackswitch.yml",
]
DEVICE_DETAILS_UID = "ktranslate-device-details"

# Known tag → Prom metric name (ktranslate compound / renamed exports)
TAG_TO_METRIC = {
    "CPU": "kentik_snmp_CPU",
    "MemoryUsed": "kentik_snmp_MemoryUsed",
    "MemoryFree": "kentik_snmp_MemoryFree",
    "MemoryTotal": "kentik_snmp_MemoryTotal",
    "MemoryUtilization": "kentik_snmp_MemoryUtilization",
    "Temperature": "kentik_snmp_Temperature",
    "Uptime": "kentik_snmp_Uptime",
}

# Capability hints: symbol/table name regex → preferred has_* (for suggestions)
CAPABILITY_HINTS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)cpu|multiProc|laLoad|ssCpu"), "has_cpu"),
    (re.compile(r"(?i)memBuffer|memCached|memShared|memMinimumSwap"), "has_ucd_mem_detail"),
    (re.compile(r"(?i)memory|memFree|memUsed|memAvail|memTotal"), "has_memory"),
    (re.compile(r"(?i)^if|ifHC|ifOper|ifAdmin|ifIn|ifOut"), "has_interfaces"),
    (re.compile(r"(?i)entPhySensor|sensor_value"), "has_entity_phy"),
    (re.compile(r"(?i)entSensor"), "has_sensors"),
    (re.compile(r"(?i)bgpPeer"), "has_bgp4"),
    (re.compile(r"(?i)bgp|tBgpPeer|cbgpPeer"), "has_bgp"),
    (re.compile(r"(?i)ospfIf"), "has_ospf_if"),
    (re.compile(r"(?i)ospf"), "has_ospf"),
    (re.compile(r"(?i)lldpRem"), "has_lldp"),
    (re.compile(r"(?i)hrSystem"), "has_hr_system"),
    (re.compile(r"(?i)hrStorage"), "has_hr_storage"),
    (re.compile(r"(?i)hrProcessor"), "has_hr_processor"),
    (re.compile(r"(?i)ipSystemStats"), "has_ip_system_stats"),
    (re.compile(r"(?i)ipIfStats"), "has_ip_if_stats"),
    (re.compile(r"(?i)^tcp|tcpCurr|tcpHC"), "has_tcp"),
    (re.compile(r"(?i)^udp|udpHC"), "has_udp"),
    (re.compile(r"(?i)dskPercent|dskTable|dskUsed"), "has_ucd_disk"),
    (re.compile(r"(?i)diskIO"), "has_ucd_diskio"),
    (re.compile(r"(?i)memAvailSwap|memTotalSwap"), "has_ucd_swap"),
    (re.compile(r"(?i)upsBatteryStatus|upsEstimated|upsSecondsOn"), "has_ups"),
    (re.compile(r"(?i)upsAdvBattery|upsBasicBattery|upsAdvOutput|PowerNet-MIB_UPS"), "has_apc_ups"),
    (re.compile(r"(?i)upsOutput"), "has_ups_output"),
    (re.compile(r"(?i)upsInput"), "has_ups_input"),
    (re.compile(r"(?i)upsBypass"), "has_ups_bypass"),
    (re.compile(r"(?i)upsAlarm"), "has_ups_alarms"),
    (re.compile(r"(?i)fwAccepted|fwDropped|fwRejected|fwNumConn|fwConn"), "has_firewall"),
    (re.compile(r"(?i)cswSwitch|cswStack|CISCO-STACKWISE"), "has_csw"),
    (re.compile(r"(?i)cHsrp|HSRP"), "has_hsrp"),
    (re.compile(r"(?i)rttMon|CISCO-RTTMON"), "has_ipsla"),
    (re.compile(r"(?i)cieIf"), "has_cie_drops"),
    (re.compile(r"(?i)cntpPeers|ntp"), "has_ntp"),
    (re.compile(r"(?i)cefcFanTray"), "has_fru_fantray"),
    (re.compile(r"(?i)cefcModule"), "has_fru_module"),
    (re.compile(r"(?i)cefcTotalDrawn|cefcPower"), "has_fru_power"),
    (re.compile(r"(?i)cefcFanSpeed"), "has_fan_speed"),
    (re.compile(r"(?i)temp_value|ciscoEnvMonTemperature"), "has_temp"),
    (re.compile(r"(?i)voltage_value|ciscoEnvMonVoltage"), "has_cisco_env_voltage"),
    (re.compile(r"(?i)fan_state|power_supply_state"), "has_psu_state"),
    (re.compile(r"(?i)fan"), "has_fan_state"),
    (re.compile(r"(?i)power|psu|PMOutput|PowerSupply"), "has_psu_state"),
    (re.compile(r"(?i)tmnxHw|tmnxPhysChassis"), "has_tmnx_chassis"),
    (re.compile(r"(?i)temp"), "has_temp"),
    (re.compile(r"(?i)disk|hrStorage"), "has_disk"),
    (re.compile(r"(?i)fwNum|firewall|conn"), "has_firewall"),
    (re.compile(r"(?i)ntp|cntp"), "has_ntp"),
]


@dataclass
class ProfileMetric:
    profile: str
    mib: str
    kind: str  # table | scalar
    table_or_scalar: str
    symbol: str
    tag: str | None
    prom_names: list[str]
    source_file: str


@dataclass
class GateInfo:
    name: str
    metric: str


@dataclass
class CoverageRow:
    profile: str
    mib: str
    kind: str
    table_or_scalar: str
    symbols: list[str]
    prom_names: list[str]
    status: str
    matched_gates: list[str] = field(default_factory=list)
    suggested_gate: str = ""
    live: bool = False
    notes: str = ""


def load_env() -> dict[str, str]:
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if not path.is_file():
        return env
    for line in path.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, _, v = s.partition("=")
        env[k.strip()] = v.strip().strip('"').strip("'")
        os.environ.setdefault(k.strip(), env[k.strip()])
    return env


def prom_name_for_symbol(symbol: str, tag: str | None) -> list[str]:
    names: list[str] = []
    if tag and tag in TAG_TO_METRIC:
        names.append(TAG_TO_METRIC[tag])
    # ktranslate often renames the OTLP metric to the symbol's tag (e.g. if_OperStatus)
    if tag:
        names.append(f"kentik_snmp_{tag}")
    # Always include raw symbol export
    names.append(f"kentik_snmp_{symbol}")
    # Dedupe preserve order
    seen: set[str] = set()
    out: list[str] = []
    for n in names:
        if n not in seen:
            seen.add(n)
            out.append(n)
    return out


def resolve_extends(name: str, search_roots: list[Path]) -> Path | None:
    """Find an extends target (e.g. system-mib.yml) under search roots."""
    candidates = [
        name,
        f"_general/{name}",
        f"general/{name}",
    ]
    for root in search_roots:
        for rel in candidates:
            p = root / rel
            if p.is_file():
                return p
            # basename search
        matches = list(root.rglob(Path(name).name))
        if matches:
            return matches[0]
    return None


def parse_profile_file(
    path: Path,
    search_roots: list[Path],
    seen_extends: set[str] | None = None,
    *,
    expand_extends: bool = True,
) -> list[ProfileMetric]:
    seen_extends = seen_extends or set()
    raw = path.read_text(encoding="utf-8")
    # Strip leading doc comments before ---
    if "\n---" in raw:
        # keep from first document start
        idx = raw.find("\n---")
        raw = raw[idx + 1 :]
    # Upstream profiles occasionally contain literal tabs that break PyYAML.
    raw = raw.replace("\t", " ")
    try:
        data = yaml.safe_load(raw) or {}
    except yaml.YAMLError as e:
        print(f"WARN: skip unparseable profile {path}: {e}", file=sys.stderr)
        return []
    if not isinstance(data, dict):
        return []

    profile_name = path.stem
    rows: list[ProfileMetric] = []

    if expand_extends:
        for ext in data.get("extends") or []:
            key = str(ext)
            if key in seen_extends:
                continue
            seen_extends.add(key)
            ext_path = resolve_extends(key, search_roots + [path.parent])
            if ext_path:
                rows.extend(
                    parse_profile_file(
                        ext_path, search_roots, seen_extends, expand_extends=True
                    )
                )

    try:
        rel = str(path.relative_to(REPO))
    except ValueError:
        rel = str(path)

    for metric in data.get("metrics") or []:
        if not isinstance(metric, dict):
            continue
        mib = str(metric.get("MIB") or metric.get("mib") or "?")
        if "table" in metric and isinstance(metric["table"], dict):
            table = metric["table"]
            tname = str(table.get("name") or "?")
            for sym in metric.get("symbols") or []:
                if not isinstance(sym, dict):
                    continue
                sname = str(sym.get("name") or "?")
                tag = sym.get("tag")
                tag_s = str(tag) if tag else None
                rows.append(
                    ProfileMetric(
                        profile=profile_name,
                        mib=mib,
                        kind="table",
                        table_or_scalar=tname,
                        symbol=sname,
                        tag=tag_s,
                        prom_names=prom_name_for_symbol(sname, tag_s),
                        source_file=rel,
                    )
                )
        elif "symbol" in metric and isinstance(metric["symbol"], dict):
            sym = metric["symbol"]
            sname = str(sym.get("name") or "?")
            tag = sym.get("tag")
            tag_s = str(tag) if tag else None
            rows.append(
                ProfileMetric(
                    profile=profile_name,
                    mib=mib,
                    kind="scalar",
                    table_or_scalar=sname,
                    symbol=sname,
                    tag=tag_s,
                    prom_names=prom_name_for_symbol(sname, tag_s),
                    source_file=rel,
                )
            )
        elif "symbols" in metric and isinstance(metric["symbols"], list):
            # Multi-scalar block (no table) — e.g. HOST-RESOURCES hrSystem*, UPS battery
            group = str(
                metric.get("name")
                or metric.get("group")
                or f"{mib}-scalars"
            )
            for sym in metric["symbols"]:
                if not isinstance(sym, dict):
                    continue
                sname = str(sym.get("name") or "?")
                tag = sym.get("tag")
                tag_s = str(tag) if tag else None
                rows.append(
                    ProfileMetric(
                        profile=profile_name,
                        mib=mib,
                        kind="scalar",
                        table_or_scalar=group,
                        symbol=sname,
                        tag=tag_s,
                        prom_names=prom_name_for_symbol(sname, tag_s),
                        source_file=rel,
                    )
                )
    return rows


def extract_gates_from_dashboard(dash: dict) -> list[GateInfo]:
    gates: list[GateInfo] = []
    variables = (dash.get("spec") or {}).get("variables") or []
    for var in variables:
        spec = var.get("spec") or {}
        name = spec.get("name") or ""
        if not name.startswith("has_"):
            continue
        qspec = ((spec.get("query") or {}).get("spec")) or {}
        metric = (qspec.get("metric") or "").strip()
        gates.append(GateInfo(name=name, metric=metric))
    return gates


def extract_panel_metrics(dash: dict) -> set[str]:
    text = json.dumps(dash)
    return set(re.findall(r"kentik_snmp_[A-Za-z0-9_]+|kentik_ping_[A-Za-z0-9_]+|network_io_by_flow_bytes", text))


def load_dashboard_from_upstream() -> dict:
    sys.path.insert(0, str(ROOT / "scripts"))
    from ktranslate_upstream import path_for_uid  # type: ignore

    path = path_for_uid(DEVICE_DETAILS_UID)
    return json.loads(path.read_text(encoding="utf-8"))


def api_get(base: str, token: str, path: str) -> tuple[int, Any]:
    req = urllib.request.Request(
        base.rstrip("/") + path,
        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
    )
    ctx = ssl.create_default_context()
    try:
        with urllib.request.urlopen(req, context=ctx, timeout=120) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode(errors="replace")
        try:
            return e.code, json.loads(raw)
        except Exception:
            return e.code, {"raw": raw[:2000]}


def load_dashboard_from_grafana(env: dict[str, str]) -> dict:
    url = env.get("GRAFANA_URL") or ""
    token = env.get("GRAFANA_TOKEN") or ""
    account = env.get("GC_OTLP_ACCOUNT") or "1061129"
    ns = f"stacks-{account}"
    if not url or not token:
        raise SystemExit("GRAFANA_URL + GRAFANA_TOKEN required for --from-grafana")
    status, data = api_get(
        url,
        token,
        f"/apis/dashboard.grafana.app/v2/namespaces/{ns}/dashboards/{DEVICE_DETAILS_UID}",
    )
    if status != 200:
        raise SystemExit(f"GET device-details failed: {status} {data}")
    return data


def query_live_metric_names(env: dict[str, str]) -> set[str]:
    url = env.get("GRAFANA_URL") or ""
    token = env.get("GRAFANA_TOKEN") or ""
    if not url or not token:
        print("WARN: no GRAFANA_URL/TOKEN — skip live Prom", file=sys.stderr)
        return set()
    status, dss = api_get(url, token, "/api/datasources")
    if status != 200:
        print(f"WARN: datasources {status}", file=sys.stderr)
        return set()
    prom = next((d for d in dss if d.get("type") == "prometheus" and d.get("isDefault")), None)
    if not prom:
        prom = next((d for d in dss if d.get("type") == "prometheus"), None)
    if not prom:
        return set()
    # series API can be heavy; use label values on __name__ with match
    q = urllib.parse.urlencode(
        {
            "match[]": '{__name__=~"kentik_snmp_.*|kentik_ping_.*"}',
        }
    )
    # Prefer /api/v1/label/__name__/values via proxy
    path = f"/api/datasources/proxy/uid/{prom['uid']}/api/v1/label/__name__/values?{q}"
    status, body = api_get(url, token, path)
    if status != 200:
        # fallback: query count by __name__ (may truncate)
        qq = urllib.parse.urlencode({"query": 'count by (__name__) ({__name__=~"kentik_snmp_.*"})'})
        status, body = api_get(url, token, f"/api/datasources/proxy/uid/{prom['uid']}/api/v1/query?{qq}")
        if status != 200:
            print(f"WARN: prom query failed {status}", file=sys.stderr)
            return set()
        names = set()
        for r in (body.get("data") or {}).get("result") or []:
            n = (r.get("metric") or {}).get("__name__")
            if n:
                names.add(n)
        return names
    data = body.get("data") if isinstance(body, dict) else None
    if isinstance(data, list):
        return {n for n in data if isinstance(n, str) and n.startswith("kentik_")}
    return set()


# Preferred has_* for whole vendor MIBs (shared with patch-mib-vendor-coverage / full-library)
MIB_GATE_OVERRIDES: dict[str, str] = {
    "PowerNet-MIB_UPS": "has_apc_ups",
    "PowerNet-MIB_ATS": "has_apc_ats",
    "PowerNet-MIB_PDU": "has_apc_pdu",
    "NETBOTZV2-MIB": "has_apc_netbotz",
    "CISCO-ENVMON-MIB": "has_cisco_env_voltage",
    "CISCO-CCM-MIB": "has_cisco_ccm",
    "CISCO-REMOTE-ACCESS-MONITOR-MIB": "has_cisco_cras",
    "CISCO-VOICE-DIAL-CONTROL-MIB": "has_cisco_voice_dial",
    "AIRESPACE-WIRELESS-MIB": "has_cisco_wlc_ap",
    "ARISTA-QUEUE-MIB": "has_arista_queue",
    "F5-BIGIP-SYSTEM-MIB": "has_f5_system",
    "F5-BIGIP-LOCAL-MIB": "has_f5_ltm",
    "FORTINET-FORTIGATE-MIB": "has_fortigate",
    "CHECKPOINT-MIB": "has_checkpoint_fw",
    "JUNIPER-IVE-MIB": "has_juniper_ive",
    "JUNIPER-DCU-MIB": "has_jnx_dcu",
    "JUNIPER-VIRTUALCHASSIS-MIB": "has_jnx_vc",
    "JUNIPER-COS-MIB": "has_jnx_cos",
    "IDRAC-MIB": "has_dell_idrac",
    "EATON-EPDU-MIB": "has_eaton_epdu",
    "MERAKI-CLOUD-CONTROLLER-MIB": "has_meraki_cc",
    "ASYNCOS-MAIL-MIB": "has_ironport_mail",
    "ASYNCOSWEBSECURITYAPPLIANCE-MIB": "has_ironport_wsa",
    "CISCO-SLB-EXT-MIB": "has_cisco_slb",
    "CPPM-MIB": "has_aruba_cppm",
    # full-library remainder
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
    "ZSCALER-SWAPINFO-MIB": "has_zscaler_swapinfo",
    "ZSCALER-ZSCALERNIC-MIB": "has_zscaler_zscalernic",
}


def suggest_gate(table_or_scalar: str, symbols: list[str], mib: str = "") -> str:
    if mib and mib in MIB_GATE_OVERRIDES:
        return MIB_GATE_OVERRIDES[mib]
    blob = " ".join([table_or_scalar] + symbols)
    for pat, gate in CAPABILITY_HINTS:
        if pat.search(blob):
            return gate
    slug = re.sub(r"[^a-z0-9]+", "_", table_or_scalar.lower()).strip("_")
    return f"has_{slug[:40]}"


def classify(
    group_key: tuple[str, str, str, str],
    metrics: list[ProfileMetric],
    gates: list[GateInfo],
    panel_metrics: set[str],
    live_names: set[str],
) -> CoverageRow:
    profile, mib, kind, table = group_key
    symbols = [m.symbol for m in metrics]
    prom_names: list[str] = []
    for m in metrics:
        for n in m.prom_names:
            if n not in prom_names:
                prom_names.append(n)

    gate_by_metric = {g.metric: g.name for g in gates if g.metric}
    gate_names = {g.name for g in gates}

    matched: list[str] = []
    for n in prom_names:
        if n in gate_by_metric:
            matched.append(gate_by_metric[n])
    for g in gates:
        if g.metric and g.metric in prom_names and g.name not in matched:
            matched.append(g.name)

    # Memory / interface tag families: any tagged Memory* or if_* matches the capability gate
    family: dict[str, set[str]] = {
        "has_memory": {
            "kentik_snmp_MemoryUsed",
            "kentik_snmp_MemoryFree",
            "kentik_snmp_MemoryTotal",
            "kentik_snmp_MemoryUtilization",
        },
        "has_interfaces": {
            "kentik_snmp_if_OperStatus",
            "kentik_snmp_ifOperStatus",
            "kentik_snmp_if_AdminStatus",
            "kentik_snmp_ifHCInOctets",
            "kentik_snmp_ifHCOutOctets",
        },
        "has_firewall": {
            "kentik_snmp_fwNumConn",
            "kentik_snmp_fwAccepted",
            "kentik_snmp_fwDropped",
            "kentik_snmp_fwRejected",
        },
    }
    gate_names_list = {g.name for g in gates}
    in_panels = False
    for gate_name, fam in family.items():
        if gate_name in gate_names_list and any(n in fam for n in prom_names):
            if gate_name not in matched:
                matched.append(gate_name)
            gmet = next((g.metric for g in gates if g.name == gate_name), "")
            if gmet and gmet in panel_metrics:
                in_panels = True  # capability panel covers the family

    live = any(n in live_names for n in prom_names) if live_names else False
    if not in_panels:
        in_panels = any(n in panel_metrics for n in prom_names)
    suggested = suggest_gate(table, symbols, mib=mib)

    # Prefer matching suggested gate if already present even when metric differs slightly
    soft_gates: list[str] = []
    if suggested in gate_names and suggested not in matched:
        soft_gates.append(suggested)
        # Rudimentary coverage: gate+panel exist for this capability → count as covered
        gmet = next((g.metric for g in gates if g.name == suggested), "")
        if gmet and gmet in panel_metrics:
            matched.append(suggested)
            in_panels = True

    notes = ""
    if matched and in_panels:
        status = "covered"
    elif matched and not in_panels:
        status = "gate_only"
        notes = "has_* exists but no panel expr for these prom names"
    elif in_panels and not matched:
        status = "live_ungated"
        notes = "panels reference metrics but no matching has_* gate metric"
        if soft_gates:
            notes += f"; capability hint {soft_gates}"
    elif live and not matched:
        status = "live_ungated"
    else:
        status = "profile_only"
        if soft_gates:
            notes = f"capability hint only: {soft_gates}"

    return CoverageRow(
        profile=profile,
        mib=mib,
        kind=kind,
        table_or_scalar=table,
        symbols=symbols,
        prom_names=prom_names,
        status=status,
        matched_gates=matched + [f"{g} (capability-hint)" for g in soft_gates if f"{g}" not in matched],
        suggested_gate=suggested,
        live=live,
        notes=notes,
    )


def apply_mib_soft_coverage(
    rows: list[CoverageRow],
    gates: list[GateInfo],
    panel_metrics: set[str],
) -> list[CoverageRow]:
    """If any group in a MIB is covered, mark sibling groups covered via that gate."""
    gate_names = {g.name for g in gates}
    gate_metric = {g.name: g.metric for g in gates if g.metric}
    mib_gates: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        if r.status != "covered":
            continue
        for g in r.matched_gates:
            name = g.split()[0]
            if name in gate_names:
                mib_gates[r.mib].add(name)
        if r.mib in MIB_GATE_OVERRIDES and MIB_GATE_OVERRIDES[r.mib] in gate_names:
            mib_gates[r.mib].add(MIB_GATE_OVERRIDES[r.mib])

    out: list[CoverageRow] = []
    for r in rows:
        if r.status == "covered":
            out.append(r)
            continue
        curated = MIB_GATE_OVERRIDES.get(r.mib)
        candidates = set(mib_gates.get(r.mib) or [])
        if curated and curated in gate_names:
            candidates.add(curated)
        if not candidates:
            out.append(r)
            continue
        chosen = curated if curated in candidates else next(iter(candidates))
        gmet = gate_metric.get(chosen, "")
        if gmet and gmet not in panel_metrics:
            for c in candidates:
                if gate_metric.get(c) in panel_metrics:
                    chosen = c
                    gmet = gate_metric[c]
                    break
        if not gmet or gmet not in panel_metrics:
            out.append(r)
            continue
        r.status = "covered"
        r.matched_gates = list(
            dict.fromkeys([*(r.matched_gates or []), chosen, f"{chosen} (mib-soft)"])
        )
        r.notes = (r.notes + "; " if r.notes else "") + "mib soft-coverage"
        out.append(r)
    return out


def collect_profile_paths(lab_only: bool, profiles_root: Path | None) -> tuple[list[Path], list[Path]]:
    """Return (profile files to parse as roots, search roots for extends)."""
    search: list[Path] = []
    roots: list[Path] = []

    if profiles_root and profiles_root.is_dir():
        search.append(profiles_root)
        # Prefer device profiles (skip _template)
        for p in sorted(profiles_root.rglob("*.yml")):
            if p.name.startswith("_"):
                continue
            if p.name.endswith("_template.yml"):
                continue
            roots.append(p)
        return roots, search

    # Lab profiles + upstream if present beside repo
    for p in DEFAULT_LAB_PROFILES:
        if p.is_file():
            roots.append(p)
            search.append(p.parent)

    upstream = REPO.parent / "snmp-profiles" / "profiles" / "kentik_snmp"
    local_ref = ROOT / ".ref-snmp-profiles" / "profiles" / "kentik_snmp"
    for cand in (upstream, local_ref):
        if cand.is_dir():
            search.append(cand)
            if not lab_only:
                for p in sorted(cand.rglob("*.yml")):
                    if p.name.startswith("_"):
                        continue
                    roots.append(p)
            break

    # Always add _general to search via upstream
    for cand in (upstream, local_ref):
        if cand.is_dir() and cand not in search:
            search.append(cand)

    return roots, search


def write_outputs(
    rows: list[CoverageRow],
    gates: list[GateInfo],
    panel_metrics: set[str],
    live_names: set[str],
    profile_count: int,
    *,
    out_md: Path,
    out_json: Path,
    title_suffix: str = "",
) -> None:
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    dead = [g for g in gates if not g.metric]
    dead_metric = [
        g
        for g in gates
        if g.metric
        and live_names
        and g.metric not in live_names
        and g.metric not in panel_metrics
        and not g.metric.startswith("network_io")
    ]

    by_status: dict[str, int] = defaultdict(int)
    for r in rows:
        by_status[r.status] += 1

    payload = {
        "profile_files": profile_count,
        "rows": [asdict(r) for r in rows],
        "gates": [asdict(g) for g in gates],
        "dead_gates_empty_metric": [asdict(g) for g in dead],
        "dead_gates_unseen": [asdict(g) for g in dead_metric],
        "summary": dict(by_status),
        "live_metric_count": len(live_names),
        "panel_metric_count": len(panel_metrics),
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    total = len(rows) or 1
    covered = by_status.get("covered", 0)
    heading = "# MIB / profile coverage matrix" + (f" ({title_suffix})" if title_suffix else "")
    lines = [
        heading,
        "",
        "Generated by `local/scripts/mib-coverage-inventory.py`. Do not edit by hand.",
        "",
        "## Summary",
        "",
        f"- Profile metric groups (table/scalar): **{len(rows)}** across **{profile_count}** profile files",
        f"- `has_*` gates on Device Details: **{len(gates)}**",
        f"- Covered: **{covered}** ({100 * covered / total:.1f}%)",
        f"- Gate only: **{by_status.get('gate_only', 0)}**",
        f"- Live/panel ungated: **{by_status.get('live_ungated', 0)}**",
        f"- Profile only (backlog): **{by_status.get('profile_only', 0)}**",
        f"- Live Prom metric names sampled: **{len(live_names)}**",
        "",
        "### Status legend",
        "",
        "| Status | Meaning |",
        "|--------|---------|",
        "| `covered` | Profile metrics map to a `has_*` gate metric and appear in panel exprs |",
        "| `gate_only` | Gate exists; panels do not reference these Prom names |",
        "| `live_ungated` | Panels or live series exist without a matching gate metric |",
        "| `profile_only` | In SNMP profile; not gated / not in panels (backlog) |",
        "",
        "## Dead / empty gates",
        "",
    ]
    if dead:
        lines.append("Empty gate metrics:")
        for g in dead:
            lines.append(f"- `{g.name}`")
        lines.append("")
    else:
        lines.append("_None._")
        lines.append("")
    if dead_metric:
        lines.append("Gate metrics not seen in live sample (may be vendor-specific OK):")
        for g in dead_metric[:40]:
            lines.append(f"- `{g.name}` → `{g.metric}`")
        if len(dead_metric) > 40:
            lines.append(f"- … and {len(dead_metric) - 40} more")
        lines.append("")

    lines += [
        "## Backlog (profile_only + live_ungated + gate_only)",
        "",
        "| Profile | MIB | Kind | Table/scalar | Prom names | Suggested gate | Status |",
        "|---------|-----|------|--------------|------------|----------------|--------|",
    ]
    backlog = [r for r in rows if r.status in {"profile_only", "live_ungated", "gate_only"}]
    backlog.sort(key=lambda r: (r.status != "live_ungated", r.profile, r.mib, r.table_or_scalar))
    # Cap markdown size for full-library runs
    shown = backlog[:500]
    for r in shown:
        prom = ", ".join(f"`{n}`" for n in r.prom_names[:3])
        if len(r.prom_names) > 3:
            prom += ", …"
        lines.append(
            f"| `{r.profile}` | `{r.mib}` | {r.kind} | `{r.table_or_scalar}` | {prom} | `{r.suggested_gate}` | `{r.status}` |"
        )
    if len(backlog) > len(shown):
        lines.append(f"| … | … | … | _{len(backlog) - len(shown)} more in JSON_ | … | … | … |")

    lines += [
        "",
        "## Covered (sample)",
        "",
        "| Profile | Table/scalar | Gates |",
        "|---------|--------------|-------|",
    ]
    covered_rows = sorted([x for x in rows if x.status == "covered"], key=lambda x: (x.profile, x.table_or_scalar))
    for r in covered_rows[:200]:
        lines.append(
            f"| `{r.profile}` | `{r.table_or_scalar}` | {', '.join('`'+g+'`' for g in r.matched_gates) or '—'} |"
        )
    if len(covered_rows) > 200:
        lines.append(f"| … | _{len(covered_rows) - 200} more_ | … |")

    lines += [
        "",
        "## Refresh",
        "",
        "```bash",
        "python3 local/scripts/mib-coverage-inventory.py",
        "python3 local/scripts/mib-coverage-inventory.py --live-prom",
        "python3 local/scripts/mib-coverage-inventory.py --full-library",
        "python3 local/scripts/mib-coverage-inventory.py --general-only",
        "```",
        "",
        "**Done bar (rudimentary):** each profile table has a `has_*` gate + at least one panel.",
        "",
        f"JSON: `{out_json.relative_to(REPO) if out_json.is_relative_to(REPO) else out_json}`",
        "",
    ]
    out_md.write_text("\n".join(lines), encoding="utf-8")
    print(f"wrote {out_md}")
    print(f"wrote {out_json}")
    print(f"summary: {dict(by_status)}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profiles-root",
        type=Path,
        help="Root of kentik_snmp profiles (enables full-library scan)",
    )
    parser.add_argument(
        "--lab-only",
        action="store_true",
        help="Only lab profiles under local/snmp-profiles (default when no --profiles-root/--full-library)",
    )
    parser.add_argument(
        "--full-library",
        action="store_true",
        help="Scan sibling ../snmp-profiles/profiles/kentik_snmp (no extends fan-in)",
    )
    parser.add_argument(
        "--general-only",
        action="store_true",
        help="Scan only ../snmp-profiles/.../_general generic MIB profiles",
    )
    parser.add_argument(
        "--vendors",
        default="",
        help="Comma-separated vendor dirs under kentik_snmp (e.g. cisco,arista,f5)",
    )
    parser.add_argument("--from-grafana", action="store_true", help="Pull Device Details from GRAFANA_URL")
    parser.add_argument("--live-prom", action="store_true", help="Query Prometheus for live metric names")
    args = parser.parse_args()

    env = load_env()

    profiles_root = args.profiles_root
    vendor_list = [v.strip() for v in (args.vendors or "").split(",") if v.strip()]
    if vendor_list and not profiles_root:
        # Placeholder; files collected below from each vendor dir
        profiles_root = REPO.parent / "snmp-profiles" / "profiles" / "kentik_snmp"
        if not profiles_root.is_dir():
            raise SystemExit(f"--vendors: missing {profiles_root}")
    if args.general_only and not profiles_root:
        cand = REPO.parent / "snmp-profiles" / "profiles" / "kentik_snmp" / "_general"
        if not cand.is_dir():
            raise SystemExit(f"--general-only: missing {cand}")
        profiles_root = cand
    if getattr(args, "full_library", False) and not profiles_root:
        cand = REPO.parent / "snmp-profiles" / "profiles" / "kentik_snmp"
        if not cand.is_dir():
            raise SystemExit(f"--full-library: missing {cand}")
        profiles_root = cand

    root_files, search_roots = collect_profile_paths(
        lab_only=profiles_root is None,
        profiles_root=None if vendor_list else profiles_root,
    )
    if vendor_list:
        base = REPO.parent / "snmp-profiles" / "profiles" / "kentik_snmp"
        root_files = []
        for v in vendor_list:
            d = base / v
            if not d.is_dir():
                print(f"WARN: missing vendor {d}", file=sys.stderr)
                continue
            for p in sorted(list(d.glob("*.yml")) + list(d.glob("*.yaml"))):
                if p.name.startswith("traps"):
                    continue
                root_files.append(p)
        search_roots = [base]
    # _general scan: include underscore-prefixed yml (collect_profile_paths skips _*)
    if args.general_only and profiles_root and profiles_root.is_dir():
        root_files = sorted(p for p in profiles_root.glob("*.yml") if p.is_file())
        search_roots = [profiles_root.parent, profiles_root]
    if not root_files:
        root_files = [p for p in DEFAULT_LAB_PROFILES if p.is_file()]
        search_roots = [p.parent for p in root_files]
        upstream = REPO.parent / "snmp-profiles" / "profiles" / "kentik_snmp"
        if upstream.is_dir():
            search_roots.append(upstream)

    print(f"parsing {len(root_files)} profile file(s); search_roots={len(search_roots)}")
    all_metrics: list[ProfileMetric] = []

    # Lab view expands extends into the device profile; full library attributes metrics to defining file only.
    expand = profiles_root is None

    for path in root_files:
        metrics = parse_profile_file(
            path, search_roots, seen_extends=set(), expand_extends=expand
        )
        if expand:
            for m in metrics:
                m.profile = path.stem
        all_metrics.extend(metrics)

    all_metrics = [m for m in all_metrics if m.symbol != "(unresolved)"]

    if args.from_grafana:
        dash = load_dashboard_from_grafana(env)
    else:
        dash = load_dashboard_from_upstream()

    gates = extract_gates_from_dashboard(dash)
    panel_metrics = extract_panel_metrics(dash)
    live_names: set[str] = set()
    if args.live_prom:
        live_names = query_live_metric_names(env)
        print(f"live metric names: {len(live_names)}")

    # Group by profile + mib + kind + table
    groups: dict[tuple[str, str, str, str], list[ProfileMetric]] = defaultdict(list)
    for m in all_metrics:
        groups[(m.profile, m.mib, m.kind, m.table_or_scalar)].append(m)

    rows = [
        classify(key, mets, gates, panel_metrics, live_names)
        for key, mets in sorted(groups.items(), key=lambda kv: kv[0])
    ]
    rows = apply_mib_soft_coverage(rows, gates, panel_metrics)

    is_general = bool(args.general_only)
    is_vendors = bool(getattr(args, "vendors", None))
    is_full = profiles_root is not None and not is_general and not is_vendors
    if is_vendors:
        out_md = ROOT / "docs" / "mib-coverage-matrix-vendors.md"
        out_json = ROOT / ".dash-payloads" / "mib-coverage" / "matrix-vendors.json"
        title = f"priority vendors ({args.vendors})"
    elif is_general:
        out_md = ROOT / "docs" / "mib-coverage-matrix-general.md"
        out_json = ROOT / ".dash-payloads" / "mib-coverage" / "matrix-general.json"
        title = "_general generic MIB profiles"
    elif is_full:
        out_md = OUT_MD_FULL
        out_json = OUT_JSON_FULL
        title = "full kentik/snmp-profiles library"
    else:
        out_md = OUT_MD
        out_json = OUT_JSON
        title = "lab profiles"
    write_outputs(
        rows,
        gates,
        panel_metrics,
        live_names,
        profile_count=len(root_files),
        out_md=out_md,
        out_json=out_json,
        title_suffix=title,
    )
    return 0


if __name__ == "__main__":
    # Path.is_relative_to is 3.9+; polyfill for clarity on older
    if not hasattr(Path, "is_relative_to"):
        def _is_relative_to(self: Path, other: Path) -> bool:  # type: ignore
            try:
                self.relative_to(other)
                return True
            except ValueError:
                return False

        Path.is_relative_to = _is_relative_to  # type: ignore

    raise SystemExit(main())
