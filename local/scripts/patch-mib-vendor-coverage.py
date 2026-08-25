#!/usr/bin/env python3
"""Rudimentary Device Details coverage for priority vendor snmp-profiles.

Vendors: cisco, apc, arista, aruba, dell, eaton, f5, fortinet, hpe, juniper,
linksys, meraki, riverbed, checkpoint.

Strategy:
  - 1 has_* + panel per uncovered **table**
  - 1 has_* + panel per **scalar-only MIB** (covers sibling scalars via inventory soft-match)
  - Prefer mapping to existing gates when CAPABILITY_HINTS already apply

Usage:
  python3 local/scripts/patch-mib-vendor-coverage.py           # write KtransToGrafana
  python3 local/scripts/patch-mib-vendor-coverage.py --push --force  # frozen unless --force
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

VENDORS = [
    "cisco",
    "apc",
    "arista",
    "aruba",
    "dell",
    "eaton",
    "f5",
    "fortinet",
    "hpe",
    "juniper",
    "linksys",
    "meraki",
    "riverbed",
    "checkpoint",
]

# Load panel helpers
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

# Inventory module
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


def slug(s: str, prefix: str = "has_") -> str:
    base = re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")
    base = re.sub(r"_+", "_", base)[:40].strip("_")
    return f"{prefix}{base}"


def pick_tab(mib: str, table: str, metric: str) -> int:
    blob = f"{mib} {table} {metric}".lower()
    if re.search(
        r"ups|pdu|epdu|power|fan|temp|sensor|env|battery|idrac|netbotz|"
        r"voltage|current|chassis|fru|disk|storage|raid|nimble|msa",
        blob,
    ):
        return HARDWARE_TAB
    if re.search(
        r"bgp|ospf|hsrp|wlan|wireless|aire|bsn|apif|dot11|vpn|ipsec|"
        r"ha|peer|lldp|user|session|tunnel|slb|load.?balanc|virtual.?server|"
        r"queue|cos|dcu|scu|firewall|cras|remote.?access",
        blob,
    ):
        return CONNECTIONS_TAB
    return OVERVIEW_TAB


def collect_vendor_files(base: Path) -> list[Path]:
    files: list[Path] = []
    for v in VENDORS:
        d = base / v
        if not d.is_dir():
            continue
        for p in sorted(list(d.glob("*.yml")) + list(d.glob("*.yaml"))):
            if p.name.startswith("traps"):
                continue
            files.append(p)
    return files


def build_backlog(dash: dict) -> list[dict[str, Any]]:
    base = REPO.parent / "snmp-profiles" / "profiles" / "kentik_snmp"
    files = collect_vendor_files(base)
    search = [base]
    all_metrics = []
    for path in files:
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
    backlog = [r for r in rows if r.status != "covered"]
    uniq: dict[tuple, dict] = {}
    for r in backlog:
        # Skip identity-only MIB noise
        if r.mib in {"SNMPv2-MIB", "SNMPv2-SMI"}:
            continue
        key = (r.mib, r.kind, r.table_or_scalar)
        if key not in uniq:
            uniq[key] = {
                "mib": r.mib,
                "kind": r.kind,
                "table": r.table_or_scalar,
                "prom": r.prom_names[0] if r.prom_names else "",
                "prom_all": r.prom_names,
                "suggested_gate": r.suggested_gate,
                "profiles": [],
            }
        uniq[key]["profiles"].append(r.profile)
    return list(uniq.values())


# Curated gate names for important vendor MIBs (override ugly auto-slugs)
CURATED_GATES: dict[str, str] = {
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
}


def select_specs(backlog: list[dict], existing_gates: set[str]) -> list[dict[str, Any]]:
    """One spec per uncovered table + one per scalar-only MIB."""
    by_mib: dict[str, list] = defaultdict(list)
    for u in backlog:
        by_mib[u["mib"]].append(u)

    specs: list[dict[str, Any]] = []
    seen_gates: set[str] = set(existing_gates)

    def add_spec(u: dict, gate: str) -> None:
        if gate in seen_gates:
            return
        if not u["prom"]:
            return
        seen_gates.add(gate)
        value_field = u["prom"].replace("kentik_snmp_", "", 1)
        kind = "table" if u["kind"] == "table" else "stat"
        short = u["table"] if len(u["table"]) < 48 else u["table"][:45] + "…"
        specs.append(
            {
                "tab": pick_tab(u["mib"], u["table"], u["prom"]),
                "gate": gate,
                "metric": u["prom"],
                "row": f"{u['mib']}: {short}",
                "panel": f"panel-{gate}",
                "kind": kind,
                "title": short,
                "value_field": value_field,
                "rename": {value_field: "Value"},
                "desc": f"{u['mib']} {u['table']} (rudimentary vendor MIB coverage).",
            }
        )

    for mib, items in sorted(by_mib.items()):
        tabs = [i for i in items if i["kind"] == "table"]
        scals = [i for i in items if i["kind"] == "scalar"]
        curated = CURATED_GATES.get(mib)

        if curated and (tabs or scals):
            # Prefer a health-ish representative metric when possible
            pool = tabs + scals
            pref = re.compile(
                r"(?i)status|state|health|battery|capacity|load|cpu|memory|temp|util|"
                r"drop|error|alarm|oper|conn|peer|session"
            )
            ranked = sorted(
                pool,
                key=lambda u: (0 if pref.search(u["prom"] + u["table"]) else 1, u["table"]),
            )
            add_spec(ranked[0], curated)
            continue

        for t in tabs:
            gate = t["suggested_gate"]
            if not gate.startswith("has_") or len(gate) > 36:
                gate = slug(t["table"])
            add_spec(t, gate)
        if scals and not tabs:
            rep = scals[0]
            add_spec(rep, slug(mib.replace("-MIB", "").replace("_MIB", "")))

    return specs


def upsert_row(rows: list[dict], title: str, gate: str, items: list[dict]) -> None:
    for i, r in enumerate(rows):
        if (r.get("spec") or {}).get("title") == title:
            rows[i] = conditional_row(title, gate, items)
            print(f"replaced row {title}")
            return
    rows.append(conditional_row(title, gate, items))
    print(f"added row {title}")


def existing_gate_names(dash: dict) -> set[str]:
    names: set[str] = set()
    for v in dash.get("spec", {}).get("variables") or []:
        n = (v.get("spec") or {}).get("name") or ""
        if n.startswith("has_"):
            names.add(n)
    return names


def patch(dash: dict) -> tuple[dict, list[dict]]:
    dash = copy.deepcopy(dash)
    elements = dash["spec"]["elements"]
    variables = dash["spec"]["variables"]
    backlog = build_backlog(dash)
    specs = select_specs(backlog, existing_gate_names(dash))
    print(f"backlog unique groups={len(backlog)}; new specs={len(specs)}")

    # Reuse panel ids when panel key already exists
    next_id = max_panel_id(elements) + 1
    for spec in specs:
        upsert_variable(variables, make_gate(spec["gate"], spec["metric"]))
        print(f"gate {spec['gate']} -> {spec['metric']}")

        existing = elements.get(spec["panel"])
        if existing and isinstance((existing.get("spec") or {}).get("id"), int):
            pid = existing["spec"]["id"]
        else:
            pid = next_id
            next_id += 1

        expr = f'{spec["metric"]}{{snmp_group=~"$snmp_group",device_name=~"$instance"}}'
        if spec["kind"] == "stat":
            panel = make_stat_panel(pid, spec["title"], expr, spec["desc"])
        else:
            panel = make_table_panel(
                pid,
                spec["title"],
                expr,
                spec["desc"],
                spec["value_field"],
                spec.get("rename"),
            )
        elements[spec["panel"]] = panel

        tab = dash["spec"]["layout"]["spec"]["tabs"][spec["tab"]]
        rows = tab["spec"]["layout"]["spec"]["rows"]
        h = 5 if spec["kind"] == "stat" else 8
        w = 8 if spec["kind"] == "stat" else 24
        upsert_row(rows, spec["row"], spec["gate"], [grid_item(spec["panel"], 0, 0, w, h)])

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
    print(f"verify layout.kind={kind}")
    if kind != "TabsLayout":
        raise SystemExit(f"layout degraded to {kind}")


def write_capability_hints_snippet(specs: list[dict]) -> Path:
    """Write JSON of new gates for inventory --vendors soft-match / docs."""
    out = ROOT / ".dash-payloads" / "mib-coverage" / "vendor-gates.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps(
            [{"gate": s["gate"], "metric": s["metric"], "mib_row": s["row"]} for s in specs],
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {out}")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--push", action="store_true")
    parser.add_argument("--from-live", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Override freeze: per-MIB has_* on Device Details hurts empty-stack TTI",
    )
    args = parser.parse_args()
    if args.push and not args.force:
        raise SystemExit(
            "Frozen: vendor per-MIB has_* on Device Details (empty label_values dominate TTI). "
            "Map to existing capability gates or use a role spoke. "
            "Pass --force to override. See docs/grafana-network-dashboard-expand-hardware.md"
        )

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
    print(f"wrote {path}")
    write_capability_hints_snippet(specs)

    if args.push:
        push_marc(patched)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
