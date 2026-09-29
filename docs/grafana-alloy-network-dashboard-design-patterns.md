# Alloy Network Dashboards — Design Patterns

Reference for visual and structural consistency on **Alloy Network Fork** Device Details / Device Summary boards (A0–A4). Apply when adding panels, rows, or tabs on **any Grafana Cloud stack** running the Alloy network addons.

**Companion skill:** [Alloy Expanding for New Hardware](grafana-alloy-network-dashboard-expand-hardware.md)

**Do not use the ktranslate skills** (`grafana-network-dashboard-design-patterns.md` / expand-hardware) on these boards. Those assume `kentik_snmp_*`, delta-gauge `* 8 / 60`, `tags_snmp_group`, and raw BGP SNMP in Mimir.

**Portability:** Assumes Alloy SNMP scrape (`snmp_*`, `job="alloy-snmp"`), optional Alloy flow (`alloy_network_io_by_flow_*`), and topology-exporter graph metrics. Does not assume hostnames, panel IDs, dashboard UIDs, or vendor MIBs unless labeled as examples.

---

## Conventions used in this document

| Symbol | Meaning |
|--------|---------|
| `$device` | Your dashboard's **single-device** template variable (PromQL label is always `device_name`; some Alloy boards name the variable `$instance`) |
| `$interface` | Interface selector (prefer `if_interface_name`; fall back to `ifName` if that is what the series carries) |
| `$datasource` | Prometheus datasource variable — never hardcode datasource UIDs |
| `$snmp_group` | Site / scrape-group filter. PromQL label is **`snmp_group`**, not `tags_snmp_group` |

Replace `$device` with whatever the import uses (`$instance`, `$device_name`, etc.).

---

## Alloy data model (PromQL)

Alloy SNMP interface metrics are **Prometheus counters**. ktranslate SNMP interface metrics are **delta gauges**. Do not mix the recipes.

| Metric family | Recommended | Avoid |
|---------------|-------------|-------|
| Interface octets (bps) | `rate(snmp_ifHCInOctets{job="alloy-snmp", device_name=~"$device"}[$__rate_interval]) * 8` | `(snmp_ifHCInOctets) * 8 / 60`; `rate(kentik_snmp_ifHC*Octets[...])` |
| Interface errors/s | `rate(snmp_ifInErrors{job="alloy-snmp", device_name=~"$device"}[$__rate_interval])` | `(snmp_ifInErrors) / 60` |
| Memory % | `device:snmp_MemoryUtilization:percent` (recording rule) | Hand-rolled `Used / (Used + Available)` in the panel |
| CPU % | `snmp_CPU{job="alloy-snmp"}` | `snmp_CPULoad` (Unix load average, not %) |
| Flow bytes | `rate(alloy_network_io_by_flow_bytes{integration="alloy-netflow"}[$__rate_interval])` | `max_over_time(network_io_by_flow_bytes[...])` (ktranslate rollups) |
| Routing / LLDP | `network_topology_edge_info{tester_id="network-lab"}` | `snmp_tBgpPeerNgConnState`, raw topology-tier walks |
| Traps (A3/A4) | Loki `{service_name="alloy-snmptrap"}`; group by `trap_oid` | `eventType="KSnmpTrap"`, CHF `kkc_snmp_traps` |
| Syslog (A3/A4) | Loki `{service_name="alloy-syslog"}` (`severity` is a label) | `\| json` on syslog; `instrumentation_name="ktranslate-syslog"` |

Recording-rule shortcuts (when provisioned): `if:snmp_ifHCInOctets:rate5m * 8` for bps, `if:snmp_ifInErrors:rate5m`, `if:snmp_IfInUtilization:percent`. Prefer those on fleet boards; live `rate()` is fine on Details.

**Fleet vs drill-down filters:**

- **Device Details** (single device): `device_name=~"$device"` and usually `job="alloy-snmp"`. Do not add `provider`.
- **Device Summary** (fleet): `snmp_group=~"$snmp_group"` alongside `device_name`. Not `tags_snmp_group`.

**Stale series:** after collector moves or IP changes, old series may linger. Use `max by (device_name)(...)` on drill-down scalars to collapse duplicates.

**Scrape tiers:** hot (60s: octets, oper, CPU/mem) is always in Mimir. Cold (names, packet counters, errors, discards, IP inventory) is slower. Topology walks **do not land in Mimir** — they go to topology-exporter.

---

## Connections tab (topology-exporter)

Raw topology SNMP (`snmp_tBgpPeerNgConnState`, LLDP neighbor tables, CDP) is **intentionally absent** from Prometheus. Connections / Observed Topology panels query the reconciled graph:

```promql
network_topology_edge_info{tester_id="network-lab", discovery_proto="bgp"}
network_topology_edge_info{tester_id="network-lab", discovery_proto="lldp"}
```

- Device identity on edges is `src_device` / `dst_device` (and `src_interface` / `dst_interface` when named).
- An unavailable BGP session **disappears** from the graph; that is current state, not a failed PromQL.
- `network_topology_graph_stale` distinguishes an ingest/exporter hold from an empty fabric.
- Gate `has_bgp` (and similar) on `network_topology_edge_info` with `src_device=~"$device"`, **not** on `snmp_tBgp*`.
- Lab event loops may bounce a leaf port on a timer; a brief unidirectional BGP drop is generated telemetry.

Patch source for the lab A3/A4 tabs: `python3 local/scripts/patch-alloy-topology-connections.py`.

---

## Layout structure

- **Root:** `TabsLayout`
- **Typical tabs:** Overview, Interfaces, Hardware Sensors, Connections (Observed Topology), Telemetry / Events (your import may differ)
- **Within each tab:** `RowsLayout` → `GridLayout` rows
- **Grid width:** 24 columns

---

## Naming conventions

### Row vs panel titles

- **Row header** = section topic (e.g. "CPU Utilization", "Memory")
- **Stat** = current value — may share the row name
- **Timeseries** = distinct title — append **" Over Time"** or describe breakdown
- **Table** = descriptive suffix — "Peer Status", "Sensor Data", not the same as the row title

---

## Conditional rows (`has_*` variables)

Hidden QueryVariables gate rows. Non-empty → show row; empty → hide row.

**Cost:** every `has_*` is a Prom `label_values` on dashboard open. A **miss** is slower than a hit. Keep capability-level gates only; do not add one `has_*` per vendor table or per topology MIB.

```
kind: QueryVariable
name: has_<feature>
hide: hideVariable
refresh: onTimeRangeChanged
query:
  group: prometheus
  qryType: 1   # LabelValues
  label: device_name
  metric: <gate metric — must exist in Mimir when the row should show>
  labelFilters: [{ device_name =~ "$device" }]
```

For topology-backed rows, use `metric: network_topology_edge_info` and filter `src_device` + `discovery_proto` + `tester_id`.

**Row visibility:**

```
visibility: show
condition: and
items: [{ kind: ConditionalRenderingVariable, variable: "has_<feature>", operator: "matches", value: ".+" }]
```

### Metric-family rules

| Gate | Gate metric family |
|------|-------------------|
| Most SNMP rows | `snmp_*` that panels query, plus `job="alloy-snmp"` when the stack also has ktranslate |
| Memory | `device:snmp_MemoryUtilization:percent` if rules are installed; else the native used/free series the panels use |
| Routing / LLDP | `network_topology_edge_info` — never topology-tier `snmp_*` |
| Ping | Alloy fork has **no** `kentik_ping_*`. Only add `has_ping` if this stack actually scrapes a ping integration |

### Dead gate metrics (common import bug)

The gate `metric` must exist **in Mimir** for the device and match what panels query.

| Symptom | Typical cause | Fix |
|---------|---------------|-----|
| Connections row empty | Gate or panels still on `snmp_tBgpPeerNgConnState` | Point both at `network_topology_edge_info` |
| Memory row hidden | Gate uses a kentik name or unused `hrStorage*` | Point gate at the recording rule or the `snmp_*` the panel uses |
| Row visible but empty | Gate OK, panel still uses `kentik_snmp_*` or `* 8 / 60` | Align panel PromQL to Alloy |
| Inventory "No data" | Bare `count(...)` | `count(...) OR vector(0)` |

Verify with Explore: `count(<gate_metric>{device_name="<device>"})`.

---

## Dashboard variable stack (typical)

```
$datasource  →  $snmp_group  →  $device  →  $interface (multi, includeAll)
```

- All queries use `$datasource` — no hardcoded UID.
- Base SNMP filter: `job="alloy-snmp", device_name=~"$device"`.
- Fleet filter: `snmp_group=~"$snmp_group"`.
- Interface panels: `if_interface_name=~"$interface"` (or `ifName`) — do not hardcode `".*"`.

---

## Timeseries panel config

**Width threshold: 17 columns** (~70% of 24-col grid).

### Wide (≥ 17 cols)

```
lineWidth: 2
tooltip: { mode: multi }
legend: { displayMode: table, placement: right, calcs: [min, mean, max] }
```

### Compact (< 17 cols)

In/Out pairs (12+12):

```
lineWidth: 1
tooltip: { mode: single }
legend: { calcs: [] }
```

Shared defaults: `palette-classic`, `min: 0`, `fillOpacity: 10`, `spanNulls: 600000`, `stacking.mode: none`.

### Flow tab exception

Stacked **area** for NetFlow/sFlow — intentional deviation:

```
lineWidth: 0
fillOpacity: 80
spanNulls: false
legend: { calcs: [max] }
```

Do not normalize flow panels to standard line style.

---

## Panel pair (stat + timeseries)

| Width | Type | Role |
|-------|------|------|
| 7 | stat | Current KPI |
| 17 | timeseries | Trend |

- **Stats:** instant queries, except Δ24h stats (`instant: false`; current minus `offset 24h`).
- **Timeseries:** range queries (`instant: false`).
- Fleet count stats: `count(...) OR vector(0)`.

---

## In/Out split (interface metrics)

Two panels — never combined:

```
Left:  x:0,  width:12 — title suffix " In"
Right: x:12, width:12 — title suffix " Out"
```

Traffic, utilization, errors, drops, error %, unicast/broadcast/multicast, queue drops.

---

## Table panels

- **Width:** 24 cols default
- **Query:** `instant: true`, `range: false`
- **No** `format: table` on Prometheus targets — use transformations
- **One query per panel** unless using SQL Expression to JOIN frames

### Column cleanup (`organize`)

Always hide collector/metadata labels:

`Time`, `Index`, `__name__`, `device_name`, `job`, `instance`, `instrumentation_name`, `service_name`, `src_addr`, `snmp_group` (when already selected), topology `tester_id` when the board is single-lab

Prefer **string state labels** on series when they exist alongside numeric values.

---

## Series-to-table: `labelsToFields → merge → organize`

Required for multi-series state tables (sensors, fans, PSU, NTP, IP inventory, topology edges).

1. **labelsToFields** — labels become columns
2. **merge** — **required**; without it only the first series row appears
3. **organize** — exclude noise + rename; exclude leftover numeric metric column

**Symptoms:**

| Symptom | Missing step |
|---------|----------------|
| Only 1 row | `merge` |
| `metric{label=...}` header | `labelsToFields` |
| Wrong colors on state | override targets string column, not numeric `Value` |

---

## Dynamic state-as-label metrics

Some vendor modules encode state as a numeric value **and** a string label. State transitions create **new series**; stale series linger → duplicate instant-table rows.

**Dedup:** `topk by (device_name, <entity_key>) (1, <metric>{device_name=~"$device"})` — prefer higher ordinal FSM values when applicable (confirm enum per vendor MIB).

Do not rely on timestamp-based dedup alone — stale and new series often share scrape time.

Topology edges are presence series (`network_topology_edge_info`). Do not treat a missing edge as a stale series; it means the exporter no longer reconciles that adjacency.

---

## Table column naming

- `entity_name` → `Component`; `if_interface_name` / `ifName` → `Interface`
- Topology: `src_device` / `dst_device` → `Source` / `Destination`; `discovery_proto` → `Protocol`; `evidence` → `Evidence`
- `*OperStatus`/`*OperState` → `Oper Status`
- State enums → `State`
- Units in headers: `Temp (°C)`, `Speed (RPM)`, `RTT (ms)`

After `labelsToFields`, exclude the leftover numeric metric column.

---

## Status column colors

1. Value mappings with semantic colors
2. `custom.cellOptions: { type: "color-background" }`

Multi-query SQL tables: use **`byFrameRefID`** overrides — not `defaults.mappings`.

Observed count stats (BGP/LLDP session counts): **0 red / ≥1 green**. Do not invert (0 green looks healthy when the graph is empty).

---

## PromQL quick reference

```promql
# Device-level scalars
max by (device_name) (snmp_CPU{job="alloy-snmp", device_name=~"$device"})
max by (device_name) (device:snmp_MemoryUtilization:percent{device_name=~"$device"})

# Interface-level (counters)
sum by (if_interface_name) (
  rate(snmp_ifHCInOctets{job="alloy-snmp", device_name=~"$device", if_interface_name=~"$interface"}[$__rate_interval]) * 8
)

# Observed routing / LLDP (not raw SNMP topology)
count(
  network_topology_edge_info{tester_id="network-lab", discovery_proto="bgp", src_device=~"$device"}
) OR vector(0)

# Alloy-native flow
rate(alloy_network_io_by_flow_bytes{integration="alloy-netflow"}[$__rate_interval])
```

---

## Safe dashboard edits (v2 TabsLayout)

- **GET** full live manifest → edit `spec.elements` / layout → **PUT** with `resourceVersion`
- **Do not** `POST /api/dashboards/db` on tabbed v2 boards (flattens tabs)
- Lab UIDs: A3 Device Summary `ma8p7dn` (marcnetterfield1) / cloned copy in folder `fb9d2s`; A4 `alloy-device-details`. Drill-down stays on Alloy UIDs, not `ktranslate-device-details`.

---

## See also

- [Alloy Expanding for New Hardware](grafana-alloy-network-dashboard-expand-hardware.md)
- [Skills README](grafana-network-dashboard-skills-README.md)
- [Alloy network fork](alloy-network-fork.md) — scrape tiers, recording rules, topology contract
- ktranslate twin (do not mix): [Design Patterns](grafana-network-dashboard-design-patterns.md)
