# Alloy network fork (lab harness)

**Home:** [Mesverrum/alloy](https://github.com/Mesverrum/alloy) branch `network-snmp` (fork of [grafana/alloy](https://github.com/grafana/alloy)). Sibling clone: `../alloy` next to this repo (`C:\Users\mesve\projects\alloy` on this machine).

**This repo** is the test harness. Default `make up` still runs **ktranslate** so existing dashboards keep working. The destination is **Alloy with the network addons** (SNMP + traps + syslog + flow) replacing the KtransToGrafana pairing. The Alloy path is opt-in today (`LAB_ALLOY_SNMP=1`, …) and runs in parallel until that cutover.

Fork docs: [`docs/network-snmp.md`](https://github.com/Mesverrum/alloy/blob/network-snmp/docs/network-snmp.md) (after the branch is pushed).

## Why this shape (Prometheus maintainers)

Stock Alloy already polls SNMP (`prometheus.exporter.snmp`). The fight internally will be with people who already run Prometheus + snmp_exporter. So discovery does **not** invent a ktranslate `devices.yaml`. It is a Prometheus **Discoverer**:

| Rule | What we emit | What we never emit |
|------|----------------|--------------------|
| Credentials | named `auth=` / `__param_auth` from `snmp.yml` `auths:` | community string, v3 secret, on labels or SD files |
| MIB / module | `module=` / `__param_module` (comma-separated, same as snmp_exporter) | a side-channel profile name |
| New devices | CIDR/`/32` probe → GET `sysObjectID` → SuperQ **fingerprinters** ([snmp_exporter#1468](https://github.com/prometheus/snmp_exporter/issues/1468)) | exporter-side CIDR walker |
| Consumers | Alloy YAML, Prometheus `file_sd`, and HTTP SD (`GET /sd`) | Alloy-only lock-in |

The exporter stays **stock**. Fingerprinters run at SD time (portable subset of #1468 until that lands in snmp_exporter). Alloy loads targets the documented way: `targets = encoding.from_yaml(local.file….content)`.

| Gap | Slice | Status |
|-----|-------|--------|
| Curated device-family OID library (CPU / mem / BGP / sensors, not only IF-MIB) | 1 | **done** — `nokia_srlinux` + `lenovo_rackswitch` in the image |
| SNMP discovery + credential/MIB mapping | 2 | **`discovery.snmp`** in the fork (`internal/snmpdiscovery` + component). Overlay still ships `snmp-discovery` CLI for file/HTTP SD. Fleet needs `ALLOY_NETWORK_FROM_SOURCE=1` image. |
| Trap receiver | 3 | **`loki.source.snmptrap`** (experimental) in the fork — [alloy#440](https://github.com/grafana/alloy/issues/440). Docs: fork [`loki.source.snmptrap.md`](https://github.com/Mesverrum/alloy/blob/network-snmp/docs/sources/reference/components/loki/loki.source.snmptrap.md). Prior art: [`docs/snmp-trap-prior-art.md`](https://github.com/Mesverrum/alloy/blob/network-snmp/docs/snmp-trap-prior-art.md) |
| Flow collector | 4 | **`otelcol.receiver.netflow`** (experimental wrap of contrib logs receiver) — [alloy#6304](https://github.com/grafana/alloy/issues/6304). Metrics via existing `otelcol.connector.signaltometrics`. Lab: `LAB_ALLOY_NETFLOW=1` + `make alloy-netflow-up` |

`discovery.snmp` now has slog, health, metrics, Live Debugging, unmarshal tests, and Alloy-shaped reference docs. Remaining GA items (stability, integration tests, official image): fork [`docs/discovery-snmp-production-gaps.md`](https://github.com/Mesverrum/alloy/blob/network-snmp/docs/discovery-snmp-production-gaps.md).

Syslog is **not** a fork gap: `loki.source.syslog` (Cisco path: [`docs/alloy-cisco-syslog-lab.md`](alloy-cisco-syslog-lab.md)).

Fleet Management can only push **config** for components in the running binary. Slice 1 bakes `/etc/alloy/snmp-network.yml` into `srl-local/alloy:network-dev`. Slice 2 is **`discovery.snmp`** (experimental) when the image is built from the fork (`Dockerfile.network-src` / `ALLOY_NETWORK_FROM_SOURCE=1`). The thin `Dockerfile.network` overlay keeps the sidecar CLI only.

### Fleet-shaped laptop lab (marcnetterfield1)

`LAB_ALLOY_SNMP=1` renders **staggered** scrapes in `alloy/snmp-scrape.generated.alloy`:

| Tier | Interval | Modules (typical) | Toggle |
|--|--|--|--|
| **hot** | 60s (`LAB_ALLOY_SNMP_HOT_INTERVAL`) | alerting/troubleshooting that fits 60s: `if_mib` counters/oper, inlined `snmp_device_info` + `snmp_Uptime` (on the vendor module or `device_base`), CPU/mem, chassis | always on when SNMP enabled |
| **cold** | 5m lab / 30m fleet (`LAB_ALLOY_SNMP_COLD_INTERVAL`) | names/descriptions/MAC (`if_mib_meta`) + IP inventory (`ip_addr`) | always on when SNMP enabled |
| **topology** | 15m (`LAB_ALLOY_SNMP_TOPOLOGY_INTERVAL`) | optional LLDP/CDP experiments — not BGP | `LAB_ALLOY_SNMP_TOPOLOGY=1` |


Discovery writes `snmp-targets.yml` (hot), `snmp-targets-cold.yml`, `snmp-targets-topology.yml`. Converter emits `snmp/module-tiers.yaml` + fingerprinter `modules_hot` / `modules_cold` / `modules_topology`.

```bash
ALLOY_IMAGE=srl-local/alloy:network-dev
LAB_ALLOY_SNMP=1
LAB_ALLOY_SNMP_TOPOLOGY=1   # optional
make -C local alloy-network-image
make -C local alloy-snmp-min
```

Default `make up` is unchanged (ktranslate).

### Fleet Management (real enroll)

Laptop Alloy can enroll in Grafana Fleet Management and pull the SNMP scrape River remotely:

```bash
# GC_FM_URL auto-detected from Collector app on marcnetterfield1
# (https://fleet-management-prod-008.grafana.net); GC_FM_TOKEN defaults to GC_OTLP_KEY.
LAB_ALLOY_FLEET=1
LAB_ALLOY_FLEET_SNMP=1   # move hot/cold River to Fleet pipeline
make -C local alloy-fleet-up
```

Local `snmp-discovery` still writes `snmp-targets*.yml` on the overlay image. With a **from-source** image, prefer Fleet River:

```alloy
discovery.snmp "fabric" {
  snmp_config = "/etc/alloy/snmp-network.yml"
  tier        = "hot"   // or "all" + discovery.relabel by snmp_tier
  group {
    name  = "hq"
    cidrs = ["172.20.20.0/24"]
    auths = ["public_v2"]
  }
}
prometheus.exporter.snmp "fabric_hot" {
  config_file = "/etc/alloy/snmp-network.yml"
  targets     = discovery.snmp.fabric.targets
}
```

Build with discovery.snmp compiled in:

```bash
ALLOY_NETWORK_FROM_SOURCE=1 make -C local alloy-network-image
```

The MIB library stays in the image. UI: **Connections → Collector → Fleet Management**.

## Metric contract

Curated `snmp_*` names (converter prefix + vital `tag` stems). Target label `device_name` is still set for joins. Labels (`ifName`, …) are not prefixed.

| Example | Emitted |
|---------|---------|
| Nokia `sgiCpuUsage` `tag: CPU` | `snmp_CPU` (utilization %) |
| HOST-RESOURCES `hrProcessorLoad` (often untagged in kentik) | `snmp_CPU` (utilization % — not a load average) |
| UCD `laLoadInt*` / UniFi `loadValue` tagged `CPU` | `snmp_CPULoad` (Unix load average — not %) |
| IF-MIB `ifHCInOctets` | `snmp_ifHCInOctets` |
| BGP `tBgpPeerNgConnState` | `snmp_tBgpPeerNgConnState` |

Interface counters use `rate(snmp_ifHCInOctets[$__rate_interval]) * 8` (Prometheus counters). Composites (memory %, error %, bps) are optional recording rules: [`local/fixtures/alloy-snmp/recording-rules.yaml`](../local/fixtures/alloy-snmp/recording-rules.yaml).

## Laptop: minimum lab (recommended while iterating)

One SR Linux node + Alloy. **No** leaves, clients, ktranslate, gnmic, or iperf. Tears down the 5-node Clos if it is running. Does **not** change `topology.clab.yml`.

```bash
make -C local alloy-network-image   # once
make -C local alloy-snmp-min        # spine1 + alloy + discover
make -C local alloy-snmp-min-down   # tear down
```

Expect `alloy/snmp-targets.yml` (hot: `if_mib,nokia_srlinux_hot,nokia_srlinux` with inlined `snmp_device_info`), `snmp-targets-cold.yml` (`if_mib_meta,ip_addr`), empty topology unless `LAB_ALLOY_SNMP_TOPOLOGY=1`. Full Clos: `make down && make up`.

## Lab bring-up (parallel to ktranslate)

```bash
# 1) Overlay image (does not compile Alloy)
make -C local alloy-network-image
# requires sibling clone of Mesverrum/alloy @ network-snmp, or ALLOY_SRC=

# 2) Pin in local/.env
#    ALLOY_IMAGE=srl-local/alloy:network-dev
#    LAB_ALLOY_SNMP=1
# Optional: ALLOY_SNMP_AUTHS=public_v2
# Optional: ALLOY_SNMP_CIDRS=172.20.20.2/32,...  (default: live spine/leaf /32s)

# 3) Discover + recreate Alloy (fabric must be on the clab network)
make -C local alloy-snmp-up
# alloy-snmp-up runs alloy-snmp-discover, then force-recreates alloy.
# Re-probe after IP drift: make -C local alloy-snmp-discover
# (local.file polls snmp-targets.yml — no recreate required for target churn)

# 4) Dashboard
make -C local alloy-snmp-dash
```

Explore (operator stack, same `GC_OTLP_*`):

```promql
count by (device_name) (snmp_CPU{job="alloy-snmp"})
count by (device_name, ifName) (snmp_ifOperStatus{job="alloy-snmp"})
count by (device_name, ifIndex, ipAdEntAddr) (snmp_ipAdEntIfIndex{job="alloy-snmp"})
count by (device_name) (snmp_tBgpPeerNgConnState{job="alloy-snmp"})
```

A/B control (ktranslate, unchanged):

```promql
count by (device_name) (kentik_snmp_CPU)
```

Dashboard UID: `alloy-snmp-device-details` (folder `network-lab`).

## What the overlay does

`LAB_ALLOY_SNMP=1` renders [`local/scripts/render-alloy-snmp-scrape.sh`](../local/scripts/render-alloy-snmp-scrape.sh) → `alloy/snmp-scrape.generated.alloy`:

- `local.file` + `encoding.from_yaml` of `alloy/snmp-targets.yml` (official Alloy snmp exporter pattern)
- `prometheus.exporter.snmp` with `config_merge_strategy = "replace"` (our `snmp-network.yml` only — no stock embedded merge)
- `make alloy-snmp-discover` writes `alloy/snmp-discovery.yml` (group: CIDRs + named auths) and a one-shot probe
- Compose profile `alloy-snmp` runs `snmp_discovery` with `--interval 5m` and `--listen :9780` (HTTP SD catalog for a poller pool; laptop Alloy still scrapes `snmp-targets.yml`)
- Scrape 60s → `otelcol.receiver.prometheus` → existing OTLP preprocess/export
- Relabel `job=alloy-snmp`

ktranslate SNMP / flow / syslog are **not** disabled. Traps stay on ktranslate unless `LAB_ALLOY_SNMPTRAP=1` (`make alloy-snmptrap-up`) — then SRL trap-group points at Alloy `loki.source.snmptrap` `:1620` and Loki `{service_name="alloy-snmptrap"}`. Device syslog stays on ktranslate unless `LAB_ALLOY_SYSLOG=1` (`make alloy-syslog-up`) — then remote-server points at Alloy `loki.source.syslog` `:1514` and Loki `{service_name="alloy-syslog"}`. Both stamp `device_name` from `snmp-targets.yml`.

Optional Alloy-native flow (`LAB_ALLOY_NETFLOW=1`, `make alloy-netflow-up`) wraps contrib `otelcol.receiver.netflow` on **2055/udp** (NetFlow/IPFIX) and **6344/udp** (sFlow) so it does **not** steal ktranslate `:9995` / `:6343`. Optional `targets` join `flow.sampler_address` to `device_name` from `snmp-targets.yml` (same catalog as traps/syslog). Two outputs:

| Flag | Default | What it does |
|------|---------|--------------|
| `LAB_ALLOY_NETFLOW_METRICS` | **on** | `otelcol.connector.signaltometrics` sums `flow.io.bytes` / `flow.io.packets` → OTLP `network.io.by_flow` (`integration=alloy-netflow`). PromQL: **`rate()`**, not ktranslate `* 8 / 60`. |
| `LAB_ALLOY_NETFLOW_LOGS` | **off** | Experimental: decoded records onto the existing OTLP logs export (`service_name=alloy-netflow`). Loki is not the scale path. |

Needs `ALLOY_NETWORK_FROM_SOURCE=1` image (`otelcol.receiver.netflow` is not in stock `grafana/alloy`). Dual-feed from softflowd is a second Alpine process (`-n` is one dest per process) — not wired by default.

### Poller pool (HTTP SD)

`snmp_discovery` is **one writer**. Laptop Alloy still reads `snmp-targets.yml`. A pool of pollers should consume `http://snmp_discovery:9780/sd` and **hashmod `__address__` before** `prometheus.exporter.snmp` (duplicate remainder = double walks). Same MD5 hashmod as Alloy/Prometheus relabel; optional `GET /sd?shard=0&shards=4` is the curl/debug equivalent. Example is in the fork [`tools/snmp-discovery/README.md`](https://github.com/Mesverrum/alloy/blob/network-snmp/tools/snmp-discovery/README.md).

Discovery modes (`sweep` / `crawl` / `both`): CIDR ping-then-SNMP (max ~1024 hosts: IPv4 `/22`, IPv6 `/118`; catalog always re-probed) plus LLDP/CDP crawl from seeds (**one hop per interval**, IPv4/IPv6). Named `auths` cover SNMPv1/v2c and **v3 USM** (snmp_exporter-shaped fields in `snmp.yml`; auth **name** only on SD). Catalog addresses are bare canonical IPs (IPv6 without brackets). Atomic catalog publish; `--misses` silent cycles before drop; overlapping scans skipped. Still out of scope: ARP/OSPF/BGP neighbor sources.

### Adding a credential (scoped, like a ktranslate group)

1. Add a named block under `auths:` in `snmp/snmp-network.yml` (v2c `community` + `version: 2`, or v3 USM: `version: 3`, `username`, `password`, optional `priv_password`, `security_level`, `auth_protocol`, `priv_protocol`).
2. Add a **group** in `alloy/snmp-discovery.yml` with that group's CIDRs and `auths: [that_name]` — do not dump every community/user onto every CIDR.
3. Optional pins/ignores: `alloy/snmp-overrides.yml`.
4. `make alloy-snmp-discover` or wait for `--interval`. Community / v3 secrets never appear in SD — only the auth **name**.

Profile conversion is **not** the bottleneck (kentik YAML → snmp_exporter modules already works). Discovery is the remaining admin-effort gap vs ktranslate.

### Adding a device family

Prefer editing `snmp/modules/<vendor>/` in the fork (that YAML is the library). Convert is a one-shot ingest of a kentik-style pack, not an ongoing sync:

1. Drop the profile YAML in the fork or point `--profiles` at the cookbook tree.
2. `python3 tools/snmp-profile-convert/convert.py --profiles … --clean-modules` once → split modules + `snmp-network.yml` + fingerprinters.
3. Hand-trim if needed (Nokia hot/chassis split, drop BGP walks). Rebuild the overlay image. Unknown `sysObjectID` scrapes `device_base,if_mib`.

## Converter (one-shot ingest)

Kentik YAML is an OID cookbook. After convert, **edit `snmp/modules/`** — do not keep a ktranslate name map or re-convert to stay “in sync.”

```bash
# Optional: type counters from public OID pages (no MIB tree).
python3 ../alloy/tools/snmp-profile-convert/lookup-oid-syntax.py \
  --profiles ../snmp-profiles/profiles/kentik_snmp
python3 ../alloy/tools/snmp-profile-convert/lookup-oid-indexes.py \
  --profiles ../snmp-profiles/profiles/kentik_snmp

python3 ../alloy/tools/snmp-profile-convert/convert.py \
  --profiles ../snmp-profiles/profiles/kentik_snmp \
  --clean-modules
```

Kentik profile YAML (numeric OIDs) → split `snmp/modules/<vendor>/` + concatenated `snmp-network.yml` + `fingerprinters.yml`. Metric `type` prefers `snmp/oid-syntax.yaml` (Counter32/64 vs Gauge32). Snapshot: [`local/fixtures/alloy-snmp/`](../local/fixtures/alloy-snmp/).

**Extends:** kentik `extends:` → discovery `module=` chains (transitive), e.g. `if_mib,nokia_srlinux` or `if_mib,cisco_all_devices,cisco_catalyst`. Kentik `system-mib.yml` is folded into `snmp_device_info` on the fingerprint module (not a sibling scrape). `_general` bases are converted modules; Alloy uses `config_merge_strategy = "replace"`.

**Enums:** status symbols → `gauge` (+ `enum_values` catalog); inventory symbols → `EnumAsInfo`; `metric_tags` → lookups (`EnumAsInfo` when the tag column has an enum). No `EnumAsStateSet`.


**When converting / extending profiles:**

1. Keep kentik’s implicit Entry: metric OID is `table.1.column` (do not strip `.1`).
2. `TABLE_INDEXES` in `tools/snmp-profile-convert/convert.py` must list the **full** MIB INDEX — short indexes cause duplicate-label scrape failures in snmp_exporter (ktranslate is more forgiving).
3. Confirm arity with a live `snmpwalk` of the column OID before baking a new table into the image.
4. Discovery `module=` = resolved extends chain; Alloy `config_merge_strategy = "replace"`.
