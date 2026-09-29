# Alloy Network Dashboard — Expanding for New Hardware

Use when a **new device type** (Alloy SNMP fingerprint / vendor module) is added and an **Alloy Network Fork** Device Details dashboard should cover it — on any Grafana Cloud stack running Alloy SNMP.

**Panel standards:** [Alloy Design Patterns](grafana-alloy-network-dashboard-design-patterns.md)

**Do not use the ktranslate expand skill** on A0–A4. That skill gates on `kentik_snmp_*` / Kentik `snmp-profiles` and will hide Alloy rows or invent empty `label_values`.

**Convention:** `$device` = your single-device dashboard variable (PromQL label `device_name`; some boards name it `$instance`).

---

## What “new hardware” means on Alloy

Identity and modules come from live SNMP, not a ktranslate `devices.yaml`:

1. CIDR discovery reads `sysName` (device identity) and `sysObjectID` (fingerprinter).
2. The fingerprinter selects **one** hot module set, **one** cold set, and **one** `{fingerprint}_topo` object.
3. Hot + cold land in Mimir as `snmp_*` (`job="alloy-snmp"`).
4. Topology walks go to **topology-exporter** (`network_topology_*`). They are not a dashboard PromQL source.

Unknown `sysObjectID` uses `device_base` / `device_base_topo`. Do not generate management-IP name overrides so IPAM churn cannot rename a box.

Expected vs actual:

| Source | What it tells you |
|--------|-------------------|
| Image `fingerprinters.yml` + `module-tiers.yaml` | Which modules *should* walk |
| Live `{job="alloy-snmp"}` series | What is actually in Mimir |
| `network_topology_edge_info` | Which neighbor/session edges the exporter reconciled |

Kentik `snmp-profiles` are **input to the converter**, not the live contract. After convert, edit `snmp/modules/` in the Alloy library. Dashboard work starts from live `snmp_*` names (see `local/fixtures/alloy-snmp/ktranslate-name-map.md` if you need a kentik → `snmp_*` hint).

The ktranslate `mib-coverage-inventory.py` helpers are **not** the Alloy path. Do not drive A4 `has_*` from that matrix.

---

## Overview

The dashboard uses **`has_*` conditional rows**. Each row renders only when the selected device reports the gate metric **in Mimir** (or on the topology graph). Adding a device type means:

1. Discover what metrics / edges it reports
2. Map them to existing `has_*` rows (often no changes)
3. Identify gaps that are operator-meaningful
4. Build new `has_*` variables + rows only for **new capabilities**
5. Validate show/hide behavior

**Done bar:** map new vendors onto existing capability gates (`has_cpu`, `has_temp`, `has_fan_state`, `has_interfaces`, sensor units, `has_bgp` via topology-exporter). Do **not** add a dashboard-level `has_*` per MIB, per vendor table, or per topology fragment.

---

## Step 1 — Discover metrics

**Live Prometheus (any Alloy stack):**

```promql
count by (__name__) ({job="alloy-snmp", device_name=~"$device"})
```

Filter `__name__` with `snmp_.*` (not `kentik_.*`).

Topology (Connections), separately:

```promql
count by (discovery_proto, evidence) (
  network_topology_edge_info{tester_id="network-lab", src_device=~"$device"}
)
```

**Grafana MCP / Assistant tools:**

- `search_label_values` — label `__name__`, selector `{job="alloy-snmp", device_name=~"$device"}`, regex `snmp_.*`

**Do not** expect `snmp_tBgpPeerNgConnState` (or other topology-tier names) in Mimir. If those series are missing, that is the contract — use the exporter graph.

---

## Step 2 — Map to existing rows

List dashboard variables prefixed `has_`. Each gate's **`metric`** field defines which family the row needs.

If the new device already exports that metric → row auto-shows. **No dashboard change.**

Discover variables via:

- Dashboard **Settings → Variables**
- Exported v2 manifest (`spec.variables`)
- gcx: `dashboards get <uid>`

All SNMP `has_*` filters should use `device_name=~"$device"` (or `$instance`). Topology gates use `src_device`.

### Example gate metrics (verify on your fleet — not universal constants)

| Variable | Example gate metric | Notes |
|----------|---------------------|-------|
| `has_cpu` | `snmp_CPU` | Utilization %. Do not gate on `snmp_CPULoad` |
| `has_memory` | `device:snmp_MemoryUtilization:percent` | Match whatever panels query |
| `has_interfaces` | `snmp_ifOperStatus` | Hot IF-MIB |
| `has_polling` | `up{job="alloy-snmp"}` | There is no `kentik_snmp_PollingHealth` |
| `has_bgp` | `network_topology_edge_info` | `discovery_proto="bgp"`, `src_device=~"$device"` |
| `has_lldp` | `network_topology_edge_info` | `discovery_proto="lldp"` if you split the row |
| `has_ping` | only if a ping integration exists | Alloy SNMP does not emit `kentik_ping_*` |

---

## Step 3 — Identify gaps

Uncovered **hot/cold** metrics that are operator-meaningful (health, state, capacity, errors) → candidates for new rows. Skip low-signal diagnostic OIDs.

Ask:

- Stat + timeseries pair, or table?
- Existing tab/section, or new row?
- Does an existing `has_*` cover a sibling metric?
- Is this actually topology? If yes, **expand the `{fingerprint}_topo` module and exporter mapping**, not a PromQL panel on a raw neighbor OID.

Collector-side topology rule: discovery emits **exactly one** consolidated `{fingerprint}_topo` object. Generic LLDP (plus Cisco/Meraki CDP) and selected control-plane neighbor fragments fold into that object. Do not restore multi-module topology chains for dashboard convenience.

---

## Step 4 — Build `has_*` variables

**First** map the new device onto an existing capability gate. Only add a new `has_*` when it is a **new capability**, not a new vendor table. Each extra gate is a `label_values` miss on every stack that lacks that metric.

One hidden QueryVariable per new row **before** panels:

```
kind: QueryVariable
name: has_<feature>
hide: hideVariable
refresh: onTimeRangeChanged
query:
  group: prometheus
  qryType: 1
  label: device_name
  metric: <primary metric for this section — must exist in Mimir>
  labelFilters: [{ device_name =~ "$device" }]
```

**Gate metric rules:**

1. Must return label values when the device supports the feature
2. Must match the **same metric family** panels query (see Alloy Design Patterns)
3. Must be a series that **actually arrives** — not a topology-tier name
4. Confirm live: `count(<metric>{job="alloy-snmp", device_name="<device>"})`

---

## Step 5 — Build row and panels

Place per **Placement Guide**. Follow Alloy Design Patterns for layout, transforms, PromQL (`rate()` on counters, recording rules for composites, topology-exporter for Connections), and naming.

**Row conditional rendering:**

```
visibility: show
condition: and
items: [{ kind: ConditionalRenderingVariable, variable: "has_<feature>", operator: "matches", value: ".+" }]
```

**v2 TabsLayout edits:** GET live manifest → edit `spec.elements` / tab layout → PUT with `resourceVersion`. Never `POST /api/dashboards/db` on tabbed boards.

---

## Step 6 — Validate

1. Select the **new device** in `$device`
2. New row **visible** with populated panels
3. Select a device **without** those metrics
4. Row **hidden** (not merely empty — empty indicates wrong gate or leftover `kentik_snmp_*` / `* 8 / 60`)
5. Multi-row tables: confirm row count matches entity count (`merge` present)
6. Connections: confirm edges via `network_topology_edge_info`, and that `network_topology_graph_stale` is not explaining an empty graph
7. Screenshot: layout, units, legends

```promql
count(<gate_metric>{job="alloy-snmp", device_name="<new-device>"})
max by (device_name) (<panel_metric>{job="alloy-snmp", device_name="<new-device>"})
```

---

## Placement guide

| Content | Tab (typical) |
|---------|----------------|
| CPU, memory, uptime KPIs | Overview |
| Interface / traffic (hot octets; cold errors/packets) | Interfaces |
| Temp, fan, power sensors | Hardware Sensors |
| BGP / LLDP / CDP **observed** edges | Connections (topology-exporter) |
| Traps / syslog volume | Telemetry / Events — Loki `alloy-snmptrap` / `alloy-syslog` |
| Scrape / discovery health | Health / Telemetry — `up{job="alloy-snmp"}`, `discovery_snmp_*` — **not** CHF |
| Large feature sets that are still in Mimir | Consider a new tab — still no raw topology SNMP |

---

## See also

- [Alloy Design Patterns](grafana-alloy-network-dashboard-design-patterns.md)
- [Skills README](grafana-network-dashboard-skills-README.md)
- [Alloy network fork](alloy-network-fork.md)
- ktranslate twin (do not mix): [Expanding for New Hardware](grafana-network-dashboard-expand-hardware.md)
