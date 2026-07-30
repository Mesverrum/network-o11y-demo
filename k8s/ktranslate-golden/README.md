# ktranslate-golden (generated Kubernetes manifests)

Manifests under this directory are **generated** from `local/` by:

```bash
make -C local generate-k8s
# or
python3 local/scripts/generate-k8s-telemetry.py
```

Apply (creates Grafana Cloud secret from `local/.env`):

```bash
bash local/scripts/deploy-ktranslate-golden.sh
```

## Architecture

| Plane | Runtime | Notes |
|-------|---------|-------|
| Fabric | ContainerLab on host | `make fabric-up` — SRL spine/leaves/clients |
| Collectors | k3s Deployments (`hostNetwork`) | Same golden path as Docker Compose |
| Egress | Alloy → Grafana Cloud OTLP | `local/alloy/config.alloy` |

Colocated AWS reference: [`terraform/colocated-network-lab/README.md`](../../terraform/colocated-network-lab/README.md).

Legacy hand-maintained EKS manifests remain in `k8s/telemetry/` for the blog/EKS path only.

## Generated files

`*.yaml` files (except this README) are gitignored. Regenerate after `make discover` or `groups/*.env` changes.
