# Alloy network fork (lab harness)

**Home:** [Mesverrum/alloy](https://github.com/Mesverrum/alloy) branch `network-snmp` (fork of [grafana/alloy](https://github.com/grafana/alloy)). Sibling clone: `../alloy` next to this repo (`C:\Users\mesve\projects\alloy` on this machine).

**This repo** is the test harness. Default laptop `make up` still runs **ktranslate** so existing dashboards keep working. The destination is **Alloy with the network addons** (SNMP + traps + syslog + flow) replacing the KtransToGrafana pairing. The Alloy path is opt-in on the laptop (`LAB_ALLOY_SNMP=1`, …) and takes over on colocated k3s with `LAB_KTRANSLATE=0` (`make -C local alloy-cutover-colocated`).

**Current operator default:** AWS colocated only. Do not start the laptop Clos or Compose Alloy until asked.

**License (SNMP library snapshot):** `local/fixtures/alloy-snmp/` is derived from [kentik/snmp-profiles](https://github.com/kentik/snmp-profiles) (Apache-2.0). See [`NOTICE`](../local/fixtures/alloy-snmp/NOTICE) and [`LICENSE`](../local/fixtures/alloy-snmp/LICENSE). Authored `ip_addr` is original (IETF IP-MIB), not Kentik `ip-mib.yml`. This is attribution of origin, not a Kentik trademark license.

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
| SNMP discovery + credential/MIB mapping | 2 | Portable CLI + library: **[Mesverrum/snmp-sd](https://github.com/Mesverrum/snmp-sd)** (private). Alloy `discovery.snmp` still lives in the fork. Overlay still ships `snmp-discovery` for file/HTTP SD. Fleet needs `ALLOY_NETWORK_FROM_SOURCE=1` image. Live `/24` sweep on the colocated Clos (2026-09-08): five SRL, `module=if_mib,nokia_srlinux`, `auth=public_v2` — run on `--network clab`; prepend `auths:` if the image concat lacks it. |
| Trap receiver | 3 | **`otelcol.receiver.snmptrap`** (experimental) in the fork — [alloy#440](https://github.com/grafana/alloy/issues/440). OTel logs, not Loki. Docs: fork [`otelcol.receiver.snmptrap.md`](https://github.com/Mesverrum/alloy/blob/network-snmp/docs/sources/reference/components/otelcol/otelcol.receiver.snmptrap.md). Prior art: [`docs/snmp-trap-prior-art.md`](https://github.com/Mesverrum/alloy/blob/network-snmp/docs/snmp-trap-prior-art.md) |
| Flow collector | 4 | **`otelcol.receiver.netflow`** (experimental wrap of contrib logs receiver) — [alloy#6304](https://github.com/grafana/alloy/issues/6304). Metrics via existing `otelcol.connector.signaltometrics`. Lab: `LAB_ALLOY_NETFLOW=1` + `make alloy-netflow-up` |

`discovery.snmp` now has slog, health, metrics, Live Debugging, unmarshal tests, and Alloy-shaped reference docs. Remaining GA items (stability, integration tests, official image): fork [`docs/discovery-snmp-production-gaps.md`](https://github.com/Mesverrum/alloy/blob/network-snmp/docs/discovery-snmp-production-gaps.md).

Syslog is **not** a fork gap: `loki.source.syslog` (Cisco path: [`docs/alloy-cisco-syslog-lab.md`](alloy-cisco-syslog-lab.md)).

Fleet Management can only push **config** for components in the running binary. Slice 1 bakes `/etc/alloy/snmp-network.yml` into `srl-local/alloy:network-dev`. Slice 2 is **`discovery.snmp`** (experimental) when the image is built from the fork (`Dockerfile.network-src` / `ALLOY_NETWORK_FROM_SOURCE=1`). The thin `Dockerfile.network` overlay keeps the sidecar CLI only.

### Fleet-shaped laptop lab (marcnetterfield1)

`LAB_ALLOY_SNMP=1` renders **staggered** scrapes in `alloy/snmp-scrape.generated.alloy`:

| Tier | Interval | Modules (typical) | Toggle |
|--|--|--|--|
| **hot** | 60s (`LAB_ALLOY_SNMP_HOT_INTERVAL`) | minimum useful: `if_mib` **octets / oper / ifHighSpeed**, inlined `snmp_device_info` + `snmp_Uptime`, CPU/mem | `LAB_ALLOY_SNMP_TIERS=hot` (or include `hot` in the list) |
| **cold** | 5m lab / 30m fleet (`LAB_ALLOY_SNMP_COLD_INTERVAL`) | names/descriptions/MAC (`if_mib_meta`) + **packet counters** + **errors** + **discards** + IP inventory (`ip_addr`) | include `cold` (default with hot) |
| **topology** | 15m (`LAB_ALLOY_SNMP_TOPOLOGY_INTERVAL`) | LLDP/CDP/BGP-class neighbor walks | include `topology`, or `LAB_ALLOY_SNMP_TOPOLOGY=1` when `TIERS` is unset |

Default when `LAB_ALLOY_SNMP_TIERS` is unset: **hot+cold**. `LAB_ALLOY_SNMP_TIERS=hot` is the absolute minimum scrape. Alloy: `tiers = ["hot"]`. CLI: `--tiers=hot`. Each tier is independently optional.


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

`remotecfg` is isolated: it cannot call components in the local ConfigMap. So OTLP receive / docker scrape / preprocess stay **local**. Fleet owns the network addons in **one** pipeline (`network_o11y_alloy` ← `local/fixtures/alloy-fleet/network.pipeline.alloy`) that exports OTLP itself via `GC_OTLP_*`.

Laptop:

```bash
# GC_FM_URL auto-detected from Collector app on marcnetterfield1
# (https://fleet-management-prod-008.grafana.net); GC_FM_TOKEN defaults to GC_OTLP_KEY.
LAB_ALLOY_FLEET=1
LAB_ALLOY_FLEET_SNMP=1   # stub local SNMP River; Fleet delivers the combined pipeline
make -C local alloy-fleet-up
```

Colocated k3s (same pipeline — `alloy-cutover-colocated` also stubs local traps/syslog/netflow):

```bash
LAB_ALLOY_FLEET=1
LAB_ALLOY_FLEET_SNMP=1
LAB_ALLOY_FLEET_EVENTS=1
LAB_ALLOY_FLEET_NETFLOW=1
make -C local alloy-cutover-colocated
```

Matcher: `lab="network-o11y-demo"`, `role="network-snmp"`. CIDRs and extra join aliases live **in the pipeline** (`group { }` + a YAML backtick list) so they are editable in the Fleet GUI. The SNMP **library** (`snmp-network.yml`, `fingerprinters.yml`, MIBs) stays in the image — those files are megabytes and are not operator config. `LAB_ALLOY_FLEET_EVENTS` / `_NETFLOW` only stub the **local** ConfigMap — they do not split Fleet.

Local `snmp-discovery` still writes `snmp-targets*.yml` on the overlay image. With a **from-source** image, prefer Fleet River:

```alloy
discovery.snmp "fabric" {
  auths = env("SNMP_AUTHS")
  tier  = "hot"   // or "all" + discovery.relabel by snmp_tier
  group {
    name  = "hq"
    cidrs = ["172.20.20.0/24"]
    auths = ["public_v2"]
  }
}
prometheus.exporter.snmp "fabric_hot" {
  auths   = env("SNMP_AUTHS")
  targets = discovery.snmp.fabric.targets
}
```

The image library paths (`snmp_config`, `fingerprinters`, `config_file`, `mib_paths`) are component defaults. Set them only to override. Credentials are `SNMP_AUTHS` (snmp_exporter `auths:` YAML) or `auths_file` — see the fork [`snmp/auths.example.yml`](https://github.com/Mesverrum/alloy/blob/network-snmp/snmp/auths.example.yml). Empty `SNMP_AUTHS` falls back to auths already in the image library.

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

Interface counters use `rate(snmp_ifHCInOctets[$__rate_interval]) * 8` (Prometheus counters). Do **not** use ktranslate’s `(ifHCInOctets) * 8 / 60` (delta gauges).

### Computed metrics (recording rules)

ktranslate computes several series in-process (`MemoryUtilization`, `ifInErrorPercent`, NR `IfInUtilization`). The Alloy converter does **not** — scrapes stay native `snmp_*`. Grafana-managed recording rules fill that gap with Prometheus colon names (`level:metric:operations`) so they cannot collide with a scrape.

| | |
|--|--|
| **Provision** | `make -C local alloy-snmp-recording-rules` |
| **Script** | `local/scripts/provision-alloy-snmp-recording-rules.py` |
| **YAML export** | [`local/fixtures/alloy-snmp/recording-rules.yaml`](../local/fixtures/alloy-snmp/recording-rules.yaml) |
| **Stack** | folder `network-lab` — **Network Lab / alloy-snmp composites** (1m) and **… composites cold** (5m), write to `grafanacloud-prom` |
| **Selector** | all exprs filter `job="alloy-snmp"` |

| Recorded name | ktranslate / NR equivalent | Formula (lab) | Notes |
|---|---|---|---|
| `device:snmp_MemoryUtilization:percent` | `kentik_snmp_MemoryUtilization` | Vendor percent OIDs **or** `100 * Used / (Used+Free)` **or** `(Total-Free)/Total` **or** `Used/Total` | Device-level `max by (instance, device_name, job, snmp_group)`. Matches [ktranslate `device_metrics.go`](https://github.com/kentik/ktranslate/blob/master/pkg/inputs/snmp/metrics/device_metrics.go). Nokia SRL uses Used+Free (`sgiKbMemoryAvailable` → `snmp_MemoryFree`). |
| `if:snmp_ifInErrors:rate5m` | `(kentik_snmp_ifInErrors) / 60` | `rate(snmp_ifInErrors[15m])` | **Cold group (5m).** Errors live on `if_mib_meta` with packet counters — not a 60s page. |
| `if:snmp_ifOutErrors:rate5m` | `(kentik_snmp_ifOutErrors) / 60` | `rate(snmp_ifOutErrors[15m])` | Same, outbound. |
| `if:snmp_ifInErrorPercent:percent` | `kentik_snmp_ifInErrorPercent` | `100 * rate(errors[15m]) / rate(ucast pkts[15m])` when ucast > 0 | **Cold group (5m).** Same-tier join on `device_name, ifIndex, if_interface_name` (**not** `instance` — still drop it so lingering hot series cannot pair). |
| `if:snmp_ifOutErrorPercent:percent` | `kentik_snmp_ifOutErrorPercent` | Same, outbound | Idle ifaces (0 unicast) stay empty — no fake 100%. |
| `if:snmp_ifHCInOctets:rate5m` | `(kentik_snmp_ifHCInOctets) / 60` | `rate(snmp_ifHCInOctets[5m])` | Octets/s. Dashboards: `* 8` for bps. |
| `if:snmp_ifHCOutOctets:rate5m` | `(kentik_snmp_ifHCOutOctets) / 60` | `rate(snmp_ifHCOutOctets[5m])` | Same, outbound. |
| `if:snmp_IfInUtilization:percent` | NR `kentik.snmp.IfInUtilization` | `100 * rate(octets[5m])*8 / ((ifHighSpeed > 0) * 1e6)` | ifHighSpeed is Mbps (RFC 2863). `== 0` (mgmt / unnumbered) is dropped to avoid `+Inf`. |
| `if:snmp_IfOutUtilization:percent` | NR `kentik.snmp.IfOutUtilization` | Same, outbound | Same-tier join (octets + speed are both hot) — `instance` is safe here. |

**Not recorded**

| ktranslate behavior | Why Alloy skips it |
|---|---|
| `CPU` from `100 - CPUIdle` | Nokia already scrapes `snmp_CPU` (tagged percent). No `snmp_CPUIdle` in the library. |
| `hrStorageUsedPercent` | HOST-RESOURCES not on the SRL cold set; converter would still emit Used/Size, not a percent name. |
| Packet rates (`ifHCInUcastPkts` / mcast / bcast) | Already scraped on **cold** `if_mib_meta`. Not recorded — modern fabrics rarely page on pps; use the raw counter if you need a one-off. |
| Discard rates (`ifInDiscards` / `ifOutDiscards`) | Same cold walk as errors. Not recorded. |

**Join gotcha:** Fleet hot/cold use different Alloy `instance` labels (`prometheus.exporter.snmp.fabric_hot` vs `fabric_cold`). Cross-tier ratios (e.g. lingering hot error series vs cold packets) must not match on `instance`. Error % drops `instance` on purpose.

**Alerts:** parallel Grafana group `Network Lab / alloy` (`make -C local alloy-network-alerts`) mirrors the ktranslate network rules onto `snmp_*` / recording rules / Loki `{service_name="alloy-snmptrap"}`. Does not replace `Network Lab / ktranslate`. Enums are numeric on this path (BGP established = 6).

Example queries:

```promql
max by (device_name) (device:snmp_MemoryUtilization:percent)
if:snmp_ifInErrorPercent:percent{device_name=~"$device"}
if:snmp_ifHCInOctets:rate5m{device_name=~"$device"} * 8
if:snmp_IfInUtilization:percent{device_name=~"$device"}
```

Name map (scrape MIB → `snmp_*` → ktranslate): [`local/fixtures/alloy-snmp/ktranslate-name-map.md`](../local/fixtures/alloy-snmp/ktranslate-name-map.md).

## Laptop: minimum lab (recommended while iterating)

One SR Linux node + Alloy. **No** leaves, clients, ktranslate, gnmic, or iperf. Tears down the 5-node Clos if it is running. Does **not** change `topology.clab.yml`.

```bash
make -C local alloy-network-image   # once
make -C local alloy-snmp-min        # spine1 + alloy + discover
make -C local alloy-snmp-min-down   # tear down
```

Expect `alloy/snmp-targets.yml` (hot: `if_mib,nokia_srlinux` with inlined `snmp_device_info`), `snmp-targets-cold.yml` (`if_mib_meta,ip_addr`), empty topology unless `LAB_ALLOY_SNMP_TOPOLOGY=1`. Discovery drops invented sidecars such as `nokia_srlinux_hot` when that file is not in the image `snmp.yml`. Full Clos: `make down && make up`.

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
- `make alloy-snmp-discover` writes `alloy/snmp-discovery.yml` (groups: CIDRs + named auths) and a one-shot probe. Each group name becomes **`snmp_group`** on `snmp_device_info` and the rest of the scrape. Laptop is one job (`hq`). Colocated is three jobs (`hq` / `branch1` / `branch2`) matching `fabric_site_for_node` — not a single `colocated` bucket. `ALLOY_SNMP_GROUP=` forces one job.
- Compose profile `alloy-snmp` runs `snmp_discovery` with `--interval 5m` and `--listen :9780` (HTTP SD catalog for a poller pool; laptop Alloy still scrapes `snmp-targets.yml`)
- Scrape 60s → `otelcol.receiver.prometheus` → existing OTLP preprocess/export
- Relabel `job=alloy-snmp`

ktranslate SNMP / flow / syslog are **not** disabled. Traps stay on ktranslate unless `LAB_ALLOY_SNMPTRAP=1` (`make alloy-snmptrap-up`) — then SRL trap-group points at Alloy `otelcol.receiver.snmptrap` `:1620` and Loki `{service_name="alloy-snmptrap"}` after OTLP export. Device syslog stays on ktranslate unless `LAB_ALLOY_SYSLOG=1` (`make alloy-syslog-up`) — then remote-server points at Alloy `loki.source.syslog` `:1514` and Loki `{service_name="alloy-syslog"}`. Both stamp `device_name` from `device-join.yml` (SNMP catalog plus fabric clients).

Alloy dashboard clones (A3 `ma8p7dn`, A4 `alloy-device-details`) query those streams directly — not ktranslate `eventType="KSnmpTrap"` / `instrumentation_name="ktranslate-syslog"`. Syslog lines are **plain text** (do not `| json`). Group traps by the `trap_oid` label (MIB names are not resolving on the lab image yet). Patch: `python local/scripts/patch-alloy-event-panels.py`. A2 Flow Summary has no event panels.

Optional Alloy-native flow (`LAB_ALLOY_NETFLOW=1`, `make alloy-netflow-up`) wraps contrib `otelcol.receiver.netflow` on **2055/udp** (NetFlow/IPFIX) and **6344/udp** (sFlow) so it does **not** steal ktranslate `:9995` / `:6343`. `targets` join `flow.sampler_address` / conversation IPs to `device_name` / `src_device` / `dst_device` from `device-join.yml`. Reverse-DNS uses the same LRU + `net.LookupAddr` pattern as `loki.source.syslog` (`udp_host_cache_size`) to stamp `src_host` / `dst_host` (PTR wins; catalog name on miss). Logs are renamed onto the same `network.local.*` / `network.peer.*` contract as ktranslate before `signaltometrics`. Two outputs:

| Flag | Default | What it does |
|------|---------|--------------|
| `LAB_ALLOY_NETFLOW_METRICS` | **on** | `otelcol.connector.signaltometrics` sums `flow.io.bytes` / `flow.io.packets` → OTLP `network.io.by_flow` (`integration=alloy-netflow`). PromQL: **`rate()`**, not ktranslate `* 8 / 60`. |
| `LAB_ALLOY_NETFLOW_LOGS` | **off** | Experimental: decoded records onto the existing OTLP logs export (`service_name=alloy-netflow`). Loki is not the scale path. |

Needs `ALLOY_NETWORK_FROM_SOURCE=1` image (`otelcol.receiver.netflow` is not in stock `grafana/alloy`). Dual-feed from softflowd is a second Alpine process (`-n` is one dest per process) — not wired by default.

### Poller pool (HTTP SD)

`snmp_discovery` is **one writer**. Laptop Alloy still reads `snmp-targets.yml`. A pool of pollers should consume `http://snmp_discovery:9780/sd` and **hashmod `__address__` before** `prometheus.exporter.snmp` (duplicate remainder = double walks). Same MD5 hashmod as Alloy/Prometheus relabel; optional `GET /sd?shard=0&shards=4` is the curl/debug equivalent. Example is in the fork [`tools/snmp-discovery/README.md`](https://github.com/Mesverrum/alloy/blob/network-snmp/tools/snmp-discovery/README.md).

Discovery modes (`sweep` / `crawl` / `both`): CIDR ping-then-SNMP (max ~1024 hosts: IPv4 `/22`, IPv6 `/118`; catalog always re-probed) plus LLDP/CDP crawl from seeds (**one hop per interval**, IPv4/IPv6). Named `auths` cover SNMPv1/v2c and **v3 USM** (snmp_exporter-shaped fields in `snmp.yml`; auth **name** only on SD). Catalog addresses are bare canonical IPs (IPv6 without brackets). Atomic catalog publish; `--misses` silent cycles before drop; overlapping scans skipped. Still out of scope: ARP/OSPF/BGP neighbor sources.

### Adding a credential (scoped, like a ktranslate group)

1. Copy a named block from the fork `snmp/auths.example.yml` into `SNMP_AUTHS` or a Secret file (`auths_file`). Do not edit `snmp-network.yml` on the collector. v2c: `community` + `version: 2`. v3 USM: `version: 3`, `username`, `password`, optional `priv_password`, `security_level`, `auth_protocol`, `priv_protocol`.
2. Point both `discovery.snmp` and `prometheus.exporter.snmp` at the same overlay (`auths = env("SNMP_AUTHS")`).
3. Add a **group** (Fleet River or `alloy/snmp-discovery.yml`) with that group's CIDRs and `auths: [that_name]` — do not dump every community/user onto every CIDR.
4. Optional pins/ignores: `alloy/snmp-overrides.yml`.
5. `make alloy-snmp-discover` or wait for `--interval`. Community / v3 secrets never appear in SD — only the auth **name**.

Profile conversion is **not** the bottleneck (kentik YAML → snmp_exporter modules already works). Discovery is the remaining admin-effort gap vs ktranslate.

### Adding a device family

Prefer editing `snmp/modules/<vendor>/` in the fork (that YAML is the library). Convert is a one-shot ingest of a kentik-style pack, not an ongoing sync:

1. Drop the profile YAML in the fork or point `--profiles` at the cookbook tree.
2. `python3 tools/snmp-profile-convert/convert.py --profiles … --clean-modules` once → split modules + `snmp-network.yml` + fingerprinters.
3. Nokia is already split: `nokia_srlinux` (hot vitals), `nokia_srlinux_sensors` (cold), `nokia_srlinux_bgp` (topology). Rebuild the overlay image after editing modules. Unknown `sysObjectID` scrapes `device_base,if_mib`.
4. Fingerprinters and `snmp-network.yml` are one catalog — do not add a `module=` name that convert did not write. Re-extract both from the image after rebuild.

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

**One catalog (do not drift).** `module=` on SD targets must be keys under `modules:` in the snmp.yml the exporter loads. Convert intersects fingerprinter lists with converted module names (no invented `nokia_srlinux_hot` unless that sidecar was written). Discovery drops names missing from the live `config_file`. Keep `snmp-network.yml` and `fingerprinters.yml` from the **same convert as the running image** — `alloy-snmp-discover.sh` re-extracts both from the image; `render-alloy-snmp-scrape.sh` must not overwrite that library with older `fixtures/alloy-snmp/`. Mixing generations looks like `up=1` with no `snmp_CPU`, or a collector panic.

**Extends:** kentik `extends:` → discovery `module=` chains (transitive), e.g. `if_mib,nokia_srlinux` or `if_mib,cisco_all_devices,cisco_catalyst`. Kentik `system-mib.yml` is folded into `snmp_device_info` on the fingerprint module (not a sibling scrape). `_general` bases are converted modules; Alloy uses `config_merge_strategy = "replace"`.

**Enums:** status symbols → `gauge` (+ `enum_values` catalog); inventory symbols → `EnumAsInfo`; `metric_tags` → lookups (`EnumAsInfo` when the tag column has an enum). No `EnumAsStateSet`.


**When converting / extending profiles:**

1. Keep kentik’s implicit Entry: metric OID is `table.1.column` (do not strip `.1`).
2. `TABLE_INDEXES` in `tools/snmp-profile-convert/convert.py` must list the **full** MIB INDEX — short indexes cause duplicate-label scrape failures in snmp_exporter (ktranslate is more forgiving).
3. Confirm arity with a live `snmpwalk` of the column OID before baking a new table into the image.
4. Discovery `module=` = resolved extends chain; Alloy `config_merge_strategy = "replace"`.
