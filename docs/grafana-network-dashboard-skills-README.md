# Grafana Network Dashboard skills (portable)

Two **paired** skill families for Network Device Details–style boards on Grafana Cloud. Use them as Grafana Cloud Assistant skills, operator runbooks, or agent context.

| Family | Attach to | Design Patterns | Expanding for New Hardware |
|--------|-----------|-----------------|----------------------------|
| **ktranslate** | 00–04 / Network Lab / `ktranslate-*` UIDs | [`grafana-network-dashboard-design-patterns.md`](grafana-network-dashboard-design-patterns.md) | [`grafana-network-dashboard-expand-hardware.md`](grafana-network-dashboard-expand-hardware.md) |
| **Alloy** | A0–A4 / Alloy Network Fork (`fb9d2s` on networko11ydev) | [`grafana-alloy-network-dashboard-design-patterns.md`](grafana-alloy-network-dashboard-design-patterns.md) | [`grafana-alloy-network-dashboard-expand-hardware.md`](grafana-alloy-network-dashboard-expand-hardware.md) |

**Do not attach both families to the same dashboard folder.** The layout rules are the same; the PromQL and gate metrics are not. Mixing them makes Assistant emit `kentik_snmp_*` + `* 8 / 60` on Alloy boards, or `rate(snmp_*)` on ktranslate delta gauges.

---

## Which family?

| Signal | ktranslate skills | Alloy skills |
|--------|-------------------|--------------|
| Collector | ktranslate OTLP | Alloy SNMP / flow / trap / syslog addons |
| SNMP prefix | `kentik_snmp_*`, `kentik_ping_*` | `snmp_*`, `job="alloy-snmp"` |
| Site label | `tags_snmp_group` | `snmp_group` |
| Interface bps | `(ifHCInOctets) * 8 / 60` | `rate(snmp_ifHCInOctets[$__rate_interval]) * 8` |
| Flow | `max_over_time(network_io_by_flow_bytes)` | `rate(alloy_network_io_by_flow_bytes)` |
| Connections / BGP | raw `kentik_snmp_tBgp*` (and siblings) | `network_topology_edge_info{tester_id="network-lab"}` |
| Traps / syslog | Loki `{service_name=~"ktranslate.*"}` | Loki `{service_name="alloy-snmptrap"\|"alloy-syslog"}` |
| Health | CHF / `kentik_snmp_PollingHealth` | `up{job="alloy-snmp"}`, `discovery_snmp_*` |

Layout, `has_*` as a pattern, `labelsToFields → merge → organize`, and v2 GET/PUT are shared. Copy those ideas; do not copy metric names across families.

---

## ktranslate prerequisites

- **Collector:** [ktranslate](https://github.com/kentik/ktranslate) exporting OTLP metrics to Grafana Cloud Prometheus
- **Metric prefixes:** `kentik_snmp_*`, `kentik_ping_*`, `network_io_by_flow*`
- **Dashboard:** Network Device Details style board — **TabsLayout** v2
- **Device identity label:** `device_name`

### ktranslate variable mapping

| Role | Label in PromQL | Common variable names |
|------|-----------------|-------------------------|
| Credential group | `tags_snmp_group` | `$snmp_group` (filters `tags_snmp_group=~"$snmp_group"`) |
| Single device | `device_name` | `$instance`, `$device`, `$device_name` |
| Fleet filter | `device_name` + often `provider` | `$device_name`, `$provider` |
| Interface | `if_interface_name` | `$interface_name`, `$interface` |

### ktranslate PromQL

ktranslate SNMP interface/error metrics are typically **delta gauges**:

| Use | Avoid |
|-----|-------|
| `(kentik_snmp_ifHCInOctets{...}) * 8 / 60` | `rate(kentik_snmp_ifHC*Octets[...])` |
| `(kentik_snmp_ifInErrors{...}) / 60` | `rate(kentik_snmp_if*Errors[...])` |
| `kentik_snmp_MemoryUtilization` | Hand-rolled Used/Available ratios |
| `max_over_time(network_io_by_flow_bytes[...])` | `rate(network_io_by_flow_bytes[...])` |

`rate()` remains appropriate for **true counters** (some firewall/session metrics, CHF totals). Adjust `/ 60` if `poll_time_sec` is not 60.

---

## Alloy prerequisites

- **Collector:** Alloy network fork — SNMP scrape (hot+cold; topology diverted), optional `otelcol.receiver` flow / traps / syslog
- **Metric prefixes:** `snmp_*` (`job="alloy-snmp"`), recording rules `device:snmp_*` / `if:snmp_*`, flow `alloy_network_io_by_flow_*`
- **Topology:** `network_topology_edge_info` / `network_topology_device_info` from topology-exporter — **not** raw `{fingerprint}_topo` walks
- **Dashboard:** A3/A4 style board — **TabsLayout** v2
- **Device identity label:** `device_name` (live `sysName`)

### Alloy variable mapping

| Role | Label in PromQL | Common variable names |
|------|-----------------|-------------------------|
| Site / scrape group | `snmp_group` | `$snmp_group` |
| Single device | `device_name` | `$instance`, `$device` |
| Interface | `if_interface_name` (else `ifName`) | `$interface` |
| Topology device | `src_device` / `dst_device` | same `$device` / `$instance` on Details |

### Alloy PromQL

Alloy SNMP interface metrics are **Prometheus counters**:

| Use | Avoid |
|-----|-------|
| `rate(snmp_ifHCInOctets[$__rate_interval]) * 8` | `(snmp_ifHCInOctets) * 8 / 60` |
| `rate(snmp_ifInErrors[$__rate_interval])` | `/ 60` on Alloy counters |
| `device:snmp_MemoryUtilization:percent` | Panel-side Used/Available hacks |
| `rate(alloy_network_io_by_flow_bytes[$__rate_interval])` | `max_over_time(network_io_by_flow_bytes)` |
| `network_topology_edge_info{tester_id="network-lab"}` | `snmp_tBgpPeerNgConnState` in Mimir |

---

## Importing into Grafana Cloud Assistant

1. Copy the markdown body of each skill file (below the title) into a new **Assistant skill** on your stack.
2. **ktranslate names:** `Network Dashboard — Design Patterns` and `Network Dashboard — Expanding for New Hardware`.
3. **Alloy names:** `Alloy Network Dashboard — Design Patterns` and `Alloy Network Dashboard — Expanding for New Hardware`.
4. Cross-reference within a family only. Scope Alloy skills to the Alloy Network Fork folder; keep ktranslate skills on 00–04.
5. After UI edits: ktranslate → merge into [KtransToGrafana `dashboards/`](https://github.com/Mesverrum/KtransToGrafana/tree/main/dashboards). Alloy → pull live, then update the Alloy patch scripts (`patch-alloy-topology-connections.py`, `patch-alloy-dashboard-skill-findings.py`, clone script) once live matches intent.

Repo operators can upsert the Alloy pair as tenant skills on both configured
stacks (`GRAFANA_*` and `GRAFANA_*_2` in `local/.env`):

```bash
python3 local/scripts/provision-alloy-dashboard-skills.py --dry-run
python3 local/scripts/provision-alloy-dashboard-skills.py
```

The helper updates an existing exact-name match rather than creating duplicates,
keeps both skills visible to Assistant discovery, and verifies them after write.

---

## Safe dashboard edits (v2 TabsLayout)

- **GET** full live manifest → edit `spec.elements` / layout → **PUT** with `resourceVersion`
- **Do not** `POST /api/dashboards/db` on tabbed v2 boards (flattens tabs)

See [`grafana-dashboard-playbook.md`](grafana-dashboard-playbook.md) for UID migration and fleet notes. Alloy scrape tiers and recording rules: [`alloy-network-fork.md`](alloy-network-fork.md).

---

## network-o11y-demo lab (optional)

- ktranslate JSON: [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) `dashboards/` — `make -C local dash-push` / `dash-live-sync`
- Alloy A3/A4 Connections: `python3 local/scripts/patch-alloy-topology-connections.py`
- Alloy skill-audit fixes (both stacks): `python3 local/scripts/patch-alloy-dashboard-skill-findings.py --dry-run`, then without `--dry-run`
- Alloy fork copies: `python3 local/scripts/clone-alloy-folder-networko11ydev.py`
- Alloy PromQL notes: [`docs/alloy-network-fork.md`](alloy-network-fork.md) § Computed metrics
- Operator PromQL (ktranslate): `local/docs/dashboard-query-lessons.md`

Those paths are **not** required on other stacks.
