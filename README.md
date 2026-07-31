# Network Observability Demo

Companion repo for **Network Observability Without the Lock-in**: a Nokia SR Linux Clos fabric with SNMP, flow, sFlow, syslog, and gNMI into Grafana Cloud.

---
## Pick your path

| Path | Best for | Start here |
|------|----------|------------|
| **Local laptop** (16 GB) | Field demos, your own Grafana Cloud stack, fast iteration | [`oneclick/`](oneclick/) or [`local/README.md`](local/README.md) |
| **AWS EC2** (colocated) | Always-on ContainerLab fabric + k3s ktranslate-golden in your AWS account | [`terraform/colocated-network-lab/README.md`](terraform/colocated-network-lab/README.md) → `make -C local colocated-lab-up` |
| **AWS / EKS** | Full blog-series Clos (2 spines, 3 leaves), NetBox, Ansible | `make deploy` (AWS) or [`make help`](#aws--eks) below |

**AI agents / new operators:** [`AGENTS.md`](AGENTS.md) → *Agent playbook*. **New to ktranslate or Clos?** [`docs/network-observability-primer.md`](docs/network-observability-primer.md).

---

## Local lab (laptop)

Reduced Clos: **1 spine, 2 leaves, 2 clients** — Docker + ContainerLab + Compose on macOS (OrbStack VM), WSL2, or native Linux.

### One-click (recommended)

`oneclick/` is the **top-level orchestrator** — it asks **local laptop lab** vs **AWS/EKS** and remembers your choice. Local path runs ContainerLab + ktranslate under `local/`; AWS path runs `make infra` + `make all`.

| OS | Command |
|----|---------|
| **Windows** | `.\oneclick\deploy.ps1` (PowerShell; needs WSL2 + Docker Desktop) |
| **macOS** | `make deploy` or `./oneclick/deploy.sh` (OrbStack Linux VM) |
| **Linux** | `make deploy` or `bash oneclick/lab-linux.sh deploy` |

Teardown: `.\oneclick\decommission.ps1` / `make teardown`. Logs and roadblock help: [`oneclick/README.md`](oneclick/README.md).

Put Grafana Cloud OTLP creds in `local\.env` before deploy — the script copies them into the lab environment for you.

### Manual bring-up

```bash
cd local
cp .env.example .env          # GC_OTLP_URL, GC_OTLP_ACCOUNT, GC_OTLP_KEY
cp groups/srl.env.sample groups/srl.env
make generate && make check && make up    # ~10 min cold start
make status && make traffic
```

Full steps, macOS OrbStack guide, troubleshooting: **[`local/README.md`](local/README.md)**.

**Verify** (Explore → Prometheus on *your* stack):

```promql
count by (device_name) (kentik_snmp_CPU)
count(network_io_by_flow_bytes)
```

(ktranslate path — not `kentik_snmp_DeviceMetrics`; see [`AGENTS.md`](AGENTS.md) → *Investigation playbook*.)

Never commit `local/.env`, `local/groups/*.env`, or generated `local/config/` / `local/state/`.

---

## AWS / EKS

Full fabric on **Clabbernetes** (SR Linux as K8s pods): 2 spines, 3 leaves, 3 clients, NetBox, reconciler, Ansible.

```
  Bastion (SSH) ──► EKS (private) ──► Clabbernetes / network-lab namespace
                                         SR Linux Clos + ktranslate + Alloy + gnmic
                                         ──► Grafana Cloud
```

### Prerequisites

OpenTofu ≥ 1.8, kubectl ≥ 1.31, Helm ≥ 3.14, Docker (for clabverter), AWS credentials. See `terraform/terraform.tfvars.example`.

### Deploy

```bash
# Interactive one-click (macOS/Linux; AWS path runs terraform + make all in WSL on Windows)
make deploy

# Or align with blog posts (from a machine with kubectl → EKS)
make infra          # terraform: VPC, EKS, bastion
make post-03        # topology + telemetry (ktranslate, Alloy, gnmic)
make post-04        # NetBox + populate
make post-05        # Grafana dashboards
make post-06        # Ansible runner + backup CronJob
make all            # posts 3–6

make help           # full target list
```

Access via bastion: `bash scripts/access.sh` (NetBox :8080, Alloy :12345, gnmic :9273). Traffic: `bash scripts/traffic.sh start`.

**First-time EKS networking:** after topology deploy, run `bash scripts/fix-networking.sh` once; `k8s/network-reconciler.yaml` re-applies ARP/MTU/DNAT on pod restart. Deep dive: comments in `scripts/fix-networking.sh` and `k8s/network-reconciler.yaml`.

**Teardown:** `kubectl delete namespace network-lab c9s network-tools` then `cd terraform && tofu destroy`.

**Cost:** ~\$0.95/hour (2× m5.2xlarge nodes + NAT + bastion). Scale node group to 0 to pause.

### Colocated EC2 + k3s demo (reference AWS deployment)

ContainerLab **fabric** on EC2; **ktranslate-golden** collectors on k3s (generated from `local/`). SSM access, no EKS.

```bash
aws sso login --profile <your-account-profile>
export AWS_PROFILE=<your-account-profile>
make -C local colocated-lab-discover
make -C local colocated-lab-up    # OTLP from local/.env
```

Details: [`terraform/colocated-network-lab/README.md`](terraform/colocated-network-lab/README.md).

---

## Blog series

Companion drafts for **Network Observability Without the Lock-in** — full outline in [`blog/blog-series-overview.md`](blog/blog-series-overview.md). Arc: *why → what → build it → enrich it → observe it → automate it → migrate*.

| Post | Title | Repo tie-in |
|------|-------|-------------|
| [1](blog/10_drafts/blog-post-01-the-case.md) | The Case Against SolarWinds | Narrative (no deploy step) |
| [2](blog/10_drafts/blog-post-02-the-stack.md) | The Open Network Observability Stack | Narrative (no deploy step) |
| [3](blog/10_drafts/blog-post-03-the-lab.md) | Building the Lab: SR Linux on Kubernetes | `make post-03` (EKS) · [`local/`](local/) for laptop |
| [4](blog/10_drafts/blog-post-04-netbox.md) | NetBox as Your Source of Truth | `make post-04` |
| [5](blog/10_drafts/blog-post-05-grafana.md) | Observability with Grafana | `make post-05` |
| [6](blog/10_drafts/blog-post-06-ansible.md) | Network Config Management with Ansible | `make post-06` |
| [7](blog/10_drafts/blog-post-07-migration.md) | Total Cost of Ownership and the Migration Path | Narrative (no deploy step) |

Posts **3–6** map to `make post-03` … `make post-06` / `make all` on the AWS path. Posts **1–2** and **7** are reading-only. The laptop lab covers the same telemetry story as post 3 at smaller scale via [`oneclick/`](oneclick/) or [`local/README.md`](local/README.md).

---

## Repo map

```
.
├── oneclick/          One-click deploy/teardown (local laptop or AWS/EKS — interactive)
├── local/             Laptop lab (ContainerLab + ktranslate golden path)
├── blog/              Series drafts (posts 1–7) + blog-series-overview.md
├── docs/              Primer, ktranslate model, Grafana dashboard playbook
├── k8s/               EKS manifests (topology, telemetry, NetBox, reconciler)
├── terraform/         AWS VPC + EKS + bastion + colocated-network-lab
├── grafana/           Dashboard JSON + provisioning scripts (EKS/blog set)
├── ansible/           Playbooks (EKS runner pod)
├── scripts/           access.sh, traffic.sh, fix-networking.sh, deploy-*.sh
├── AGENTS.md          Agent playbook + dashboard patch rules
└── Makefile           make deploy, post-03…06, local-up/down
```

**Ktranslate dashboards 00–04:** [KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) `dashboards/` (not in this repo).

---

## What's different

| | Local (`local/`) | AWS (`k8s/` + `terraform/`) |
|--|------------------|-----------------------------|
| Fabric size | 1 spine, 2 leaves, 2 clients | 2 spines, 3 leaves, 3 clients |
| NetBox | Optional (CIDR discovery default) | Deployed + populated |
| Ansible backup/drift | — | ✓ |
| Topology exporter | ✓ | — |

Architecture deep-dive: [`docs/ktranslate-unified-model.md`](docs/ktranslate-unified-model.md). **Ktranslate dashboards (00–04):** source of truth is **[KtransToGrafana](https://github.com/Mesverrum/KtransToGrafana) `dashboards/`** — push with `make -C local dash-push`, drift-check with `make -C local dash-live-sync`. **Grafana dashboard patches (TabsLayout-safe):** [`docs/grafana-dashboard-playbook.md`](docs/grafana-dashboard-playbook.md).

---

## Grafana dashboards

| Set | Location | Use |
|-----|----------|-----|
| **Ktranslate 00–04** (SNMP, flow, health) | [KtransToGrafana `dashboards/`](https://github.com/Mesverrum/KtransToGrafana/tree/main/dashboards) | Golden-path fleet boards; edit upstream, push to your stack |
| **Lab-specific** (topology, join demo, flow lab UID) | `local/.dash-payloads/`, `local/dashboards/` | Adapted for this demo's UIDs (`lab-*`) |
| **EKS / blog set** | `grafana/dashboards/` | AWS integrations path (`integrations/snmp`, gNMI) |

**SNMP credential groups** stamp **`tags_snmp_group`** on metrics (from `GROUP=` in `groups/*.env` via poller `global.user_tags`). Filter fleet dashboards with `$snmp_group` / `tags_snmp_group=~"$snmp_group"`. Laptop default: one group `srl`. Colocated EC2: `srl-hq`, `srl-branch1`, `srl-branch2` — see [`local/docs/colocated-topology.md`](local/docs/colocated-topology.md).

**Workflow:** edit JSON in KtransToGrafana → `make -C local dash-push` (needs `GRAFANA_URL` + `GRAFANA_TOKEN` in `local/.env`, clone at `../KtransToGrafana` or set `KTRANS_UPSTREAM`). Details: [`local/dashboards/ktranslate/README.md`](local/dashboards/ktranslate/README.md), [`AGENTS.md`](AGENTS.md).
