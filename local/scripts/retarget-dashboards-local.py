#!/usr/bin/env python3
"""Retarget the AWS-authored net-o11y dashboards to the local ktranslate/OTLP schema.

The dashboards under ../../grafana/dashboards/ were authored for the AWS / EKS
path (Grafana Cloud SNMP + gNMI integrations). Their metric names and labels do
NOT match what the local `local/` deployment ships via ktranslate + Alloy OTLP,
so every panel is empty against a local stack until retargeted.

This reads the AWS source dashboards and writes local-schema variants to
../dashboards/ (local/dashboards/). It does NOT modify the AWS originals, so the
AWS / EKS path is unaffected.

Schema mapping (local, verified 2026-07):
  SNMP   metrics carry a `kentik_snmp_` prefix (ifHCInOctets -> kentik_snmp_ifHCInOctets,
         ifOperStatus -> kentik_snmp_if_OperStatus, sysUpTime -> kentik_snmp_Uptime);
         device is the `device_name` label (not `source`/`job`); interface is
         `if_Description` (e.g. ethernet-1/1); a single job `ktranslate-snmp-srl-<host>`.
         AWS `job=~"integrations/snmp/..."` selectors -> `device_name` selectors.
  gNMI   metric names match as-authored but carry `job="network-topology-exporter"`
         (NOT `job="gnmic"`); device is the `source` label. Only bgp_neighbors +
         lldp are subscribed locally, so gNMI CPU/interface metrics do not exist —
         `srl_cpu_*` / `srl_iface_*` / `srl_memory_*` remap to kentik_snmp_ equivalents.
  Flow   network_io_by_flow_bytes (unchanged).
  Loki   device syslog lives under {service_name="ktranslate"} (ktranslate --tee_logs;
         no hostname/severity stream labels).

Usage:
    python3 local/scripts/retarget-dashboards-local.py
    # then import (with gcx OAuth, or GRAFANA_URL+GRAFANA_TOKEN):
    #   gcx --context <ctx> api /api/dashboards/db -d @<wrapped-payload>
"""
import json
import os
import re

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
SRC = os.path.join(ROOT, "grafana", "dashboards")
DST = os.path.join(ROOT, "local", "dashboards")

# net-o11y dashboards that target fabric telemetry (the linux-compliance-* set is
# out of scope: it has no equivalent on the local network lab).
NAMES = [
    "bgp-status", "device-details", "interface-health",
    "network-topology", "traffic-flows", "traffic-sankey",
]


def snmp(s: str) -> str:
    # memory utilization: no local gauge -> compute from Used / (Used + Available)
    s = re.sub(
        r"srl_memory_utilization\{([^}]*)\}",
        r"(100 * sum by (device_name) (kentik_snmp_MemoryUsed{\1}) "
        r"/ (sum by (device_name) (kentik_snmp_MemoryUsed{\1}) "
        r"+ sum by (device_name) (kentik_snmp_MemoryAvailable{\1})))",
        s,
    )
    # gNMI metrics that do not exist locally -> SNMP equivalents
    for a, b in [
        ("srl_cpu_total_average_1", "kentik_snmp_CPU"),
        ("srl_cpu_total_average_5", "kentik_snmp_CPU"),
        ("srl_memory_free", "kentik_snmp_MemoryAvailable"),
        ("srl_iface_in_octets", "kentik_snmp_ifHCInOctets"),
        ("srl_iface_out_octets", "kentik_snmp_ifHCOutOctets"),
        ("srl_iface_in_packets", "kentik_snmp_ifHCInUcastPkts"),
        ("srl_iface_out_packets", "kentik_snmp_ifHCOutUcastPkts"),
        ("srl_iface_in_discarded_packets", "kentik_snmp_ifInDiscards"),
        ("srl_iface_in_error_packets", "kentik_snmp_ifInErrors"),
    ]:
        s = s.replace(a, b)
    # bare SNMP metric names -> kentik_snmp_ prefixed
    s = re.sub(
        r"(?<![\w])if(HCInOctets|HCOutOctets|HCInUcastPkts|HCOutUcastPkts|"
        r"HCInMulticastPkts|HCOutMulticastPkts|HCInBroadcastPkts|HCOutBroadcastPkts|"
        r"InErrors|OutErrors|InDiscards|OutDiscards)\b",
        r"kentik_snmp_if\1",
        s,
    )
    s = re.sub(r"(?<![\w])ifOperStatus\b", "kentik_snmp_if_OperStatus", s)
    s = re.sub(r"(?<![\w])ifAdminStatus\b", "kentik_snmp_if_AdminStatus", s)
    s = re.sub(r"\bsysUpTime\b", "kentik_snmp_Uptime", s)
    s = re.sub(r"\bsysDescr\b", "kentik_snmp_Uptime", s)
    # Loki syslog panels -> local ktranslate teed logs
    s = re.sub(r'job="syslog/srl",\s*hostname=~"[^"]*"', 'service_name="ktranslate"', s)
    s = re.sub(r'job="syslog/srl"', 'service_name="ktranslate"', s)
    s = re.sub(r'\|\s*severity\s*=~\s*"[^"]*"', '|~ "(?i)warn|error|crit"', s)
    # label renames
    s = re.sub(r"\binterface_name\b", "if_Description", s)
    s = re.sub(r"\bifDescr\b", "if_Description", s)
    s = re.sub(r"\bifName\b", "if_interface_name", s)
    # AWS integration job selectors -> device_name
    s = re.sub(r'job=~?"integrations/snmp/[^"]*\$device[^"]*"', 'device_name=~"$device"', s)
    s = re.sub(r'job=~?"integrations/snmp/[^"]*"', 'device_name=~".+"', s)
    s = re.sub(r'\s*,?\s*job=~?"integrations/gnmi"', "", s)
    # device label + label_values extraction
    s = re.sub(r"\bsource\b", "device_name", s)
    s = re.sub(r"\bby \(job\)", "by (device_name)", s)
    s = re.sub(r"\}, job\)", "}, device_name)", s)
    # selector cleanup
    s = s.replace("{, ", "{").replace("{,", "{")
    s = re.sub(r",\s*\}", "}", s)
    return s


def gnmi(s: str) -> str:
    return s.replace('job="gnmic"', 'job="network-topology-exporter"') \
            .replace('job=~"gnmic"', 'job=~"network-topology-exporter"')


def xform(v):
    if isinstance(v, str):
        return gnmi(v) if "gnmi_" in v else snmp(v)
    if isinstance(v, dict):
        return {k: xform(x) for k, x in v.items()}
    if isinstance(v, list):
        return [xform(x) for x in v]
    return v


def fix_variable_regex(dash):
    """Template variables extracted a short name from the AWS `job` label via a
    `regex: integrations/snmp/(.*)` field. Locally the variable already returns
    clean device_name values (spine1/leaf1/leaf2), so that regex now filters
    everything out -> empty variable -> blank dashboard. Clear it."""
    for var in dash.get("templating", {}).get("list", []):
        rx = var.get("regex")
        if isinstance(rx, str) and "integrations/snmp" in rx:
            var["regex"] = ""
    return dash


def main():
    os.makedirs(DST, exist_ok=True)
    for name in NAMES:
        src = os.path.join(SRC, f"{name}.json")
        with open(src, encoding="utf-8") as f:
            dash = json.load(f)
        dash = xform(dash)
        dash = fix_variable_regex(dash)
        out = os.path.join(DST, f"{name}.json")
        with open(out, "w", encoding="utf-8") as f:
            json.dump(dash, f, indent=2, ensure_ascii=False)
            f.write("\n")
        print(f"wrote {os.path.relpath(out, ROOT)}")


if __name__ == "__main__":
    main()
