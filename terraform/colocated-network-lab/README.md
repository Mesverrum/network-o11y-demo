# Colocated network lab (reference AWS deployment)

**Fabric:** ContainerLab on EC2 (`make fabric-up` via systemd).  
**Telemetry:** ktranslate-golden on **k3s** (same host, `hostNetwork` collectors).

This replaces the deprecated `ec2-network-lab` all-in-compose path. Manifests are **generated** from `local/` — not hand-edited duplicates of `k8s/telemetry/`.

## Prerequisites

- AWS profile with EC2 + SSM (e.g. `AWS_PROFILE=mvr`)
- `local/.env` with `GC_OTLP_URL`, `GC_OTLP_ACCOUNT`, `GC_OTLP_KEY`
- Private subnet with NAT (for OTLP egress)

## Bring up

```bash
make -C local colocated-lab-discover   # writes terraform.tfvars
make -C local colocated-lab-up         # ~3 min terraform + ~15 min bootstrap
```

Bootstrap installs Docker, ContainerLab, k3s, clones this repo, then:

1. `network-o11y-fabric.service` — ContainerLab fabric (no compose collectors)
2. `network-o11y-telemetry.service` — k3s collectors, then **SNMP CIDR discovery** (`groups/srl.env` → `TARGETS=172.20.20.0/24` → `state/devices-srl.yaml`), then softflowd/traffic

Discovery uses the same golden path as the laptop lab: `discover_srl` compose profile with `COLLECTOR_RUNTIME=k3s` (host network, OTLP → k3s Alloy). **Do not** hand-populate `state/devices-*.yaml`.

## Monitor

```bash
aws ssm start-session --target <instance-id>
sudo journalctl -u network-o11y-fabric -f
sudo journalctl -u network-o11y-telemetry -f
kubectl get pods -n network-lab
```

## Verify in Grafana Cloud

```promql
count by (device_name) (kentik_snmp_CPU{deployment_host="aws-colocated-lab"})
count(network_io_by_flow_bytes{deployment_host="aws-colocated-lab"})
```

### SNMP profile / empty metrics

Run discovery first (`make discover GROUP=srl` or colocated bootstrap). If metrics are still sparse, check poller logs for `profile_message` and compare `state/devices-srl.yaml` to a discovery-produced file (correct `mib_profile` + `provider` from ktranslate, not hand-written IPs).

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
