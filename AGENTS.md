# AGENTS.md — guidance for LLM coding agents

**New operator on any Grafana Cloud stack?** Start with [**Agent playbook**](#agent-playbook--run-the-local-lab-on-the-operators-stack) below.

Keep this file accurate as the lab evolves. When you change architecture, collectors, metric names, or bring-up steps, **update this file and `.cursor/rules/` in the same change**.

## What this repo is

Companion demo for the blog series **Network Observability Without the Lock-in**. One **ktranslate-centric telemetry model** runs on every platform — see [`docs/ktranslate-unified-model.md`](docs/ktranslate-unified-model.md).

| Where it runs | How you start it |
|---------------|------------------|
| **Laptop** (macOS / Windows / Linux) | [`local/`](local/) + [`oneclick/`](oneclick/) — ContainerLab + Compose |
| **AWS colocated** | [`terraform/colocated-network-lab/`](terraform/colocated-network-lab/) — ContainerLab fabric + **k3s** (`make -C local colocated-lab-up`). Fresh EC2: `userdata.sh.tpl` → `colocated-host-deps.sh` → systemd `network-o11y-fabric` / `network-o11y-telemetry` (staggered deploy, discovery retries, sanity scripts — no manual SSM). |
| **AWS / EKS (legacy blog)** | [`terraform/`](terraform/) + [`k8s/telemetry/`](k8s/telemetry/) — Clabbernetes reference only |

**Source of truth for collector config:** `local/` → `make generate` (Compose) or `make generate-k8s` → `k8s/ktranslate-golden/` (Kubernetes). Do not hand-edit generated manifests. **Device lists** come from SNMP discovery (`make discover GROUP=<name>` scanning `TARGETS` CIDRs in `groups/*.env`) — never hand-populate `state/devices-*.yaml`. Colocated AWS runs the same discovery after k3s Alloy is up (`COLLECTOR_RUNTIME=k3s`).

Do **not** lift-and-shift the EKS/Clabbernetes **networking** stack onto a laptop. Local work belongs under `local/`. Alloy is the OTLP sink on all paths; **SNMP, flow, sFlow, and syslog are always ktranslate**, not Alloy-native collectors.

## Agent playbook — run the local lab on the operator's stack

**Audience:** LLM coding agents helping a new teammate bring up `local/` on **their own** Grafana Cloud stack (macOS, WSL2, or native Linux). Follow this section before improvising.

### Read order

1. This section (playbook)
2. [`docs/ktranslate-unified-model.md`](docs/ktranslate-unified-model.md) — one collector model (ktranslate + Alloy + gnmic)
3. [`local/README.md`](local/README.md) — operator commands and platform notes
4. [`docs/network-observability-primer.md`](docs/network-observability-primer.md) — optional; networking context

### Hard rules for agents

| Do | Do not |
|----|--------|
| Work under `local/` only | Port EKS/Clabbernetes networking into `local/` |
| Ask the user for **their** Grafana Cloud OTLP creds if `.env` is missing or placeholder | Assume `networko11ydev`, `marcnetterfield1`, or any stack baked into the repo |
| Run `make check` before `make up` | Commit `local/.env`, `local/groups/*.env`, `local/config/`, or `local/state/` |
| **Run lab diagnostics and fixes yourself** (WSL/bash, Grafana MCP PromQL) — `make softflowd`, `make traffic`, `make stabilize`, etc. | Tell the user to run operator commands you can execute in the shell |
| Use `make stabilize` when SRL nodes stop | Run `clab deploy --reconfigure` unless the user explicitly asks |
| Use `python3 local/scripts/retarget-otlp-gc.py --write` (env vars) on any OS | Rely on `retarget-otlp-networko11ydev.py` / `marcnetterfield1` on Mac (Windows CredMgr only) |

### Detect platform

```bash
uname -s          # Darwin = macOS, Linux = WSL or native
docker info       # must succeed before bring-up
```

| Platform | How agents run commands | Extra setup |
|----------|-------------------------|-------------|
| **macOS** | **Inside an OrbStack Linux VM** — ContainerLab has no macOS binary, so run the whole lab in a VM (`orb -m ubuntu ...`). See [`docs/macos-orbstack-setup.md`](docs/macos-orbstack-setup.md). | `brew install --cask orbstack`; in the VM install `docker.io docker-compose-v2 make gettext-base`, ContainerLab via get.containerlab.dev, mikefarah `yq`; give the VM **10–12 GB** RAM; clone to the VM's native disk (not `/Users`); run discovery as **`sudo make discover GROUP=srl`** (VM user is uid 501, ktranslate expects uid 1000) |
| **WSL2 (Windows)** | Bash in WSL on a **native ext4 clone** (`~/projects/network-o11y-demo/local`) — **not** `/mnt/c/...` | `sudo apt install yq gettext-base`; `sudo chown -R 1000:1000 config state` after `make generate`. From Cursor on Windows, run commands via `wsl -e bash -lc 'cd ~/projects/network-o11y-demo/local && …'` or use `.\oneclick\deploy.ps1` |
| **Native Linux** | Bash in `local/` | `chown` only if preflight warns about uid ≠ 1000 on `config/` / `state/` |

**Apple Silicon:** images are `linux/amd64`; first `make up` may take **~15 min** under emulation. This is expected.

### Credentials — ask the user if any are missing

The operator must supply values from **their** Grafana Cloud stack:

- **Grafana Cloud → Connections → OpenTelemetry** → OTLP endpoint URL, instance ID, access policy token
- Map to `local/.env`:
  - `GC_OTLP_URL` — e.g. `https://otlp-gateway-prod-<region>.grafana.net/otlp`
  - `GC_OTLP_ACCOUNT` — stack instance / OTLP account id (numeric)
  - `GC_OTLP_KEY` — `glc_…` token (metrics:write, logs:write, traces:write)

Optional:

- `LAB_TESTER_ID` — label for topology/entity metrics (default `network-lab`; set to operator name on shared stacks)
- `KTRANS_HOST` — optional override for `deployment_host` / `service_name` host suffix. Leave blank: `make generate` writes `compose-host.generated.env` from hostname (`host-id.sh`). All compose paths load `.env` + that file — do not hardcode per-machine hostnames in `.env`.

**Merge helper (any OS):**

```bash
export GRAFANA_URL=https://<stack>.grafana.net
export GC_OTLP_URL=... GC_OTLP_ACCOUNT=... GC_OTLP_KEY=...
python3 local/scripts/retarget-otlp-gc.py --write
```

Restart Alloy after OTLP changes: `docker compose -f local/compose-base.yaml … up -d --force-recreate alloy` or `make -C local up`.

### First-time bring-up (exact sequence)

```bash
cd local
cp .env.example .env
cp groups/srl.env.sample groups/srl.env
# Edit .env: GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY (and optional LAB_TESTER_ID)

make generate
# Linux/WSL only, if preflight warns:
# sudo chown -R 1000:1000 config state

make check          # must pass (docker, containerlab, yq, envsubst, non-placeholder .env)
make up             # staggered ~10 min — fabric + collectors + flows/syslog/traps/traffic/events
make status
```

From repo root: `make local-up` ≡ `make -C local up`.

**What `make up` does:** deploy ContainerLab fabric (spine1 → leaf1 → leaf2 → client1 → client2 with settle pauses) → start collectors one-by-one (`alloy`, `flow_dns`, `ktranslate_snmp_srl`, `ktranslate_flow`, `ktranslate_sflow`, `ktranslate_syslog`, `gnmic`) → refresh SNMP targets → `make discover GROUP=srl` → **`scripts/post-telemetry-config.sh`** (softflowd, sFlow, syslog, traps, flow DNS, traffic, events-loop) → **mgmt API catalog** OTLP export. Optional: `topology_exporter` via `LAB_TOPOLOGY_EXPORTER=1` + `make topology-up`. Opt out: `LAB_AUTO_TRAFFIC=0` / `LAB_AUTO_EVENTS=0` in `.env`.

**Parallel / faster (less safe on 16 GB):** `make up-parallel` or `LAB_STAGGER=0 make up`.

### Success criteria (verify in the operator's Grafana Cloud)

Use Grafana Explore → Prometheus (or Grafana Cloud MCP if authenticated to **their** stack). **Do not use `kentik_snmp_DeviceMetrics`** — that rollup exists on AWS `integrations/snmp` dashboards, **not** on the ktranslate OTLP path. See [Metric names & PromQL](#metric-names--promql-ktranslate-otlp-path).

```promql
count by (device_name) (kentik_snmp_CPU)
```

Expect **three** devices: `spine1`, `leaf1`, `leaf2`.

```promql
count(network_io_by_flow_bytes)
```

```promql
sum(network_io_by_flow_bytes) * 8 / 60
```

(Use `network_io_by_flow_bytes` rollup gauges — **`rate(network_io_by_flow[…])` under-reports** on ktranslate delta exports.)

```promql
count by (src_device, dst_device) (network_topology_edge_info{tester_id="<LAB_TESTER_ID or network-lab>"})
```

(Device nodes via optional `network_topology_device_info` need `LAB_TOPOLOGY_EXPORTER=1` + `make topology-up`.)

**One-shot local + Grafana check:**

```bash
make -C local snmp-check    # TARGETS vs live IPs, snmpget, poller logs, Grafana SNMP series
```

**Local sanity checks:**

```bash
make -C local status
docker ps --format 'table {{.Names}}\t{{.Status}}' | grep -E 'spine|leaf|client|ktranslate|alloy|gnmic'
```

Expect **11** running containers (5 fabric + 6 collectors) when healthy. With optional `topology_exporter`: **12**.

### Troubleshooting (agent decision tree)

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `make check` fails on placeholders | `.env` not customized | User must paste OTLP creds |
| `Permission denied` on `./scripts/*.sh` | Git does not mark shell scripts executable on fresh clone | Fixed in repo: Makefile/scripts invoke `bash scripts/...`. Pull latest `main`. |
| `make check` fails containerlab | Not installed | macOS: `brew install containerlab`; Linux: [containerlab.dev/install](https://containerlab.dev/install/) |
| `compute-limits.sh` / memory error | Unusual host RAM detection | Set `MEM_LIMITS=off` in `.env`, re-run `make up` |
| SRL container **exit 143** | SIGTERM (sleep, `make down`, `clab --reconfigure`, Docker Desktop stop) — **not OOM** | `make -C local stabilize`; never `clab deploy --reconfigure` |
| BGP/EVPN/SNMP missing after deploy | Fabric config not applied or postdeploy race | `make -C local fabric-apply` or `make stabilize`; confirm repo is on **WSL ext4**, not `/mnt/c` |
| `leaf1` stuck / yang reload | Fabric boot race | Wait; or `docker restart leaf1` then `make stabilize` |
| No flows in Grafana | **softflowd target IP stale** after `ktranslate_flow` recreate (clab IP drift), softflowd not running, or wrong PromQL (`rate()` on rollup) | Agent: compare `docker exec client1 pgrep -a softflowd` `-n` IP vs `docker inspect ktranslate_flow` clab IP; `make -C local softflowd` + `make traffic`; wait ~90s; verify `count(network_io_by_flow_bytes)` |
| SNMP looks empty in Grafana but poller healthy | Wrong PromQL (`kentik_snmp_DeviceMetrics` does not exist) or MCP on different stack than lab | `make snmp-check`; use `count by (device_name) (kentik_snmp_CPU)` — see [Metric names](#metric-names--promql-ktranslate-otlp-path) |
| ktranslate SNMP `connection refused` on :161 | Stale device IP **or** SNMP agent down on mgmt NI | `make snmp-check` (compare TARGETS vs live clab IPs); if IPs drifted: `make snmp-recover`; if snmpget times out: `bash scripts/enable-snmp-srl.sh` |
| `FULL_FABRIC=1` / broken `apply-fabric-node` | Can wedge `net_inst_mgr` or wipe mgmt NI | **Do not** set unless user asks; prefer `make fabric-apply` (SNMP-only path) or `make down && make up` |
| Discovery permission error | `config/` / `state/` ownership | `sudo chown -R 1000:1000 config state` (Linux/WSL) |
| GHCR pull denied (topology_exporter) | Image auth | `LAB_TOPOLOGY_EXPORTER=1` + `make -C local topology-exporter-image` + `make topology-up` |

**Recovery command of first resort:** `make -C local stabilize` (starts stopped SRL nodes, applies fabric, discover, sidecar configs — no full clab redeploy).

**After clab IP drift or `clab deploy --reconfigure`:** stabilize alone may leave **stale SNMP targets**. Run `make snmp-recover` then `make finish-flows`.

### Investigation playbook — SNMP & flows (do not start from scratch)

**Run diagnostics before guessing OTLP or dashboard bugs:**

| Symptom | First command | What it tells you |
|---------|---------------|-------------------|
| "SNMP broken" | `make -C local snmp-check` | TARGETS vs live `clab` IPs, `snmpget`, `state/devices-srl.yaml`, poller logs, Grafana `kentik_snmp_*` count |
| "No flows" | Agent runs `make -C local softflowd` + `make traffic` (or `finish-flows` if EVPN/fabric suspect) | Compare softflowd `-n` IP vs `ktranslate_flow` clab IP; then Grafana `count(network_io_by_flow_bytes)` |
| "Containers keep dying" | `make -C local lab-log-status` | `state/lab-actions.log` (our scripts) + `docker-events.log` (which container stopped) |

**Decision tree (SNMP):**

1. **`snmp-check` → snmpget works, Grafana has `kentik_snmp_*`** → SNMP is fine. User likely queries `kentik_snmp_DeviceMetrics` or an AWS `integrations/snmp` dashboard. Retarget panels or use lab dashboards under `local/.dash-payloads/`.
2. **`snmpget` fails, TARGETS ≠ live clab IPs** → IP drift after clab redeploy. `make snmp-recover` (`finish-bringup.sh`: refresh TARGETS → discover → reload poller).
3. **`snmpget` fails, IPs match, `connection refused` in poller logs** → SNMP agent on device. `bash scripts/enable-snmp-srl.sh`; confirm `oper-state up` on `system snmp network-instance mgmt`.
4. **snmpget works, Grafana empty, flows present** → stack mismatch (lab `.env` `GC_OTLP_*` vs Grafana MCP token) or Alloy down. Verify `GC_OTLP_*`; `docker logs alloy --tail 50`.

**Decision tree (flows):**

1. **`count(network_io_by_flow_bytes)` > 0** → flows OK; dashboard may use wrong metric or `rate()`.
2. **No series** → check softflowd collector IP first (common after `ktranslate_flow` / `make ktranslate-dev-recreate`):
   - `docker inspect ktranslate_flow` → clab IP; `docker exec client1 pgrep -a softflowd` → `-n <ip>:9995`
   - Mismatch → `make -C local softflowd` + `make traffic`; wait ~90s for 60s rollup.
3. **softflowd IP OK but still empty** → `docker exec client1 ip link show eth1` (missing after partial restart); `make -C local finish-flows`.
4. **EVPN ICMP ping fails** (`client2` cannot ping `172.17.0.1`) **but UDP iperf may still work** — do not treat ping alone as "no flows". If no traffic at all: `make fabric-apply` or `make finish-flows`.

**Container exit 143:** SIGTERM, not OOM (`OOMKilled=false`). Common causes: `clab deploy --reconfigure`, `make down`, Docker Desktop Resource Saver, staggered collector restarts. `journalctl -u docker` may show `hasBeenManuallyStopped=true`. Do not treat as memory pressure.

### Metric names & PromQL (ktranslate OTLP path)

ktranslate exports **per-metric OTLP names** (dots → underscores in Prometheus). There is **no** `kentik_snmp_DeviceMetrics` series on this path.

| Check | PromQL |
|-------|--------|
| SNMP devices up | `count by (device_name) (kentik_snmp_CPU)` → spine1, leaf1, leaf2 |
| SNMP volume | `count({__name__=~"kentik_snmp.*"})` (expect hundreds of series) |
| Poll health | `kentik_snmp_PollingHealth` |
| Interface bps | `(kentik_snmp_ifHCInOctets{device_name="$device"}) * 8 / 60` — **not** `rate(...)` |
| Flow conversations | `count(network_io_by_flow_bytes)` |
| Flow throughput (bps) | `sum(network_io_by_flow_bytes) * 8 / 60` |

**Dashboard trap:** Commvault / AWS **01. Network Device Details** and similar boards query `kentik_snmp_DeviceMetrics` and `rate(kentik_snmp_ifHC*Octets[…])`. Those panels stay empty until retargeted (see [Grafana dashboard updates](#grafana-dashboard-updates--preserve-tabslayout-v2-manifest-path)).

**Grafana Cloud MCP:** `query_prometheus` needs `endTime` (e.g. `"now"`). MCP may authenticate to a **different** stack than the lab — confirm against `GRAFANA_URL` / `GC_OTLP_*` in `local/.env`, or use `snmp-check` / `finish-flows.sh` (they query via `.env`).

### SNMP diagnosis (SRL up but empty Grafana)

**Symptom:** devices look healthy in `docker ps`, but Explore has no `kentik_snmp_*` and ktranslate logs show `recvfrom: connection refused` on UDP 161.

**Check locally first** (do not assume OTLP/stack misconfig until SNMP works):

```bash
# From WSL — community public matches groups/srl.env
snmpget -v2c -c public -t 2 172.20.20.2:161 1.3.6.1.2.1.1.5.0   # spine1

docker exec spine1 sr_cli -ec 'info from state system snmp network-instance mgmt' | grep oper-state
# expect: oper-state up

docker logs srl-local-telemetry-ktranslate_snmp_srl-1 --tail 20
```

| `oper-state` / symptom | Cause | Fix |
|------------------------|-------|-----|
| `down`, empty `error-msg` | `ag1` missing `community-entry ce1 community public` | `bash scripts/enable-snmp-srl.sh` (deletes clab `SNMPv2-RO-Community`, sets `ag1`/public) |
| grpc/snmp: `Network instance 'mgmt' does not exist` | `network-instance mgmt` wiped (often after `FULL_FABRIC=1`) | `bash scripts/restore-mgmt-ni.sh` then `enable-snmp-srl.sh`; if still wedged: `make down && make up` |
| `yang reload` / commit failures | Fabric boot race or partial apply | Wait; `docker restart <node>`; then `make stabilize` |

**Fabric contract:** `configs/fabric/*.cfg` must include **`network-instance mgmt`** (type `ip-vrf`, `mgmt0.0`, linux protocol) and **`system snmp access-group ag1 community-entry ce1 community public`**. `make fabric-apply` (default) pipes only SNMP via `enable-snmp-srl.sh`; full flat config requires `FULL_FABRIC=1` and is risky on a running lab.

**Verify in the operator's stack** (after SNMP polls for ~1–2 min):

```promql
count by (device_name) (kentik_snmp_CPU)
count({__name__=~"kentik_snmp.*"})
```

(`kentik_snmp_DeviceMetrics` does **not** exist on the ktranslate path — empty result there is not a failure.)

### Agents on Windows (Cursor host)

| Do | Do not |
|----|--------|
| Run lab commands via `wsl -e bash -lc 'cd ~/projects/network-o11y-demo/local && …'` | Inline bash `for` loops / `$var` in the **outer** PowerShell string — `$n`, `$ip` get eaten |
| Use repo scripts: `bash scripts/enable-snmp-srl.sh` | Long one-liners with nested quoting through `wsl -e bash -lc "…"` |
| Sync edits to the WSL clone when changing files on `C:\…` | Assume `~/network-o11y-demo` picked up Windows-side edits automatically |
| Strip CRLF before running new shell scripts: `sed -i 's/\r$//' scripts/foo.sh` | Run freshly written `.sh` from Windows without LF check (`set: pipefail\r: invalid option`) |
| Confirm `GC_OTLP_URL` / account in `local/.env` match the stack the user asked about | Assume Grafana Cloud MCP is on the same stack as the lab (MCP may be a different org) |

**WSL clone sync** (after editing on Windows):

```bash
cp -r /mnt/c/Users/<you>/projects/network-o11y-demo/local/configs/fabric ~/network-o11y-demo/local/configs/
cp /mnt/c/Users/<you>/projects/network-o11y-demo/local/scripts/*.sh ~/network-o11y-demo/local/scripts/
```

### Optional next steps (only if user asks)

| Goal | Command |
|------|---------|
| SNMP diagnostic (IPs, snmpget, Grafana) | `make -C local snmp-check` |
| SNMP recovery after clab IP drift | `make -C local snmp-recover` |
| Flow recovery (EVPN, softflowd, traffic, verify) | `make -C local finish-flows` |
| Container stop audit trail | `make -C local lab-log-status` |
| App↔network join demo traces | `make -C local join-app` |
| Latency fault talk-track | `make -C local join-fault` / `join-fault-stop` |
| Synthetic traps + link flaps | `make -C local events-loop` |
| Import join dashboard | `python3 local/scripts/build-network-join-demo.py` then import script with user's `GRAFANA_URL` + token |
| NetBox-driven discovery | `cp groups/srl.env.netbox.sample groups/srl.env`, set `NETBOX_*` in `.env`, `make netbox-sync && make up` |

### Grafana Cloud MCP

If MCP is available, authenticate to the **operator's** stack (same as `GRAFANA_URL` / `GC_OTLP_*`). Use it to run verification PromQL and generate Explore deeplinks — do not assume a specific stack name in docs or queries.

### Grafana dashboard updates — preserve `TabsLayout` (v2 manifest path)

**Full playbook:** [`docs/grafana-dashboard-playbook.md`](docs/grafana-dashboard-playbook.md) — UID migration, legends, heights, marcnetterfield reorg, HTTP v2 when gcx is unavailable.

**Operator PromQL patterns:** [`local/docs/dashboard-query-lessons.md`](local/docs/dashboard-query-lessons.md) — diff tool: `local/scripts/_compare-dashboard-live.py`.

**Hard rule:** **Pull the live dashboard manifest before any edit.** Never push from stale `local/.dash-payloads/` or re-apply hand-rolled queries the operator already fixed in Grafana Assistant. After live edits, update patch scripts only when `_compare-dashboard-live.py` shows the script matches live.

**Audience:** agents patching or importing ktranslate / Network O11y dashboards on Grafana Cloud.

Grafana **v2** dashboards (generation ≥ 2, `spec.layout.kind: TabsLayout`) store tabs in the **App Platform manifest**, not in classic `dashboard.panels` JSON. Updating them through the **legacy** API **flattens tabs into one long scroll** — we hit this on Commvault Device Details (restored from version history).

| Path | Safe for tabbed v2 dashboards? | When to use |
|------|-------------------------------|-------------|
| `gcx dashboards get` → edit manifest → `gcx dashboards update` | **Yes** | Preferred when `gcx --context <stack>` is configured |
| v2 HTTP `GET`/`PUT` on `dashboard.grafana.app/v2` | **Yes** | `GRAFANA_URL` + `GRAFANA_TOKEN` in `local/.env` (WSL without gcx context) |
| `local/scripts/reorganize-marcnetterfield-dashboards.py` | **Yes** | Pull / renumber / friendly UID migration on marcnetterfield1 |
| `local/scripts/patch-iface-bps-fleet.py` | **Yes** | Fleet interface BPS rewrites |
| `gcx assistant dashboard` / `gcx assistant prompt` | **Yes** (OAuth) | New panels/rows — prefer over hand-built JSON; then pull manifest |
| `local/scripts/patch-flow-dashboard-sections.py` | **Yes** | Flow Summary scripted rows (country, transport) |
| `POST /api/dashboards/db` with `{ "dashboard": { ...panels... } }` | **No** on v2 tabbed boards | One-shot **first import** of classic JSON only; never re-save tabbed dashboards this way |
| `local/scripts/patch-iface-bps-60s.py` (legacy HTTP) | **No** on tabbed boards | Avoid; kept for `rewrite_expr()` helper only |
| `local/scripts/audit-commvault-bps.py` | **No** | Deprecated — strips `TabsLayout` |

**Canonical workflow (gcx + v2 manifest):**

```bash
# 1) Read full manifest (note layout.kind)
gcx --context <stack> --agent dashboards get <uid> -o json > /tmp/dash.json

# 2) Patch spec.elements[*].spec (queries, descriptions, etc.) — not top-level panels[]
#    Example: interface bps — rate(kentik_snmp_ifHC*Octets[$__rate_interval])*8
#             → (kentik_snmp_ifHC*Octets{...}) * 8 / 60  (ktranslate delta gauges, 60s poll)

# 3) Write back via v2 update
gcx --context <stack> --agent dashboards update <uid> -f /tmp/dash.json

# 4) Verify layout survived
gcx --context <stack> --agent dashboards get <uid> -o json \
  | jq '.spec.layout.kind'    # expect "TabsLayout" when started as TabsLayout
```

**marcnetterfield1 ktranslate set** (`local/.dash-payloads/marcnetterfield-live/`, gitignored):

```bash
# Pull all 00–04 + refresh agent docs (after UI/Assistant edits)
python3 local/scripts/sync-ktranslate-dashboards-live.py --pull

# Manifests only
python3 local/scripts/reorganize-marcnetterfield-dashboards.py pull
python3 local/scripts/reorganize-marcnetterfield-dashboards.py plan    # stage + inspect reorg/
python3 local/scripts/reorganize-marcnetterfield-dashboards.py apply --delete-legacy
```

Committed agent references: `docs/grafana-network-dashboard-design-patterns.md`, `docs/grafana-network-dashboard-expand-hardware.md`, `docs/grafana-network-dashboard-skills-README.md` (portable — recommend for any stack); `local/docs/dashboard-query-lessons.md`, `local/docs/ktranslate-dashboard-live-snapshot.md` (this lab).

UID migration: v2 cannot rename `metadata.name` on PUT (400). Create new UID via POST **without** `deprecatedInternalID` or `resourceVersion`; delete legacy UID after UI check. See playbook § UID migration.

**Legends / heights:** do not blank existing `legendFormat` (`{{if_interface_name}}`, `__auto`, etc.). Only fill empty legends when a panel has 2+ queries with missing formats. Trim oversized text panels (~10 grid units); bump charts below ~8 — avoid half-page whitespace and dashboard-level scroll on normal monitors.

**Fleet helper (interface BPS on kentik SNMP):**

```bash
# Dry-run scan (discovers ktranslate/network-lab dashboards on the stack)
python3 local/scripts/patch-iface-bps-fleet.py <gcx-context> --dry-run

# Patch explicit UIDs (live)
python3 local/scripts/patch-iface-bps-fleet.py networko11ydev ktranslate-device-summary ktranslate-device-details
python3 local/scripts/patch-iface-bps-fleet.py marcnetterfield1 ktranslate-device-summary net-o11y-traffic-sankey
```

Reports: `local/.dash-payloads/bps-v2-patch-report-<context>.json`. Shared query rewrite: `rewrite_expr()` in `local/scripts/patch-iface-bps-60s.py`.

**Post-patch checklist:**

1. `spec.layout.kind` unchanged (`TabsLayout` vs `RowsLayout` / `GridLayout`).
2. `metadata.generation` incremented (update actually landed).
3. UI spot-check: e.g. **04. Network Device Details** still shows all tabs (Interfaces, BGP, …), not one flattened page.
4. Legends readable on multi-series panels; no accidental blank `legendFormat` overwrites.
5. Panel heights: no half-page empty markdown; charts not cramped below ~8 grid units.
6. For BPS panels: no remaining `rate(kentik_snmp_ifHCInOctets` / `ifHCOutOctets` in the manifest.

**If tabs were already flattened:** restore a pre-patch dashboard **version** in Grafana UI (Dashboard settings → Versions), then re-apply patches with the v2 path above.

**MCP note:** prefer read-only MCP (`get_dashboard_summary`, PromQL) for verification. For writes on tabbed v2 dashboards, use **gcx v2** until you have confirmed your MCP `patch_dashboard` / `update_dashboard` path preserves `TabsLayout` (legacy-shaped payloads are unsafe).

**Grafana Assistant:** `gcx login` then `gcx assistant dashboard "…"` or GUI Assistant for dashboard design. Requires OAuth — not the SA token in `.env`. After Assistant edits, run `python3 local/scripts/sync-ktranslate-dashboards-live.py --pull` (all ktranslate boards) or `download-flow-dashboard.py` (flow only).

**Flow Summary (`ktranslate-flow-summary`):** RowsLayout; live JSON in `.dash-payloads/marcnetterfield-live/`. Use `max_over_time` on `network_io_by_flow_bytes` (not `rate()`). Keep IP + `src_host`/`dst_host` in group-by; country panels must match geomap filters (`network_peer_country!~"Private IP|undefined"`). North-south geomap traffic: client mgmt `172.20.20.*` + `make internet-probes`. Full playbook: [`docs/grafana-dashboard-playbook.md`](docs/grafana-dashboard-playbook.md) § Grafana Assistant · § Flow Summary dashboard.

## Local lab (current phase)

- **Topology:** 1 spine (`spine1`) + 2 leaves (`leaf1`, `leaf2`) + 2 clients (`client1`, `client2`); all SR Linux `ixrd2l`
- **Talk track:** eBGP underlay + EVPN MAC-VRF; clients `172.17.0.1` / `172.17.0.2`
- **Collectors:** `ktranslate_snmp_srl` (golden-path poller), `ktranslate_flow`, `ktranslate_syslog`, **`gnmic`** (incl. LLDP neighbors). Optional: **`topology_exporter`** (`LAB_TOPOLOGY_EXPORTER=1`, `make topology-up`)
- **NetBox Cloud (optional):** `scripts/netbox-populate.py` + `update-netbox-mgmt-ips.py` when `DISCOVERY_SOURCE=netbox` in `groups/srl.env` (`groups/srl.env.netbox.sample`). Default bring-up uses **CIDR** discovery (`groups/srl.env.sample`). See `local/netbox/README.md`.
- **ktranslate model:** [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) golden path — `groups/*.env` → `make generate` → discovery/polling split (`discover_srl` profile + read-only poller). No root `snmp.yaml` + `snmp_discovery_on_start`
- **SNMP profiles:** bundled in the ktranslate image from [kentik/snmp-profiles](https://github.com/kentik/snmp-profiles). Discovery matches `sysObjectID` → `mib_profile` automatically (e.g. Nokia SR Linux → `nokia-srlinux.yml`). Missing platform? [Profile tutorial](https://github.com/kentik/ktranslate/wiki/Tutorial:-Writing-a-custom-yaml-file-for-SNMP) → PR upstream — do not bind-mount local profile overrides in normal bring-up.
- **Alloy role:** OTLP receive + Docker log scrape (lab containers except ktranslate) → preprocess → OTLP HTTP to Grafana Cloud. ktranslate already tees its own logs (and device syslog/traps) over OTLP via `--tee_logs=true`.
- **Topology graph:** LLDP edges via **gnmic** → Alloy remap → `network_topology_edge_info`. Optional **topology_exporter** (off by default) adds SNMP `network_topology_device_info` + BGP walkers
- **Topology exporter image:** only when enabled — `make -C local topology-exporter-image` then `make topology-up`
- **Deferred:** Ansible, full 2-spine/3-leaf Clos, local LGTM stack

### Bring-up (macOS or WSL/Linux)

```bash
cd local
cp .env.example .env          # set GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY
cp groups/srl.env.sample groups/srl.env
make generate
# Linux/WSL only: sudo chown -R 1000:1000 config state
make up
make traffic
```

**macOS:** `brew install containerlab yq gettext`; Docker Desktop **10–12 GB** RAM.
Set OTLP creds in `.env` or `python3 scripts/retarget-otlp-gc.py --write`. Apple Silicon
uses amd64 emulation — slower but supported. See `local/README.md` → macOS quick reference.

**WSL (Windows):** clone inside WSL on ext4 (`git clone … ~/projects/network-o11y-demo`). Do **not** run the lab from `/mnt/c/...` — ContainerLab cannot reliably commit SR Linux config on drvfs. Agents on Windows invoke WSL explicitly, e.g. `wsl -e bash -lc 'cd ~/projects/network-o11y-demo/local && make up'`, or use `.\oneclick\deploy.ps1`.

`make up` **staggers** fabric sr_cli readiness and collectors with `LAB_STAGGER_SECS`
(default 25) pauses. Use `make up-parallel` or `LAB_STAGGER=0` to disable.
`make stabilize` honors `LAB_STAGGER` for collector bring-up.

Optional NetBox Cloud discovery: `cp groups/srl.env.netbox.sample groups/srl.env`, set `NETBOX_*` in `.env`, then `make generate && make netbox-sync && make up`.

From repo root: `make local-up` / `make local-down` / `make local-help`.

Agents on Windows must use a WSL ext4 checkout — e.g. `wsl -e bash -lc 'cd ~/projects/network-o11y-demo/local && make up'`.

### Operational gotchas

1. **ContainerLab mgmt network is `clab`** (v0.72+ shared bridge), not `srl-local`. Set `CLAB_NETWORK=clab` in `.env`.
2. **Shell scripts must be LF** (CRLF breaks `set -o pipefail`). `.gitattributes` forces LF under `local/`.
3. **Alloy comments are `//`**, not `#`.
4. **`state/devices-*.yaml` is mutable** (discovery writes device lists); never commit `config/` / `state/` / `groups/*.env`. UID 1000 must own `config/` and `state/`.
5. **Syslog / SNMP traps:** pipe into `sr_cli` via `docker exec -i` (non-interactive); see `local/scripts/syslog-config.sh` and `snmp-trap-config.sh`. Both must use **mgmt** (`system logging network-instance mgmt`, trap-group `network-instance mgmt`) or packets never leave the box. **Traps go to the SNMP poller** (`ktranslate_snmp_srl`, UDP `:1620` — same container as polling, not a separate ktranslate). One-shot: `make -C local emit-events`. Periodic: `make -C local events-loop` (synthetic traps ~3m, real flaps ~5m; `events-stop` / `events-status`).
6. **Windows / WSL:** clone and run the lab **only** on WSL native ext4 (`~/…`), never `/mnt/c/…`. drvfs breaks ContainerLab postdeploy for SR Linux startup config. **Do not** run `clab deploy --reconfigure` unless the user explicitly asks — it SIGTERM-stops all lab containers (exit 143), which looks like a crash but is not OOM.
7. **SNMP on mgmt:** fabric cfg + `enable-snmp-srl.sh` must set `network-instance mgmt` and `access-group ag1` + `community-entry ce1 community public`. Without both, SNMP/gNMI stay `oper-state down` and ktranslate gets `connection refused` on :161 — devices can look "up" while Grafana has no `kentik_snmp_*`. See playbook **SNMP diagnosis**.
8. **Recovery without redeploy:** `make -C local stabilize` — `docker start` stopped SRL nodes, apply fabric, NetBox sync, discover, softflowd/syslog/traps. Not a memory issue: SRL exits with code 143 (SIGTERM), `OOMKilled=false`.

### Metrics to expect in Grafana Cloud

| Stream | PromQL / check |
|--------|----------------|
| SNMP | `count by (device_name) (kentik_snmp_CPU)` → spine1, leaf1, leaf2; `count({__name__=~"kentik_snmp.*"})` for volume. **Not** `kentik_snmp_DeviceMetrics`. Alloy stamps `site` (`hq` on laptop; `hq`/`branch1`/`branch2` colocated) and `device_role` (`spine`/`leaf`/`branch-edge`) on `kentik_snmp_*`. |
| NetFlow | `count(network_io_by_flow_bytes)`; throughput `sum(network_io_by_flow_bytes) * 8 / 60` — **not** `rate(network_io_by_flow[…])` |
| Syslog | OTLP logs via ktranslate `--tee_logs` (`service_name` ≈ `ktranslate`, `tags.container_service=syslog`) |
| Docker stdout | Alloy `loki.source.docker` → OTLP (`collector=docker`, `service_name` = container: `topology_exporter`, `spine1`, …). ktranslate containers skipped (already teed) |
| gNMI | `{job="gnmic"}` — OTEL metric names often use `:` separators, e.g. `gnmi_bgp_neighbors_…:bgp_neighbor_session_state` |
| Topology devices | `network_topology_device_info{tester_id="network-lab"}` — `site` label `hq` (laptop) or `hq`/`branch1`/`branch2` (colocated) |
| Topology edges | `network_topology_edge_info{tester_id="network-lab"}` (gnmic LLDP → Alloy remap) |
| Mgmt API catalog | `srl_mgmt_api_capability_info{tester_id="network-lab"}` — live APIs (`enabled_in_lab="true"`) plus **mock** entries for documented APIs not turned on in the lab (NETCONF, JSON-RPC, gNOI, gRIBI). Catalog: `local/fixtures/srl-mgmt-api-catalog.json`; samples: `local/fixtures/srl-mock/`. Re-export: `make -C local mgmt-api-mock`. |
| Flex gap-fill (optional) | `srl_flex_poc_ssh_up` / `srl_flex_poc_bgp_peers_up` from `make -C local telegraf-poc` (SSH + jq parse → OTLP; nri-flex analog — `local/telegraf-flex-poc/`) |

**SR Linux management plane (lab vs platform):** devices expose northbound APIs on **`network-instance mgmt`** (ContainerLab `clab` bridge). **Enabled here:** gNMI `:57400` (gnmic), SNMP, syslog, traps, sFlow. **Not enabled but catalogued with mock fixtures:** NETCONF `:830`, JSON-RPC HTTPS `/jsonrpc`, gNOI/gRIBI (gRPC, same port as gNMI). See `local/fixtures/README.md`.

Dashboards under [`grafana/dashboards/`](grafana/dashboards/) were authored for the **AWS** lab (`integrations/snmp`, gNMI). Many panels will be empty against the local ktranslate path until queries are retargeted. Folder in GC (if imported): **Network Lab** (`network-lab`).

Topology dashboards (adapted for this lab):

| UID | Title |
|-----|-------|
| `lab-topology-graph` | Network Topology (topology-exporter) |
| `lab-topology-health` | Topology Exporter Health |
| `lab-ktranslate-flow` | Network Flow Summary (ktranslate) — `network_io_by_flow_bytes` from softflowd + spine sFlow |
| `lab-network-join-demo` | Network join demo (SIG model) — flows + LLDP subway + SNMP errors/CPU |

JSON payloads: `local/.dash-payloads/topology/`, `local/.dash-payloads/network-join-demo.json`, `local/.dash-payloads/ktranslate-import/lab-ktranslate-flow.json`. Skip `topology-schedule` (long-running mutator harness only).

**Ktranslate dashboards (marcnetterfield1 / Network Lab folder):** friendly UIDs, numbered 00–04. **Playbook:** [`docs/grafana-dashboard-playbook.md`](docs/grafana-dashboard-playbook.md). Re-pull and re-apply: `python3 local/scripts/reorganize-marcnetterfield-dashboards.py pull|plan|apply` (v2 API — preserves `TabsLayout`).

| # | UID | Title |
|---|-----|-------|
| 00 | `ktranslate-architecture` | Ktranslate Architecture |
| 01 | `ktranslate-health` | Ktranslate Health (CHF / jchf) |
| 02 | `ktranslate-flow-summary` | Network Flow Summary |
| 03 | `ktranslate-device-summary` | Network Device Summary |
| 04 | `ktranslate-device-details` | Network Device Details (TabsLayout) |

**Architecture guide (KtransToGrafana):** UID `ktranslate-architecture` (**00.**). Re-sync text panels from upstream docs: `python3 local/scripts/build-ktrans-arch-dashboard.py --context <gcx-context>` (gcx v2 manifest path — preserves `GridLayout`).

**Collector health (ktranslate CHF / jchf):** UID `ktranslate-health` (**01.**). Maps [New Relic container health](https://docs.newrelic.com/docs/network-performance-monitoring/advanced/ktranslate-container-health/) metrics to OTLP names (`kentik_ktranslate_chf_kkc_*`). Facet by **`service_name`** (`ktranslate-snmp-*`, `ktranslate-flow-*`, `ktranslate-sflow-*`, `ktranslate-syslog-*`). Patch script: `python3 local/scripts/patch-ktranslate-health-dashboard.py` (v2 TabsLayout-safe). Flow **rollups** carry datapoint label `integration=ktranslate-netflow` (Alloy does not rewrite resource `service.name`). Each ktranslate container sets its own `OTEL_SERVICE_NAME`. **Upstream fix (pending):** [Mesverrum/ktranslate `fix/otel-chf-flow-only`](https://github.com/Mesverrum/ktranslate/tree/fix/otel-chf-flow-only). **Local test image until merge:** `make -C local ktranslate-dev-image` → `KTRANSLATE_IMAGE=srl-local/ktranslate:otel-chf-dev` in `.env` → `make -C local ktranslate-dev-recreate`. Verify: `bash local/scripts/verify-chf-grafana.sh`.

**Flow dashboard:** UID `lab-ktranslate-flow` (local lab) or `ktranslate-flow-summary` (marcnetterfield1). Adapted from the ktranslate **02. Network Flow Summary** pattern. Rebuild/import lab copy: `python3 local/scripts/build-ktranslate-flow-dashboard.py` then `python3 local/scripts/import-ktranslate-flow-dashboard.py` (prefers `gcx --context networko11ydev`). Pull live Assistant edits: `python3 local/scripts/download-flow-dashboard.py`. Patch helpers: `patch-ktranslate-flow-dashboard.py`, `patch-flow-dashboard-sections.py`, `verify-flow-countries.py`. Playbook: [`docs/grafana-dashboard-playbook.md`](../docs/grafana-dashboard-playbook.md) § Flow Summary dashboard.

**Join demo:** UID `lab-network-join-demo`, folder `network-lab`. Section **0** pairs Tempo `clos-join-demo` spans with softflowd flows on shared `$peer_addr`/`$peer_port` (default `172.17.0.2:8080`). Rebuild/import: `python3 local/scripts/build-network-join-demo.py` then `python3 local/scripts/import-network-join-demo-gcx.py` (or `import-network-join-demo.sh` with `GRAFANA_URL` + `GRAFANA_TOKEN`). After `ktranslate_flow` recreate, agent runs `make -C local softflowd` (also automatic after `make ktranslate-dev-recreate`).

**Clos join app (phase 2 traces):** minimal OTel Go HTTP client/server on EVPN clients — `make -C local join-app` (`local/join-app/`, `scripts/join-app.sh`). client1 `172.17.0.1` → client2 `172.17.0.2:8080` over the Clos; traces → Alloy `:4317` as `service.name=clos-join-demo` with `network.peer.*` / `server.address` for 5-tuple join vs softflowd (`network_peer_port="8080"`). Also exports `clos_join_entity_info` / `clos_join_edge_info` for the dashboard subway overlay (`runs_on` / `attached`). Stop: `make -C local join-app-stop`. Talk-track fault: `make -C local join-fault` / `join-fault-stop` (`scripts/join-fault.sh` — tc netem on client `eth1`); Investigation row on `lab-network-join-demo`. **Identity tabs:** parallel `entity_demo_*` datasets (`demo_model=hostname|hostname_poison|mac_alias|address|iface|edge_attrs|vrf`) prove/disprove OTel entity open questions — Q3: attrs-on-edge vs MAC-VRF as `network.vrf`.

**OTLP / Grafana Cloud:** copy `local/.env.example` → `local/.env` and set `GC_OTLP_URL`, `GC_OTLP_ACCOUNT`, `GC_OTLP_KEY` from your stack's OpenTelemetry connection. Optional `LAB_TESTER_ID` (default `network-lab`) labels topology and entity metrics. Merge helper: `python3 local/scripts/retarget-otlp-gc.py --write`. Restart Alloy after changing OTLP env: `docker compose … up -d --force-recreate alloy` (or `make up`).

## AWS / EKS path (unchanged)

See root [`README.md`](README.md) and `make post-03` … `post-06`. Uses Clabbernetes, Alloy SNMP exporter historically, gnmic, NetBox, Ansible. Do not mix those collector assumptions into `local/` work.

## Secrets — never commit

- `local/.env`, `local/groups/*.env`, `local/state/`, `local/config/`
- `k8s/telemetry/grafana-cloud-secret.yaml`, `grafana-cloud-api.token`, `grafana-cloud.instance`
- Terraform `*.tfvars`, AWS keys

## Grafana Cloud MCP

If the Grafana Cloud MCP server is available and authenticated, prefer it for Explore queries and deeplinks. Point MCP at **your** Grafana Cloud stack (the same one as `GRAFANA_URL` / `GC_OTLP_*` in `local/.env`).

**Dashboard writes on tabbed v2 boards:** use the [**v2 manifest / gcx path**](#grafana-dashboard-updates--preserve-tabslayout-v2-manifest-path) (`dashboards get` → edit `spec.elements` → `dashboards update`). Do **not** use `POST /api/dashboards/db` or legacy patch scripts on `TabsLayout` dashboards.

## Blog / docs map

Series outline: [`blog/blog-series-overview.md`](blog/blog-series-overview.md). Local lab does not yet map 1:1 to every post (posts 3–6 assume K8s/NetBox/Ansible).

## Agent maintenance rule

When a session changes bring-up, topology, collectors, network names, or metric contracts, update:

1. This file (`AGENTS.md`)
2. Relevant `.cursor/rules/*.mdc`
3. [`local/README.md`](local/README.md) if operator-facing steps changed
