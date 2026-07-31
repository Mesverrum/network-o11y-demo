# Dashboard query & UI lessons (agent notes)

**Dashboard JSON:** [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) `dashboards/` (set `KTRANS_UPSTREAM` in `local/.env` if not `../KtransToGrafana`). **Live drift check:** `local/.dash-payloads/marcnetterfield-live/` (refreshed 2026-07-31 18:16 UTC). Re-pull: `make -C local dash-live-sync`. Push to stack: `make -C local dash-push`.

Compared prior agent patches vs operator/Assistant edits on all five ktranslate dashboards (00–04).

## Operator patterns — always use these

| Topic | Use | Do not use |
|-------|-----|------------|
| **Memory %** | `kentik_snmp_MemoryUtilization{$sel}` | Manual `MemoryUsed/MemoryAvailable` ratios |
| **Interface bps** | `(kentik_snmp_ifHCInOctets{...}) * 8 / 60` | `rate(kentik_snmp_ifHC*Octets[...])` |
| **Interface errors/s** | `(kentik_snmp_ifInErrors{...}) / 60` | `rate(kentik_snmp_if*Errors[...])` |
| **Flow bytes** | `max_over_time(network_io_by_flow_bytes[...])` | `rate(network_io_by_flow_bytes[...])` |
| **Trap volume** | Loki `{service_name=~"ktranslate.*"} \| json \| eventType="KSnmpTrap"` | `\|= "KSnmpTrap"`, `\|= "trapdata"`, `rate(kentik_ktranslate_chf_kkc_snmp_traps[5m])` |
| **Syslog volume** | Loki `{service_name=~"ktranslate.*"} \| json \| instrumentation_name="ktranslate-syslog"` (+ `severity` for breakdown) | `\|= "ktranslate-syslog"`, keyword regex on message |
| **Internal collector logs** | Loki `{service_name=~"ktranslate.*"} != "{"` (plain-text `ktranslate/<component>` lines) | Mixing with `\| json` trap/syslog panels |
| **CHF metrics** | Collector health / heartbeat only | Device telemetry or event volume |
| **Fleet stats** | `count(...) OR vector(0)` | Bare `count(...)` → "No data" |
| **Stale series** | `max by(device_name)(...)` on device drill-downs | Raw selectors when ghost `src_addr` series exist |
| **SNMP inventory** | `count by (device_name) (kentik_snmp_CPU)` | `kentik_snmp_DeviceMetrics` (AWS path) |
| **Device drill-down** | `/d/ktranslate-device-details?var-instance=${__data.fields.device_name}` | Legacy `magz6qw1` |

## Live stack counts (all dashboards)

- PromQL panel queries: **327**
- Loki queries: **0**
- `MemoryUtilization`: **4** vs manual memory ratios: **1**
- BPS `* 8 / 60`: **16** vs `rate(kentik_snmp_*`: **6**
- Flow `max_over_time`: **31** vs `rate(network_io_by_flow`: **0**
- Loki trap panels: **5** vs CHF trap rate: **0**
- `OR vector(0)` guards: **16**
- `max by(device_name)` collapses: **35**
- Ping (`kentik_ping_*`): **8** panels

## Per-dashboard notes

### 00. Ktranslate Architecture (`ktranslate-architecture`, gen 4)

GridLayout markdown + links. Sync text from `build-ktrans-arch-dashboard.py`; do not flatten to classic panels API.

### 01. Ktranslate Health (`ktranslate-health`, gen 10)

TabsLayout CHF/jchf collector health. Facet by `service_name` (`ktranslate-snmp-*`, `ktranslate-flow-*`, …). `snmp_fail`: **1=healthy**, >1 failure codes. 6h lookback panels can show stale leaf failures after IP recovery.

### 02. Network Flow Summary (`ktranslate-flow-summary`, gen 14)

RowsLayout. Group flows by `src_host`/`dst_host` **with** IPs in legends. Country panels: `network_peer_country!~"Private IP|undefined"`. Use `max_over_time` on `network_io_by_flow_bytes`.

### 03. Network Device Summary (`ktranslate-device-summary`, gen 49)

TabsLayout fleet view. Selector: `provider` + `device_name`. Collection Health uses Loki for traps/syslog, CHF for collector counts. Memory fleet panels use `MemoryUtilization`.

### 04. Network Device Details (`ktranslate-device-details`, gen 19)

TabsLayout per-device drill-down. Variable **`instance`** (= `device_name`), filtered by **`provider`**. Ping uses `kentik_ping_*`. Memory panels query `MemoryUtilization` but `has_memory` gate still checks `hrStorageUsedPercent` (0 on SRL) — memory section visibility can be wrong; prefer `max by(device_name)` on overview queries to avoid ghost `src_addr` series.

## Agent workflow

1. `python3 local/scripts/sync-ktranslate-dashboards-live.py --pull` before editing patch scripts.
2. Edit pulled v2 manifest (`spec.elements` / `spec.layout`) — never `POST /api/dashboards/db` on TabsLayout.
3. Verify `spec.layout.kind` unchanged after PUT.
4. Update this file + `docs/grafana-dashboard-playbook.md` when operator patterns change.

## UI design notes

- **TabsLayout:** keep related panels on one tab; don't duplicate stats on Overview + Resources.
- **Tables:** hide SNMP junk labels (`job`, `mib_name`, `src_addr`, `objectIdentifier`) via transformations.
- **Timeseries:** `instant: false` for trends; stats/gauges use instant snapshots.
- **Δ24h stats:** current expr minus `offset 24h` subquery, both range-capable.
- **Thresholds:** percent panels `min:0,max:100`; bps tables need unit on Value column.
