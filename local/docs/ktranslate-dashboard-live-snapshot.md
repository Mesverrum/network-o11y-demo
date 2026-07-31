# ktranslate dashboards — live snapshot

Pulled from Grafana Cloud (`local/.env`) on **2026-07-31 18:16 UTC**.
Re-pull: `python3 local/scripts/sync-ktranslate-dashboards-live.py --pull`

| # | UID | Layout | Generation | PromQL | Loki |
|---|-----|--------|------------|--------|------|
| 00 | `ktranslate-architecture` | GridLayout | 4 | 0 | 0 |
| 01 | `ktranslate-health` | TabsLayout | 10 | 52 | 0 |
| 02 | `ktranslate-flow-summary` | RowsLayout | 14 | 19 | 0 |
| 03 | `ktranslate-device-summary` | TabsLayout | 49 | 62 | 0 |
| 04 | `ktranslate-device-details` | TabsLayout | 19 | 194 | 0 |

## 00. Ktranslate Architecture (`ktranslate-architecture`)
- **Generation:** 4
- **Layout:** GridLayout

### Pattern counts

| Pattern | Count |
|---------|-------|

### Key variables

- `snmp_group` → label `` on metric ``

## 01. Ktranslate Health (`ktranslate-health`)
- **Generation:** 10
- **Layout:** TabsLayout

### Pattern counts

| Pattern | Count |
|---------|-------|
| bps delta 60 | 1 |

### Key variables

- `snmp_group` → label `` on metric ``
- `service_name` → label `` on metric ``

### Notable queries (sample)

- **Total Upload Errors:** `sum by(deployment_host) (count_over_time({service_name=~"ktranslate.*|integrations/ktranslate-netflow"} |= "failed to upload metrics" [$__range]))`
- **Input Queue Depth by Container:** `kentik_ktranslate_chf_kkc_inputq_len`
- **Output Queue Depth by Container:** `kentik_ktranslate_chf_kkc_outputq_len`
- **JCHF Buffer Depth:** `last_over_time(kentik_ktranslate_chf_kkc_jchfq[$__range])`
- **Syslog Queue Depth:** `last_over_time(kentik_ktranslate_chf_kkc_syslog_queue[$__range])`
- **ResourceExhausted Errors:** `sum by(deployment_host) (count_over_time({service_name=~"ktranslate.*|integrations/ktranslate-netflow"} |= "ResourceExhausted" [$__range]))`
- **Healthcheck Execution Time (mean / p99 / max):** `last_over_time(kentik_ktranslate_chf_kkc_baseserver_healthcheck_execution_time[6h])`
- **Healthcheck Rate by Container:** `rate(kentik_ktranslate_chf_kkc_baseserver_healthcheck_execution_total[$__rate_interval])`
- **SNMP Errors by Device:** `kentik_ktranslate_chf_kkc_snmp_errors`
- **SNMP Poll Health by Device (snmp_fail):** `kentik_ktranslate_chf_kkc_snmp_fail`
- **SNMP Missing Responses by Device:** `kentik_ktranslate_chf_kkc_snmp_missing`
- **Device Metrics Collected by Device:** `kentik_ktranslate_chf_kkc_device_metrics`

## 02. Network Flow Summary (`ktranslate-flow-summary`)
- **Generation:** 14
- **Layout:** RowsLayout

### Pattern counts

| Pattern | Count |
|---------|-------|
| max over time flow | 18 |

### Key variables

- `datasource`
- `device_name` → label `` on metric ``
- `src_addr` → label `` on metric ``
- `dst_addr` → label `` on metric ``
- `application` → label `` on metric ``
- `src_host` → label `` on metric ``
- `dst_host` → label `` on metric ``

### Notable queries (sample)

- **Top Local Addresses:** `topk(20, sum by(network_local_address, src_host) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}",network_local_address=~"${src_addr:pipe}",network_peer_address=~"${dst_addr:`
- **Top Peer Addresses:** `topk(20, sum by(network_peer_address, dst_host) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}",network_local_address=~"${src_addr:pipe}",network_peer_address=~"${dst_addr:p`
- **Flow Exporters:** `sum by(device_name) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}",network_local_address=~"${src_addr:pipe}",network_peer_address=~"${dst_addr:pipe}",src_host=~"${src_host:`
- **Top Flow Peer Locations:** `sum by(network_peer_country) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}",network_local_address=~"${src_addr:pipe}",network_peer_address=~"${dst_addr:pipe}",src_host=~"${`
- **Top Flow Local Locations:** `sum by(network_local_country) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}",network_local_address=~"${src_addr:pipe}",network_peer_address=~"${dst_addr:pipe}",src_host=~"$`
- **Protocol Traffic over Time:** `sum by(network_protocol_name) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}",network_local_address=~"${src_addr:pipe}",network_peer_address=~"${dst_addr:pipe}",src_host=~"$`
- **Total Traffic by Conversation:** `topk(10, sum by(network_local_address, network_peer_address, src_host, dst_host) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}", network_local_address=~"${src_addr:pipe}", `
- **Conversations:** `topk(25, sum by(device_name, network_local_address, network_peer_address, src_host, dst_host, network_protocol_name) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}", network`
- **Protocol Total Bytes:** `sum by(network_protocol_name) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}",network_local_address=~"${src_addr:pipe}",network_peer_address=~"${dst_addr:pipe}",src_host=~"$`
- **Total Traffic by Protocol:** `sum by(network_protocol_name)(max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}", network_local_address=~"${src_addr:pipe}", network_peer_address=~"${dst_addr:pipe}", src_host=~`
- **Conversation Traffic over Time:** `topk(25, sum by(device_name, network_local_address, network_peer_address, src_host, dst_host) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}",network_local_address=~"${src_a`
- **Peer Destinations by Country:** `topk(25, sum by(network_peer_country, network_peer_address, dst_host) (max_over_time(network_io_by_flow_bytes{device_name=~"${device_name:pipe}",network_local_address=~"${src_addr:pipe}",network_peer_`

## 03. Network Device Summary (`ktranslate-device-summary`)
- **Generation:** 49
- **Layout:** TabsLayout

### Pattern counts

| Pattern | Count |
|---------|-------|
| bgp established 6 | 2 |
| bgp established str | 1 |
| bps delta 60 | 9 |
| errors per 60 | 1 |
| loki traps | 2 |
| max by device | 2 |
| memory manual ratio | 1 |
| memory utilization | 2 |
| or vector 0 | 13 |

### Key variables

- `datasource`
- `snmp_group` → label `` on metric ``
- `provider` → label `` on metric ``
- `device_name` → label `` on metric ``

### Notable queries (sample)

- **Unhealthy Pollers:** `count(kentik_snmp_PollingHealth{tags_snmp_group=~"$snmp_group",provider=~"$provider",device_name=~"$device_name"} != 1) OR vector(0)`
- **SNMP Collectors:** `count(count by(service_name) (kentik_ktranslate_chf_kkc_jchfq{service_name=~"ktranslate-snmp.*"})) OR vector(0)`
- **Flow Collectors:** `count(count by(service_name) (kentik_ktranslate_chf_kkc_jchfq{service_name=~"ktranslate-flow.*|ktranslate-sflow.*"})) OR vector(0)`
- **Syslog Collectors:** `count(count by(service_name) (kentik_ktranslate_chf_kkc_jchfq{service_name=~"ktranslate-syslog.*"})) OR vector(0)`
- **Memory by Device:** `sort_desc(max by(device_name, tags_snmp_group) (kentik_snmp_MemoryUtilization{tags_snmp_group=~"$snmp_group",provider=~"$provider",device_name=~"$device_name"}))`
- **Memory Utilization — Top 10:** `topk(10, max by(device_name, tags_snmp_group) (kentik_snmp_MemoryUtilization{tags_snmp_group=~"$snmp_group",provider=~"$provider",device_name=~"$device_name"}))`
- **Top Interface Utilization (bps):** `topk(20, sum by(device_name, if_interface_name, tags_snmp_group) (kentik_snmp_ifHCInOctets{tags_snmp_group=~"$snmp_group",provider=~"$provider",device_name=~"$device_name"} * 8 / 60) + sum by(device_n`
- **BGP Peers Established:** `count(kentik_snmp_tBgpPeerNgConnState{tags_snmp_group=~"$snmp_group",provider=~"$provider",device_name=~"$device_name"} == 6) OR vector(0)`
- **BGP Peers Total:** `count(kentik_snmp_tBgpPeerNgConnState{tags_snmp_group=~"$snmp_group",provider=~"$provider",device_name=~"$device_name"}) OR vector(0)`
- **Devices with Hardware Issues:** `count(count by(device_name) (kentik_snmp_tmnxHwOperState{tags_snmp_group=~"$snmp_group",provider=~"$provider",device_name=~"$device_name"} != 2)) OR vector(0)`
- **Total Interfaces:** `count(kentik_snmp_if_OperStatus{tags_snmp_group=~"$snmp_group",provider=~"$provider",device_name=~"$device_name"}) OR vector(0)`
- **Admin-Up Interfaces:** `count(kentik_snmp_if_OperStatus{tags_snmp_group=~"$snmp_group",provider=~"$provider",device_name=~"$device_name",if_AdminStatus!="down"}) OR vector(0)`

## 04. Network Device Details (`ktranslate-device-details`)
- **Generation:** 19
- **Layout:** TabsLayout

### Pattern counts

| Pattern | Count |
|---------|-------|
| bgp established 6 | 1 |
| bps delta 60 | 6 |
| errors per 60 | 1 |
| loki traps | 3 |
| max by device | 33 |
| max over time flow | 13 |
| memory utilization | 2 |
| or vector 0 | 3 |
| ping metrics | 8 |
| rate kentik snmp | 6 |

### Key variables

- `datasource`
- `snmp_group` → label `` on metric ``
- `provider` → label `` on metric ``
- `instance` → label `` on metric ``
- `has_ping` → label `` on metric ``
- `has_cpu` → label `` on metric ``
- `has_cpu_percore` → label `` on metric ``
- `has_memory` → label `` on metric ``
- `has_interfaces` → label `` on metric ``
- `has_disk` → label `` on metric ``
- `has_sensors` → label `` on metric ``
- `has_polling` → label `` on metric ``
- `has_cpu_breakdown` → label `` on metric ``
- `has_memory_detail` → label `` on metric ``
- `has_firewall` → label `` on metric ``
- `has_ntp` → label `` on metric ``
- `has_redundancy` → label `` on metric ``
- `has_sensor_celsius` → label `` on metric ``
- `has_sensor_voltsDC` → label `` on metric ``
- `has_sensor_amperes` → label `` on metric ``
- `has_sensor_truthvalue` → label `` on metric ``
- `has_sensor_dBm` → label `` on metric ``
- `has_sensor_voltsAC` → label `` on metric ``
- `has_sensor_watts` → label `` on metric ``
- `has_sensor_hertz` → label `` on metric ``
- `has_sensor_percentRH` → label `` on metric ``
- `has_sensor_rpm` → label `` on metric ``
- `has_sensor_cmm` → label `` on metric ``
- `has_sensor_specialEnum` → label `` on metric ``
- `has_sensor_other` → label `` on metric ``

### `has_*` gate metrics (device-details)

| Variable | Gate metric |
|----------|-------------|
| `has_ping` | `?` |
| `has_cpu` | `?` |
| `has_cpu_percore` | `?` |
| `has_memory` | `?` |
| `has_interfaces` | `?` |
| `has_disk` | `?` |
| `has_sensors` | `?` |
| `has_polling` | `?` |
| `has_cpu_breakdown` | `?` |
| `has_memory_detail` | `?` |
| `has_firewall` | `?` |
| `has_ntp` | `?` |
| `has_redundancy` | `?` |
| `has_sensor_celsius` | `?` |
| `has_sensor_voltsDC` | `?` |
| `has_sensor_amperes` | `?` |
| `has_sensor_truthvalue` | `?` |
| `has_sensor_dBm` | `?` |
| `has_sensor_voltsAC` | `?` |
| `has_sensor_watts` | `?` |

… and 27 more `has_*` gates

### Notable queries (sample)

- **Polling Status:** `max by(device_name)(kentik_snmp_PollingStatus{snmp_group=~"$snmp_group",device_name=~"$instance"})`
- **Process Count:** `max by(device_name)(kentik_snmp_procNum{snmp_group=~"$snmp_group",device_name=~"$instance"})`
- **Memory Used vs Free Over Time:** `max by(device_name)(kentik_snmp_MemoryUsed{snmp_group=~"$snmp_group",device_name=~"$instance"}) * 1024`
- **Memory Used vs Free Over Time:** `max by(device_name)(kentik_snmp_MemoryFree{snmp_group=~"$snmp_group",device_name=~"$instance"}) * 1024`
- **Active Connections:** `max by(device_name)(kentik_snmp_fwNumConn{snmp_group=~"$snmp_group",device_name=~"$instance"})`
- **Active Connections Over Time:** `max by(device_name)(kentik_snmp_fwPeakNumConn{snmp_group=~"$snmp_group",device_name=~"$instance"})`
- **Connection Disposition:** `max by(device_name)(rate(kentik_snmp_fwAccepted{snmp_group=~"$snmp_group",device_name=~"$instance"}[$__rate_interval]))`
- **Connection Disposition:** `max by(device_name)(rate(kentik_snmp_fwDropped{snmp_group=~"$snmp_group",device_name=~"$instance"}[$__rate_interval]))`
- **Connection Disposition:** `max by(device_name)(rate(kentik_snmp_fwRejected{snmp_group=~"$snmp_group",device_name=~"$instance"}[$__rate_interval]))`
- **Traffic In:** `clamp_max( topk(25, max by(if_interface_name) ( (kentik_snmp_ifHCInOctets{snmp_group=~"$snmp_group",device_name=~"$instance",if_interface_name=~"$interface_name"}) ) * 8 / 60 ), 100e9 )`
- **Traffic Out:** `clamp_max( topk(25, max by(if_interface_name) ( (kentik_snmp_ifHCOutOctets{snmp_group=~"$snmp_group",device_name=~"$instance",if_interface_name=~"$interface_name"}) ) * 8 / 60 ), 100e9 )`
- **Collection Age:** `min by (device_name) (time() - max_over_time(timestamp(kentik_ping_AvgRttMs{device_name=~"$instance"})[24h:1m]))`
