# NetBox for the network-o11y lab

SNMP discovery works **without NetBox** (`DISCOVERY_SOURCE=cidr`). Use NetBox when you want
inventory-driven discovery, Orb/Diode ingest demos, or SoT → Grafana validation.

## Preferred: NetBox on AWS colocated (self-contained)

Runs on the same EC2 host as ContainerLab + k3s collectors — **no laptop dependency**.

**Public UI (home IP and/or Grafana Cloud lab access):**  
http://network-o11y-netbox-ui-383fcaf9622d867c.elb.us-east-1.amazonaws.com:8000/  

Login: **`admin` / see `NETBOX_ADMIN_PASSWORD` in `local/.env`** (not `admin/admin`).  
Rotate: `python3 local/scripts/rotate-netbox-admin-password.py`  

SG: set `netbox_ui_cidrs` (home `/32`) and/or `netbox_ui_allow_grafana_cloud = true` in terraform so Grafana Cloud Infinity can reach the API. API access still requires `NETBOX_TOKEN`.

```bash
make -C local netbox-colocated   # NetBox OSS + Diode plugin + Diode + live Orb
```

| | |
|--|--|
| UI | public NLB `:8000` (above) or SSM tunnel |
| Path on host | `/opt/network-o11y-demo/local/netbox-oss/netbox-docker/` |
| Diode | `/opt/diode/` (`grpc://127.0.0.1:8080/diode`) |
| Orb | live Diode ingest + OTLP to Alloy `:4317` |

### What lands in Grafana Cloud

| Signal | Where it shows |
|--------|------------------|
| NetBox SoT (live REST) | Infinity datasource `netbox-api` on dashboards 20 / 22 / 24 / 25 |
| Orb agent OTLP | metrics with `deployment_host=orb-agent` / `collector=orb` |
| Lab SNMP (unchanged) | `kentik_snmp_*` from ktranslate — **not** from Orb |

Orb SNMP discovery feeds **NetBox** (via Diode), not `kentik_snmp_*`. Grafana Cloud reads NetBox **live** through Infinity (no inventory-OTLP sidecar). Device changelog/journal in NetBox is the inventory audit trail; a Prometheus recording rule is optional if someone later wants Grafana-side history of those counts.

## Option B — NetBox OSS on laptop (heavy; avoid if RAM-constrained)

```bash
make -C local netbox-oss-up
make -C local netbox-sync
```

## Option C — NetBox Cloud

See earlier Cloud trial notes; set `NETBOX_*` in `.env` and `groups/srl-hq.env.netbox.sample`.

## Enable NetBox-driven ktranslate SNMP discovery (optional)

After NetBox has devices (Orb ingest or `make netbox-sync`):

```bash
# On colocated: point groups at NetBox API, then rediscover
cp groups/srl.env.netbox.sample groups/srl-hq.env   # adjust NETBOX_* URLs for 127.0.0.1:8000
make generate && COLLECTOR_RUNTIME=k3s bash scripts/run-colocated-discovery.sh
```

## Scripts

| Target | Purpose |
|--------|---------|
| `make netbox-colocated` | AWS: NetBox + Diode + live Orb (Grafana reads NetBox via Infinity) |
| `make netbox-ui-tunnel` | SSM port-forward UI to laptop |
| `make netbox-oss-up` / `down` | Laptop sidecar only |
| `make netbox-populate` / `sync` | Seed / mgmt IP sync (API) |
| `make orb-colocated` | Orb only (dry-run or live if Diode creds set) |
