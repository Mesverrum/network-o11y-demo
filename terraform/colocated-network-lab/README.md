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

1. `network-o11y-fabric.service` — ContainerLab + discovery (no compose collectors)
2. `network-o11y-telemetry.service` — `generate-k8s-telemetry.py` + `kubectl apply -k k8s/ktranslate-golden`

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

### SNMP profile (`Missing matched profile`)

Not a sysObjectID problem — SRL devices match `nokia-srlinux.yml` by OID (`1.3.6.1.4.1.6527.1.20.*`). If `state/devices-srl.yaml` was **hand-written** instead of produced by `run-discovery.sh`, ktranslate may only emit Uptime/PollingHealth with `profile_message="Missing matched profile"`.

**Fix:** run discovery so devices get the full YAML ktranslate expects, or force the profile on each device:

```yaml
mib_profile: "!nokia-srlinux.yml"   # bang (!) forces profile binding
provider: kentik-switch             # must match the profile's provider field
```

After editing `state/devices-srl.yaml`, restart the SNMP poller (`kubectl rollout restart deployment/ktranslate-snmp-srl -n network-lab`).

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
