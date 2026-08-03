# Colocated network lab (reference AWS deployment)

**Fabric:** ContainerLab on EC2 — **HQ hub + two branch offices** (`topology-colocated.clab.yml`).  
**Telemetry:** ktranslate-golden on **k3s** (same host, `hostNetwork` collectors).

This replaces the deprecated `ec2-network-lab` all-in-compose path. Manifests are **generated** from `local/` — not hand-edited duplicates of `k8s/telemetry/`.

The laptop lab (`make up`) keeps the reduced **5-node** fabric (`topology.clab.yml`). Only the colocated profile uses the expanded topology.

## Architecture (HQ + branches)

```
                    ┌──────────── HQ (site=hq) ────────────┐
                    │  spine1 (RR)                       │
                    │   ├─ leaf1 ─ client1  172.17.0.1  │
                    │   └─ leaf2 ─ client2  172.17.0.2  │
                    └───┬───────────────────────┬────────┘
                        │ WAN e1-3            │ WAN e1-4
              ┌─────────▼─────────┐   ┌───────▼──────────┐
              │ branch1          │   │ branch2           │
              │ leaf-br1         │   │ leaf-br2          │
              │  └─ client-br1   │   │  └─ client-br2    │
              │     172.17.21.1  │   │     172.17.22.1   │
              └──────────────────┘   └───────────────────┘
```

| Site | Nodes | Client subnet | EVPN |
|------|-------|---------------|------|
| HQ | spine1, leaf1, leaf2 | `172.17.0.0/24` (stretched L2) | EVI 1 |
| Branch 1 | leaf-br1 | `172.17.21.0/24` | EVI 21 |
| Branch 2 | leaf-br2 | `172.17.22.0/24` | EVI 22 |

Underlay: eBGP from each leaf to spine1; branches use dedicated WAN links (`e1-3` / `e1-4`).

**Default instance:** `m5.4xlarge` (32 GB) — 5 SR Linux + 4 clients + k3s collectors.

Set `LAB_FABRIC_PROFILE=colocated` in EC2 `local/.env` (userdata does this automatically).

## Prerequisites

- AWS profile with EC2 + SSM (e.g. `AWS_PROFILE=mvr`)
- `local/.env` with `GC_OTLP_URL`, `GC_OTLP_ACCOUNT`, `GC_OTLP_KEY`
- Private subnet with NAT (for OTLP egress)

## Bring up

```bash
make -C local colocated-lab-discover   # writes terraform.tfvars
make -C local colocated-lab-up         # ~3 min terraform + ~15 min bootstrap
```

Bootstrap installs host dependencies (`colocated-host-deps.sh`), clones this repo, then runs two **oneshot** systemd units with built-in sanity checks (no manual SSM steps):

1. `network-o11y-fabric.service` — stage colocated topology, staggered ContainerLab deploy (`colocated-fabric-up.sh`), fabric sanity
2. `network-o11y-telemetry.service` — k3s collectors, SNMP CIDR discovery (`run-colocated-discovery.sh` via host-network `docker run`), post-telemetry wiring, telemetry sanity

Discovery uses CIDR from `groups/srl-hq.env` (and branch site groups) → `state/devices-srl-hq.yaml` (plus branch device lists). **Do not** hand-populate device lists.

Fresh EC2 packages installed before any lab scripts: userdata installs `git` via `dnf`, clones this repo, runs `colocated-host-deps.sh`, then `colocated-ec2-bootstrap.sh` (writes `local/.env`, installs all three site SNMP groups with LF-normalized `groups/*.env`, registers systemd units, starts fabric + telemetry).

### Bootstrap troubleshooting (AL2023)

| Symptom | Cause | Fix in repo |
|---------|-------|-------------|
| `git: command not found` on first boot | userdata cloned before installing git | userdata installs `git` before clone |
| `curl` / `curl-minimal` dnf conflict | AL2023 ships `curl-minimal` | `colocated-host-deps.sh` does not install `curl` |
| `INSTALL_K3S_EXEC=...: command not found` | k3s install as root without `env` | `env INSTALL_K3S_EXEC='...' sh` in deps script |
| `$'\r': command not found` in `groups/*.env` | CRLF in samples on Windows checkouts | LF samples + `normalize_env_file` on copy/generate |

If userdata still fails mid-flight, on the instance (with OTLP vars exported or in `local/.env`):

```bash
bash /opt/network-o11y-demo/local/scripts/colocated-bootstrap-recover.sh
```

## Monitor

```bash
aws ssm start-session --target <instance-id>
sudo journalctl -u network-o11y-fabric -f
sudo journalctl -u network-o11y-telemetry -f
kubectl get pods -n network-lab
```

## Verify in Grafana Cloud

```promql
count by (service_name) (kentik_ktranslate_chf_kkc_jchfq{deployment_host="aws-colocated-lab"})
```

Expect suffixed names (`ktranslate-flow-aws-colocated-lab`, not bare `ktranslate-flow`). On the instance:

```bash
cd /opt/network-o11y-demo/local
bash scripts/verify-ktranslate-service-names.sh --prometheus
```

`tags_container_service` stays short (`flow`, `flow-sflow`, `snmp-srl`) — that is ktranslate's internal `--service_name` flag. Dashboard **container_service** columns use OTLP `service_name` (the suffixed value above).

```promql
count by (device_name) (kentik_snmp_CPU{deployment_host="aws-colocated-lab"})
count(network_io_by_flow_bytes{deployment_host="aws-colocated-lab"})
```

### SNMP profile / empty metrics

Run discovery first (`make discover GROUP=srl-hq` or colocated bootstrap). If metrics are still sparse, check poller logs for `profile_message` and compare `state/devices-srl-hq.yaml` to a discovery-produced file (correct `mib_profile` + `provider` from ktranslate, not hand-written IPs).

## Destroy

```bash
make -C local colocated-lab-down
```

## Local k3s (without AWS)

On any machine with kubectl + k3s/microk8s and a running `local/` fabric:

```bash
make -C local generate-k8s
bash local/scripts/deploy-ktranslate-golden.sh
export KTRANSLATE_CLAB_HOST=$(docker network inspect clab -f '{{(index .IPAM.Config 0).Gateway}}')
make -C local softflowd traffic
```
