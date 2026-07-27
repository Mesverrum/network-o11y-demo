# Grafana dashboard playbook — ktranslate / Network Lab

Operators and agents patching **Grafana Cloud v2** dashboards (especially tabbed ktranslate boards). Read this before any dashboard write.

**Related:** [`AGENTS.md`](../AGENTS.md) → *Grafana dashboard updates* · [`grafana-network-dashboard-skills-README.md`](grafana-network-dashboard-skills-README.md) (portable Assistant skills) · [`local/docs/dashboard-query-lessons.md`](../local/docs/dashboard-query-lessons.md) (lab PromQL notes) · scripts under `local/scripts/`.

---

## Rule zero: pull live before you edit

**Never** start from a stale file in `local/.dash-payloads/`, an old patch script output, or repo-exported JSON. The live stack (often after Grafana Assistant fixes) is the source of truth.

```bash
# 1) Pull (note generation)
gcx --context <stack> --agent dashboards get <uid> -o json > /tmp/dash-live.json
# or HTTP v2 GET with GRAFANA_URL + GRAFANA_TOKEN (see § HTTP v2 API)

# 2) Edit pulled manifest only (spec.elements[*] for TabsLayout)

# 3) PUT with resourceVersion from GET

# 4) Verify layout kind unchanged
jq '.spec.layout.kind' /tmp/dash-live.json

# 5) Before updating a patch script, diff live vs local payload
python3 local/scripts/_compare-dashboard-live.py
```

Patch scripts that already GET live on each run (e.g. `patch-device-summary-tabs.py`) are OK for **push** — but when **changing the script's hardcoded queries**, pull live first and merge operator patterns from `dashboard-query-lessons.md`.

---

## The one rule

**Never use `POST /api/dashboards/db` or legacy panel-tree patches on v2 `TabsLayout` dashboards.** It flattens tabs into one long scroll. We lost Commvault Device Details tabs this way once; restore from **Dashboard settings → Versions** if it happens again.

---

## Safe write paths

| Path | TabsLayout-safe? | Notes |
|------|------------------|-------|
| `gcx dashboards get` → edit `spec` → `gcx dashboards update` | **Yes** | Preferred when `gcx --context <stack>` is configured |
| v2 HTTP API `GET`/`PUT` on `dashboard.grafana.app/v2` | **Yes** | Use `GRAFANA_URL` + `GRAFANA_TOKEN` from `local/.env` when gcx context is missing (common on WSL) |
| `local/scripts/patch-iface-bps-fleet.py` | **Yes** | Fleet BPS rewrites via gcx v2 |
| `local/scripts/patch-flow-dashboard-sections.py` | **Yes** | Flow Summary rows (country, transport) via HTTP v2 |
| `gcx assistant dashboard` / `gcx assistant prompt` | **Yes** (review in UI) | OAuth only; best for new panels/rows — then `download-flow-dashboard.py` |
| `local/scripts/reorganize-marcnetterfield-dashboards.py` | **Yes** | Pull / renumber / friendly UID migration |
| `POST /api/dashboards/db` | **No** on tabbed v2 | Classic import only; never re-save tabbed boards |
| `local/scripts/patch-iface-bps-60s.py` (legacy HTTP) | **No** | `rewrite_expr()` helper only |
| `local/scripts/audit-commvault-bps.py` | **No** | Deprecated — strips tabs |

---

## v2 manifest anatomy

v2 dashboards store layout in **`spec.layout`**, panels in **`spec.elements`** (keyed map), not top-level `panels[]`.

| `spec.layout.kind` | Used by |
|--------------------|---------|
| `TabsLayout` | Device Details, Device Summary, Health |
| `RowsLayout` | Flow Summary |
| `GridLayout` | Architecture |

**Edit queries in:** `spec.elements[<key>].spec.data.spec.queries[*].spec.query.spec.expr`  
**Edit layout positions in:** `spec.layout.spec.tabs[*].layout.spec.items[*].spec` (nested grids per tab)  
**Do not** reorder tabs or rewrite `spec.layout` structure unless you know exactly what you are doing.

**PromQL / UI pitfalls (agent):** see [`local/docs/dashboard-query-lessons.md`](../local/docs/dashboard-query-lessons.md) — diff script `local/scripts/_compare-dashboard-live.py`. Common mistakes: `rate()` on ktranslate SNMP gauges, manual memory ratios, CHF metrics for trap/syslog volume (use Loki), `instant` on timeseries.

---

## Canonical patch workflow (gcx)

```bash
# 1) Read full manifest — note layout.kind
gcx --context <stack> --agent dashboards get <uid> -o json > /tmp/dash.json

# 2) Patch spec.elements[*] only (queries, descriptions, heights)
#    Interface bps (ktranslate delta gauges, 60s poll):
#      rate(kentik_snmp_ifHCInOctets[$__rate_interval]) * 8
#    → (kentik_snmp_ifHCInOctets{...}) * 8 / 60

# 3) Write back
gcx --context <stack> --agent dashboards update <uid> -f /tmp/dash.json

# 4) Verify tabs survived
gcx --context <stack> --agent dashboards get <uid> -o json \
  | jq '.spec.layout.kind'    # expect "TabsLayout"
```

---

## HTTP v2 API (no gcx context)

When `gcx --context marcnetterfield1` is not configured, use `local/.env`:

```bash
# GET
curl -s -H "Authorization: Bearer $GRAFANA_TOKEN" \
  "$GRAFANA_URL/apis/dashboard.grafana.app/v2/namespaces/stacks-1061129/dashboards/<uid>"

# PUT (include metadata.resourceVersion from GET)
```

Namespace `stacks-1061129` is marcnetterfield1; other stacks differ — read `metadata.namespace` from an existing GET.

**Helper scripts using HTTP v2:** `reorganize-marcnetterfield-dashboards.py`, `_sync-arch-panels-http.py` (architecture text panels).

---

## UID migration gotchas

Grafana v2 **cannot rename** a dashboard UID in place. A `PUT` to `/dashboards/old-uid` with `metadata.name: new-uid` returns **400** (*name does not match URL*).

**Safe migration (old random UID → friendly UID):**

1. `GET` live manifest from old UID (source of truth).
2. `POST` create at new UID with:
   - `metadata.name` = new slug
   - **No** `metadata.resourceVersion` on create
   - **No** `metadata.labels.grafana.app/deprecatedInternalID` (that ID is bound to the old UID; reusing it causes **409 Conflict**)
3. `PUT` updates to existing friendly UID **do** copy `deprecatedInternalID` from the GET response.
4. `DELETE` legacy UID after verifying the new dashboard in the UI.

Automated: `python3 local/scripts/reorganize-marcnetterfield-dashboards.py pull|plan|apply --delete-legacy`

---

## marcnetterfield1 ktranslate set (Network Lab)

Live stack is source of truth. Canonical JSON exports: `local/.dash-payloads/marcnetterfield-live/` (gitignored — pull locally).

| # | Title | UID | Layout | Gen (2026-07-26) |
|---|-------|-----|--------|------------------|
| 00 | Ktranslate Architecture | `ktranslate-architecture` | GridLayout | 2 |
| 01 | Ktranslate Health | `ktranslate-health` | TabsLayout | 3 |
| 02 | Network Flow Summary | `ktranslate-flow-summary` | RowsLayout | 14 |
| 03 | Network Device Summary | `ktranslate-device-summary` | TabsLayout | 34 |
| 04 | Network Device Details | `ktranslate-device-details` | TabsLayout | 13 |

```bash
cd local   # or repo root with local/scripts/...

# Pull all five + refresh agent docs (recommended after UI/Assistant edits)
python3 scripts/sync-ktranslate-dashboards-live.py --pull
# → .dash-payloads/marcnetterfield-live/*.json (manifests)
# → local/docs/ktranslate-dashboard-live-snapshot.md (inventory)
# → local/docs/dashboard-query-lessons.md (operator patterns)

# Pull manifests only (no doc regen)
python3 scripts/reorganize-marcnetterfield-dashboards.py pull
python3 scripts/reorganize-marcnetterfield-dashboards.py plan

# Push (dry-run stages only)
python3 scripts/reorganize-marcnetterfield-dashboards.py apply --dry-run

# Push + remove legacy random UIDs
python3 scripts/reorganize-marcnetterfield-dashboards.py apply --delete-legacy
```

**Verify tabs after any change:**

```bash
python3 scripts/_verify-live-reorg.py   # layout kind + tab/row counts
python3 scripts/_verify-reorg-tabs.py # compare live pull vs staged
```

**Sync architecture markdown panels** (dashboard links table, rollout checklist):

```bash
python3 scripts/build-ktrans-arch-dashboard.py --context marcnetterfield1
# or without gcx:
python3 scripts/_sync-arch-panels-http.py
```

**Ktranslate Health (CHF / OTLP):** retarget NR `svc`/`host` labels to `service_name`, fix `netflow_flows`, add flow/syslog spotlight panels:

```bash
python3 local/scripts/patch-ktranslate-health-dashboard.py          # HTTP via local/.env
python3 local/scripts/patch-ktranslate-health-dashboard.py --dry-run
```

Dashboard UID: `ktranslate-health`. Staged output: `local/.dash-payloads/ktranslate-health-otlp-patched.json`.

---

## Legends — do not break them

Common regression: blank `legendFormat` on multi-query panels → all series show as `{}` or duplicate labels.

| Situation | Action |
|-----------|--------|
| Panel has explicit `legendFormat` (`{{if_interface_name}}`, `Established`, `__auto`) | **Leave unchanged** |
| Single-query panel with empty legend | **Leave unchanged** (Grafana auto-label is fine) |
| Multi-query panel, 2+ queries with empty `legendFormat` | Fill heuristically: `{{device_name}}`, `{{device_name}} {{if_Description}}`, `{{service_name}}` |

`reorganize-marcnetterfield-dashboards.py` → `preserve_legends()` only patches the multi-query / all-empty case.

---

## Panel heights — avoid scroll and dead space

Grid height is in layout item `spec.height` (Grafana grid units).

| Panel type | Target height | Rule |
|------------|---------------|------|
| `text` / markdown | ~10 | Shrink if >12 (half-page whitespace) |
| `timeseries`, `table`, `barchart` | ~10 | Bump if <8 (cramped, forces scroll) |
| `stat` | ~6 | Keep compact |

Tune **nested tab grids** only — never change `TabsLayout` tab order or tab count. Goal: readable on a normal laptop viewport without scrolling the whole dashboard; no single panel eating half the viewport.

---

## Fleet BPS patch

ktranslate exports interface octets as **delta gauges** (60s poll), not counters — `rate()` under-reports.

```bash
python3 local/scripts/patch-iface-bps-fleet.py <gcx-context> --dry-run
python3 local/scripts/patch-iface-bps-fleet.py marcnetterfield1 ktranslate-device-summary ktranslate-device-details
```

Report: `local/.dash-payloads/bps-v2-patch-report-<context>.json`

---

## Post-patch checklist

1. `spec.layout.kind` unchanged (`TabsLayout` / `RowsLayout` / `GridLayout`).
2. `metadata.generation` incremented (update actually landed).
3. **UI spot-check:** Device Details still shows all tabs (Overview, Interfaces, BGP, …), not one flattened page.
4. **Legends:** multi-series panels have distinct, readable legend labels.
5. **Heights:** no obvious half-page empty markdown blocks; charts tall enough to read without dashboard-level scroll on a 1080p display.
6. **BPS panels:** no remaining `rate(kentik_snmp_ifHCInOctets` / `ifHCOutOctets` in the manifest.

---

## Local lab dashboards (different UIDs)

| UID | Title |
|-----|-------|
| `lab-ktranslate-flow` | Flow Summary (local lab) |
| `lab-topology-graph` | Network Topology |
| `lab-network-join-demo` | Network join demo |

Import/rebuild scripts live under `local/scripts/build-*` and `import-*`. Same v2 rules apply if the imported board uses `TabsLayout`.

---

## MCP note

Use Grafana MCP for **read-only** verification (`get_dashboard_summary`, PromQL, deeplinks). MCP may point at a different stack than `local/.env` — always confirm stack. For writes on tabbed v2 boards, use **gcx v2** or the HTTP API until you have confirmed MCP `patch_dashboard` preserves `TabsLayout`.

---

## Grafana Assistant (`gcx assistant`)

The **GUI Assistant** and **`gcx assistant`** are the same product family. Prefer them for **new panels, rows, transforms, and SQL joins** — they match live Prometheus and produce manifests that look like the rest of an Assistant-built board.

| Command | Use when |
|---------|----------|
| `gcx assistant dashboard "…"` | Net-new dashboard or major row (routes to `grafana_dashboarding` agent) |
| `gcx assistant prompt "…"` | General edits, investigations, follow-ups (`--continue` / `--context-id`) |
| `gcx dashboards get` / `update` | Small, repeatable patches (BPS rewrite, scripted row insert) |
| Grafana UI Assistant | Same as above; best when you can review visually before save |

**Auth:** `gcx assistant` requires **OAuth** (`gcx login` browser flow). **Service-account tokens** in `local/.env` work for `gcx dashboards` and HTTP v2 — not for `gcx assistant`.

```bash
gcx login
gcx assistant dashboard "On UID ktranslate-flow-summary, add a country breakdown row below Geo Maps. Use network_io_by_flow_bytes; match existing geomap variable filters; preserve RowsLayout."
gcx assistant prompt "Continue: add drill-down links on the country table" --continue
```

**When to use which:**

| Task | Prefer |
|------|--------|
| Design / layout / transforms | GUI Assistant or `gcx assistant dashboard` |
| Fleet query rewrite (same expr everywhere) | `patch-iface-bps-fleet.py` |
| Pull live manifest to git | `download-flow-dashboard.py` or `reorganize-marcnetterfield-dashboards.py pull` |
| Idempotent row from a script | `patch-flow-dashboard-sections.py` (then UI spot-check) |

After Assistant edits: **pull** the manifest back into the repo so agents do not fight live state:

```bash
python3 local/scripts/sync-ktranslate-dashboards-live.py --pull   # all 00–04 + agent docs
# or flow only:
python3 local/scripts/download-flow-dashboard.py   # → .dash-payloads/marcnetterfield-live/ktranslate-flow-summary.json
```

---

## Device Details dashboard (`ktranslate-device-details`, TabsLayout)

Live export: `local/.dash-payloads/marcnetterfield-live/ktranslate-device-details.json` (gen **13** as of 2026-07-26).

**Design patterns (portable Assistant skill):** [`docs/grafana-network-dashboard-design-patterns.md`](../docs/grafana-network-dashboard-design-patterns.md) — layout, `has_*` gates, table transforms, naming. Import guide: [`docs/grafana-network-dashboard-skills-README.md`](../docs/grafana-network-dashboard-skills-README.md).

**Expanding for new hardware/vendor:** [`docs/grafana-network-dashboard-expand-hardware.md`](../docs/grafana-network-dashboard-expand-hardware.md).

**Variables:** `provider` → `instance` (device name). Do not confuse with Device Summary's `device_name`.

| Pattern | Operator edit (live) |
|---------|----------------------|
| Per-device SNMP | `max by(device_name)(kentik_snmp_*{device_name=~"$instance"})` — collapses ghost `src_addr` / old poller series |
| Interface bps | `clamp_max(topk(25, max by(if_interface_name)((kentik_snmp_ifHCInOctets{...}) * 8 / 60)), 100e9)` |
| Memory % | `kentik_snmp_MemoryUtilization{device_name=~"$instance"}` |
| Memory bytes chart | `MemoryUsed` / `MemoryFree` with `max by(device_name)` and `* 1024` |
| Ping | `kentik_ping_*{device_name=~"$instance"}` |
| Collection age | `time() - max_over_time(timestamp(kentik_ping_AvgRttMs{...})[24h:1m])` |
| Flow tab | `max_over_time(network_io_by_flow_bytes{device_name=~"$instance",...})` |

**Caveat:** hidden `has_memory` gate still probes `hrStorageUsedPercent` (0 on SRL). Memory **panels** use `MemoryUtilization`; section visibility may not match Nokia profile.

---

## Device Summary dashboard (`ktranslate-device-summary`, TabsLayout)

Live export: `local/.dash-payloads/marcnetterfield-live/ktranslate-device-summary.json` (gen **34** as of 2026-07-26).

**Tabs:** Overview · Traffic · Resources · Interfaces · Routing · Hardware · Events

| Tab | Operator focus |
|-----|----------------|
| Overview | Fleet status table, headline stats, **fleet breakdown** (provider/model/poller), **active conditions**, collection health |
| Traffic | Stacked bps by device (ktranslate delta gauges `* 8 / 60`) + WAN ifAlias row |
| Resources | CPU + memory utilization |
| Interfaces | Link state, errors, utilization hotspots |
| Routing | BGP established/down (compact table: device, peer group, AS, state) |
| Hardware | Fan/PSU stats + issue tables, chassis FRUs, temperature |
| Events | **Syslog/trap volume over time**, trap breakdown, syslog stream |

```bash
python3 local/scripts/provision-network-alerts.py          # create/update 12 rules
python3 local/scripts/provision-network-alerts.py --dry-run
make -C local network-alerts
python3 local/scripts/patch-device-summary-tabs.py          # tabs + ALERTS panels
python3 local/scripts/patch-device-summary-tabs.py --dry-run
python3 local/scripts/apply-wan-ifalias.py                  # live lab: WAN ifAlias on 4 ifaces
python3 local/scripts/snmp-walk-srl-memory.py               # verify memory OIDs + ifAlias
python3 local/scripts/_map-device-summary-layout.py       # tab/row inventory
```

### Network alert rules (`network-lab` folder)

Provisioned by `local/scripts/provision-network-alerts.py` into rule group **Network Lab / ktranslate**.
All rules carry `category=network` and `source=ktranslate` for dashboard filtering.

| Rule | Severity | `for` | Domain |
|------|----------|-------|--------|
| BGP session not established | warning | 5m | routing |
| SNMP polling unhealthy | critical | 10m | collection |
| Interface admin-up oper-down | warning | 5m | interfaces |
| High interface error rate | warning | 10m | interfaces |
| High device CPU | warning | 15m | resources |
| High device memory | warning | 15m | resources |
| Chassis fan not in service | critical | 2m | hardware |
| Power supply failed or degraded | critical | 2m | hardware |
| Hardware FRU not in service | critical | 5m | hardware |
| High chassis temperature | warning | 10m | hardware |
| SNMP collector heartbeat missing | critical | 5m | collection |
| Elevated SNMP trap rate | info | 5m | events |

Fixture export: `local/fixtures/network-alert-rules.json`. Notifications use the stack default policy
(`grafana-default-email` unless you add routing rules).

Dashboard panels **Firing Network Alerts** / **Active Network Alerts** query:
`ALERTS{alertstate="firing", category="network"}` (populates after rules pass their `for` window).

**Memory:** profile tags `MemoryUsed` + `MemoryFree` (SRL `sgiKbMemoryAvailable` → `MemoryFree` tag).
ktranslate auto-exports `kentik_snmp_MemoryUtilization` — use that in dashboards/alerts, not a manual formula.

**WAN traffic:** filter `if_Alias=~".*WAN.*"` (SRL maps `interface description` → SNMP ifAlias).  
Lab: `leaf1/leaf2 ethernet-1/49`, `spine1 ethernet-1/1` + `ethernet-1/2` (`apply-wan-ifalias.py`).

**Traps:** CHF `kentik_ktranslate_chf_kkc_snmp_traps`; logs `{service_name=~"ktranslate.*"} |= "KSnmpTrap"`.  
Generate: `make -C local traps` / `events-loop`.

**BGP/HW tables:** keep only operator columns (hide ktranslate/SNMP metadata labels). BGP state uses
`tBgpPeerNgConnState` string label; hardware uses `tmnxHwOperState`, `tmnxPhysChassisFanOperStatus`,
`tmnxPhysChassisPMOutputStatus` (Nokia SRL TIMETRA-CHASSIS-MIB).

**Fleet breakdown:** `provider`, `tags_kentik_model`, `service_name` (poller) from `kentik_snmp_if_OperStatus`.

**Grafana alerts:** `python3 local/scripts/provision-network-alerts.py` — 12 rules in folder `network-lab`,
group `Network Lab / ktranslate`, label `category=network`. Dashboard uses `ALERTS{alertstate="firing",category="network"}`.

Drill-down links target **04. Network Device Details** (`ktranslate-device-details`, `var-instance`).

---

## Flow Summary dashboard (`ktranslate-flow-summary`, RowsLayout)

Live export: `local/.dash-payloads/marcnetterfield-live/ktranslate-flow-summary.json`.  
**Rows** (not tabs): Devices · Applications · Conversations · Sankey · Geo Maps · Country Breakdown · Transport & Ports.

### Scripts

| Script | Purpose |
|--------|---------|
| `download-flow-dashboard.py` | Pull live v2 manifest (gen + `resourceVersion`) |
| `patch-ktranslate-flow-dashboard.py` | Hostname labels in group-by + legends (`src_host`/`dst_host` **with** IPs — no `label_replace`) |
| `patch-flow-dashboard-sections.py` | Country + transport rows; `--fix-country` refreshes bad country queries |
| `verify-flow-countries.py` | `count by (network_peer_country)` for public peers |
| `_audit-flow-data.py` / `_inspect-flow-labels.py` | Label cardinality and sample tuples (agent debugging) |
| `_summarize-flow-dashboard.py` | Row/panel inventory from manifest |

### Dashboard variables (use in every flow panel)

`$device_name`, `$src_addr`, `$dst_addr`, `$application`, `$src_host`, `$dst_host` — all pipe-multi (`${var:pipe}`).

### PromQL rules (flow rollups)

| Do | Don't |
|----|-------|
| `max_over_time(network_io_by_flow_bytes{…}[$__range])` for totals | `rate(network_io_by_flow_bytes[…])` — ktranslate exports **delta gauges**, not counters |
| `max_over_time(…[$__rate_interval])` for timeseries steps | `label_replace` **inside** `max_over_time(…)` — invalid PromQL |
| `label_replace` **after** `max_over_time` if you must coalesce labels | Duplicate the same label in one selector (e.g. two `network_local_address=~`) |
| Group by **both** IP and hostname: `network_local_address, src_host` | `label_replace` coalesce that hides IP — keep IP for investigation |
| Geomap / country: `network_peer_country!~"Private IP\|undefined"` | Hardcode `172.20.20.*` **and** `${src_addr:pipe}` — breaks variables and geomap parity |

**Throughput (bps):** `sum(network_io_by_flow_bytes) * 8 / 60` (60s rollup period).

### Flow metric labels (Alloy → Prometheus)

Primary metric: **`network_io_by_flow_bytes`** (rollup from `kentik.rollup.bytes_by_flow`).

| Label | Source | Dashboard use |
|-------|--------|----------------|
| `device_name` | softflowd exporter / catalog | Exporter filter; only `client1.clab` / `client2.clab` in local lab |
| `network_local_address` / `network_peer_address` | 5-tuple | Variables, drill-down links |
| `src_host` / `dst_host` | ktranslate `--dns` / `flow_dns` | Legends `{{src_host}} ({{network_local_address}})`; `"undefined"` = PTR miss (not empty) |
| `network_peer_country` / `network_local_country` | MaxMind (`src_geo`/`dst_geo` rollups) | Geo Maps; `"Private IP"` for RFC1918 |
| `network_protocol_name` | L7 app ID | Application row |
| `network_transport` | L4 (`TCP`/`UDP`) | Transport & Ports row |
| `network_local_port` / `network_peer_port` | 5-tuple | Top destination ports |
| `integration` | Alloy | `ktranslate-netflow` on rollups (not `service_name`) |

### Traffic planes (local lab)

| Plane | Typical `network_local_address` | Volume | Geomap |
|-------|----------------------------------|--------|--------|
| East-west EVPN | `172.17.0.*` | High (`make traffic`) | Private IP peers — hidden on map |
| North-south (internet) | `172.20.20.*` (client mgmt) | Low | Public `network_peer_country` |

Dual softflowd: **eth0** → mgmt/internet, **eth1** → EVPN. Internet probes: `fixtures/internet-probe-targets.txt` (`make internet-probes`). Verify countries: `make verify-flow-countries`.

### Country row lesson (2026-03)

Country breakdown panels must use the **same selector as Top Flow Peer Locations** (geomap), not a separate hardcoded CIDR. Table = drill-down (`country`, peer IP, `dst_host`); timeseries = `sum by (network_peer_country)` with `[$__rate_interval]`. Row sits **under Geo Maps**.

### RowsLayout edits

Edit `spec.layout.spec.rows[*]` grid items and `spec.elements.panel-*`. Do not flatten to `panels[]`. After patch, confirm `spec.layout.kind` is still `RowsLayout` and `metadata.generation` incremented.
