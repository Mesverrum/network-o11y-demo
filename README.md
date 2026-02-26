# Network Observability Demo

A self-contained, reproducible demo environment that showcases Grafana's network observability capabilities using a simulated Nokia SR Linux Clos fabric running in Kubernetes. Intended for Grafana Labs field engineers and customers to illustrate end-to-end collection, enrichment, and visualization of network telemetry in Grafana Cloud.

---

## Goals

- Demonstrate multi-protocol network telemetry collection (SNMP, gNMI, sFlow, syslog) from simulated network devices.
- Show how ktranslate and Grafana Alloy form a production-grade network telemetry pipeline.
- Illustrate device inventory enrichment using NetBox as a source of truth.
- Deliver pre-built Grafana Cloud dashboards covering topology, interface health, traffic flows, and device inventory.
- Be fully reproducible — deployable from scratch with a small set of commands.
- Be configurable for different Grafana Cloud stacks via a simple secrets file.

---

## Architecture

```
  Your Machine
  ┌──────────────────────────────────────┐
  │  ssh -L 8080:localhost:8080 bastion  │
  │  ssh -L <port>:localhost:<port> ...  │
  └──────────────┬───────────────────────┘
                 │ SSH port 22 only
                 ▼
  ┌──────────────────────────┐
  │   Bastion Host (EC2)     │  ← Only publicly reachable resource
  │   t3.micro, public subnet│
  │   kubectl pre-configured │
  └──────────────┬───────────┘
                 │ Private VPC networking
┌────────────────▼───────────────────────────────────────────┐
│                 AWS VPC (eu-west-1, private subnets)       │
│                                                            │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  EKS Cluster (private API endpoint only)             │  │
│  │                                                      │  │
│  │  ┌────────────────────────────────────────────────┐  │  │
│  │  │  Clabbernetes (namespace: c9s)                 │  │  │
│  │  │  Nokia SR Linux Clos Fabric (namespace: network-lab) │ │
│  │  │                                                │  │  │
│  │  │   Spine1 ──── Spine2                           │  │  │
│  │  │   / | \      / | \                             │  │  │
│  │  │  L1  L2  L3─L1  L2  L3   (eBGP underlay)      │  │  │
│  │  │  |   |   |               (iBGP/EVPN overlay)   │  │  │
│  │  │  C1  C2  C3   (Linux client pods)              │  │  │
│  │  └────────────────────────────────────────────────┘  │  │
│  └──────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────┘
```

---

## Telemetry Architecture

```
SR Linux nodes (5×)                      Linux client nodes (3×)
  │                                         │
  ├─ SNMP v2c (UDP 161)                     └─ softflowd (NetFlow v9)
  │    └── iptables DNAT ──► Alloy               │
  │        prometheus.exporter.snmp              │
  │                    │                         │
  ├─ gNMI (TCP 57400)  │                         ▼
  │    └── iptables DNAT ──► gnmic          ktranslate ◄── NetFlow v9 UDP 6343
  │                    │         │               │
  ├─ syslog (UDP 6514) │         ▼ Prometheus    │
  │    └── NodePort ──►│       Alloy scrape       │ OTLP gRPC
  │        Alloy loki  │         │                │
  │        .source     │         └────────────────┘
  │        .syslog     │                  │
  └────────────────────┘                  ▼
                                        Alloy ──► Grafana Cloud
                                          │         (Prometheus + Loki)
                                          │
                                  [SNMP metrics]
                                  [gNMI metrics]
                                  [NetFlow logs]
                                  [syslog logs]
```

**Flow data source:** The containerized SR Linux simulator only generates sFlow counter-sample datagrams (device statistics), not flow-sample records. Per-flow data (src IP, dst IP, ports, bytes) comes from `softflowd` running on the Linux client nodes, managed automatically by the `network-reconciler`.

SNMP and gNMI are made accessible to in-cluster tools (Alloy, gnmic) via iptables DNAT rules in each SR Linux launcher pod, exposed through `*-telemetry` ClusterIP Services.

Syslog is forwarded from SR Linux over UDP to Alloy's NodePort (30614) on the node where the Alloy pod runs. The `srl-syslog-config` Kubernetes Job applies this configuration at deploy time via gNMI.

---

## What's Implemented

| Component | Status | Notes |
|-----------|--------|-------|
| AWS VPC (2 AZs, NAT GW) | ✅ Deployed | `eu-west-1` |
| EKS cluster (private endpoint) | ✅ Deployed | 2× m5.2xlarge nodes, 100 GiB EBS |
| EC2 Bastion host | ✅ Deployed | SSH-only access |
| Clabbernetes manager | ✅ Deployed | Helm, `c9s` namespace |
| SR Linux Clos fabric | ✅ Deployed | 2 spines, 3 leaves, 3 clients |
| eBGP underlay | ✅ Working | All sessions established |
| iBGP/EVPN overlay (L2VPN) | ✅ Working | MAC-VRF across all leaves |
| Client connectivity | ✅ Working | ping + iperf3 between clients |
| Traffic generation | ✅ Working | `scripts/traffic.sh start` |
| SNMP v2c on all SR Linux nodes | ✅ Configured | community `public`, mgmt + default NI |
| gNMI (gRPC) on all SR Linux nodes | ✅ Configured | port 57400, TLS `clab-profile` |
| sFlow v5 on all SR Linux nodes | ✅ Configured | counter-samples only (simulator limitation) |
| collector topology node | ✅ Deployed | fabric monitoring point (leaf1:e1-2, IP 10.0.3.2/30) |
| softflowd on client nodes | ✅ Running | NetFlow v9 → ktranslate (managed by reconciler) |
| ktranslate | ✅ Deployed | NetFlow v9 → OTLP → Alloy |
| Grafana Alloy | ✅ Deployed | SNMP polling + OTLP receive + syslog → Grafana Cloud |
| gnmic | ✅ Deployed | gNMI streaming → Prometheus → Alloy |
| SR Linux syslog | ✅ Configured | RFC5424 UDP → Alloy → Loki; `hostname`, `app_name`, `severity` labels |
| Grafana Cloud pipeline | ✅ Configured | Requires credentials Secret |
| NetBox | ✅ Implemented | Fabric inventory; requires `deploy-netbox.sh` |
| netbox-sd | ✅ Implemented | Prometheus HTTP SD adapter for Alloy enrichment |
| NetBox populate job | ✅ Implemented | Seeds all devices, interfaces, IPs on first run |
| NetBox metric enrichment | ✅ Implemented | `device_role`, `site`, `platform`, `tenant` labels on all SNMP + gNMI metrics |

---

## Prerequisites

| Tool | Version | Notes |
|------|---------|-------|
| [OpenTofu](https://opentofu.org/) | ≥ 1.8 | `brew install opentofu` |
| [kubectl](https://kubernetes.io/docs/tasks/tools/) | ≥ 1.31 | `brew install kubectl` |
| [Helm](https://helm.sh/) | ≥ 3.14 | `brew install helm` |
| [Docker](https://docs.docker.com/get-docker/) | any recent | Required for `clabverter` |
| AWS credentials | — | Temporary STS or IAM user with AdministratorAccess |

---

## Deployment

### 1. Provision Infrastructure

```bash
cd terraform/

# Copy and fill in your public IP
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars — set allowed_ssh_cidr to your IP (curl -s ifconfig.me)

# Load AWS credentials
source ../scripts/setup-env.sh

# Apply
tofu init && tofu apply
```

Terraform provisions the VPC, NAT Gateway, bastion host, and EKS cluster (~15 minutes).

### 2. Connect to the Bastion

```bash
source scripts/setup-env.sh
BASTION_IP=$(cd terraform && tofu output -raw bastion_public_ip)
ssh -i network-o11y-demo.pem ec2-user@$BASTION_IP
```

Wait ~2 minutes for the bastion userdata script to finish configuring kubectl:
```bash
tail -f ~/kubectl-setup.log
kubectl get nodes   # should show 2 nodes Ready
```

### 3. Deploy Clabbernetes

```bash
# From the bastion:
helm repo add clabernetes https://clabernetes.github.io/clabernetes/
helm repo update
helm install clabernetes clabernetes/clabernetes \
  --namespace c9s --create-namespace \
  -f /path/to/k8s/clabbernetes/values.yaml
```

### 4. Deploy the SR Linux Topology

`k8s/topology/manifests.yaml` is the generated Kubernetes manifest (produced by `clabverter` from `topology.clab.yml`). Apply it directly:

```bash
kubectl apply -f k8s/topology/manifests.yaml
kubectl -n network-lab get pods --watch   # wait for all pods Running
```

To regenerate `manifests.yaml` from scratch (e.g. after topology changes):
```bash
docker run --rm -v $(pwd)/k8s/topology:/topology \
  ghcr.io/clabernetes/clabverter:latest \
  --topologyFile /topology/topology.clab.yml \
  --outputDirectory /topology \
  --naming non-prefixed
```

### 5. Apply Networking Fixes (one-shot)

Run the fix script once after the topology is first deployed:

```bash
bash scripts/fix-networking.sh
```

This fixes four things — see `scripts/fix-networking.sh` for full explanations:

- **VxLAN remote → `0.0.0.0`**: Disables the kernel source-IP filter. **Permanent** — does not need re-applying after pod restarts.
- **ARP off** on transit interfaces: Prevents spurious ARP replies from the launcher kernel. Re-applied automatically by the reconciler.
- **MTU clamp** to 1400 on client containers: Prevents TCP fragmentation over double VxLAN encapsulation. Re-applied automatically by the reconciler.
- **iptables DNAT** for SNMP (UDP 161) and gNMI (TCP 57400) in each launcher pod: Makes SR Linux management ports reachable from the Kubernetes network. Re-applied automatically by the reconciler.

### 6. Deploy the Network Reconciler

The reconciler watches for topology pod restarts and automatically re-applies the ARP, MTU, and DNAT fixes:

```bash
kubectl apply -f k8s/network-reconciler.yaml
kubectl -n network-lab get deploy network-reconciler   # should be 1/1 Ready
```

The reconciler polls every 30 seconds, detects pod UID changes, and re-applies fixes automatically.

### 7. Deploy NetBox (optional)

First create and fill in the NetBox credentials Secret:

```bash
cp k8s/netbox/netbox-secret.yaml.example k8s/netbox/netbox-secret.yaml
# Edit netbox-secret.yaml — fill in:
#   superuser-password  (NetBox admin UI password)
#   superuser-api-token (40-char hex, e.g. openssl rand -hex 20)
#   secret-key          (50+ chars,   e.g. openssl rand -base64 40)
#   postgresql-password (any strong password)
```

Then deploy NetBox, the netbox-sd adapter, and the populate job:

```bash
bash scripts/deploy-netbox.sh
```

This does three things:
1. Installs the **NetBox Helm chart** (`netbox-community/netbox`, v4.5.3) in the `network-tools` namespace.
2. Deploys **netbox-sd** — a lightweight HTTP service that reads NetBox device metadata and exposes it in [Prometheus HTTP SD format](https://prometheus.io/docs/prometheus/latest/http_sd/) for Alloy to consume.
3. Runs the **netbox-populate Job** to seed NetBox with the full SR Linux Clos fabric topology (sites, device types, roles, devices, interfaces, IP addresses, prefixes).

Access NetBox via the SSH tunnel:
```bash
bash scripts/access.sh
# → http://localhost:8080   (login: admin / password from netbox-secret.yaml)
```

### 8. Deploy the Telemetry Stack

First create the Grafana Cloud credentials Secret:

```bash
cp k8s/telemetry/grafana-cloud-secret.yaml.example k8s/telemetry/grafana-cloud-secret.yaml
# Edit grafana-cloud-secret.yaml — fill in all GC_* fields and API_TOKEN
# (see the example file for where to find each value in Grafana Cloud)
kubectl apply -f k8s/telemetry/grafana-cloud-secret.yaml
rm k8s/telemetry/grafana-cloud-secret.yaml   # never commit credentials
```

Then deploy:

```bash
bash scripts/deploy-telemetry.sh
```

This deploys ktranslate, Alloy, gnmic, the node telemetry Services, and runs the `srl-syslog-config` Job to configure syslog forwarding on each SR Linux node. The network-reconciler automatically installs and starts `softflowd` on each client node.

### 9. Deploy Grafana Dashboards (optional)

The dashboards in `grafana/dashboards/` can be pushed to Grafana Cloud using the deploy script.
It reads two gitignored credential files from the repo root:

```bash
# Create grafana-cloud-api.token — a Grafana service account token with dashboard write access
# (Grafana Cloud → Administration → Service Accounts → Add service account token)
echo "glc_eyJ..." > grafana-cloud-api.token

# Create instance.details — your Grafana Cloud instance URL
echo "url: https://yourorg.grafana.net" > instance.details

bash scripts/deploy-dashboards.sh
```

To regenerate dashboard JSON before deploying:
```bash
python3 grafana/dashboards.py && bash scripts/deploy-dashboards.sh
```

### 10. Start Traffic Generation

```bash
bash scripts/traffic.sh start
bash scripts/traffic.sh status
```

---

## Accessing Services

All services are accessed by SSH port forwarding through the bastion.
Run `scripts/access.sh` locally:

```bash
source scripts/setup-env.sh
bash scripts/access.sh
```

| Local Port | Service | K8s Service |
|------------|---------|-------------|
| `8080` | NetBox UI | `network-tools/netbox:80` |
| `12345` | Grafana Alloy UI | `network-lab/alloy:12345` |
| `9273` | gnmic Prometheus metrics | `network-lab/gnmic:9273` |

Grafana Cloud dashboards are accessed directly via your Grafana Cloud URL — no tunnel needed.

---

## SR Linux Fabric Details

### Topology

```
Spine1 (AS 201)    Spine2 (AS 202)
  e1-1 e1-2 e1-3    e1-1 e1-2 e1-3
   |    |    |        |    |    |
  L1   L2   L3      L1   L2   L3
  (AS101)(AS102)(AS103)
   |         |         |
  C1        C2        C3
172.17.0.1  172.17.0.2  172.17.0.3
```

- **Underlay**: eBGP on /31 point-to-point links
- **Overlay**: iBGP EVPN with a MAC-VRF (VNI 1) bridging all client ports
- **Client subnet**: `172.17.0.0/24` — all clients L2-adjacent via EVPN

### SR Linux Node Types

| Node | Type | Role |
|------|------|------|
| spine1, spine2 | `ixrd3l` | Route reflectors for EVPN |
| leaf1, leaf2, leaf3 | `ixrd2l` | EVPN VTEPs |
| client1, client2, client3 | Linux (`network-multitool`) | Traffic sources/sinks |

### Known Limitations

- **SR Linux sFlow — counter samples only**: The containerized SR Linux ASIC simulator
  (7220 IXR-D2L) only generates sFlow *counter-sample* datagrams (interface statistics) — it
  does not produce *flow-sample* records because there is no hardware ASIC for packet
  sampling. Per-flow data (src IP, dst IP, ports, bytes) is provided by `softflowd` (NetFlow v9)
  running on the Linux client nodes, managed automatically by the `network-reconciler`.
- **sFlow via default NI only**: SR Linux cannot use the `mgmt` network instance for sFlow
  collectors. The `collector` topology node (10.0.3.2/30 on leaf1:e1-2) provides a
  fabric-routable IP that SR Linux uses for its sFlow collector destination address.
- **SNMP/gNMI via iptables proxy**: Alloy and gnmic are not directly connected to the SR Linux
  fabric. They reach SR Linux management ports (161/UDP, 57400/TCP) through iptables DNAT rules
  in each launcher pod, exposed as `*-telemetry` ClusterIP Services. These rules are re-applied
  automatically by the network reconciler on pod restart.
- **Syslog via NodePort UDP**: SR Linux syslog is forwarded to Alloy over UDP using the NodePort
  (30614) on the node where the Alloy pod runs. All SR Linux devices target that specific node's
  IP — cross-node NodePort UDP forwarding is not reliable on this EKS cluster configuration.
- **MTU**: Client `eth1` interfaces are clamped to MTU 1400 to accommodate double VxLAN
  encapsulation overhead. Re-applied automatically by `k8s/network-reconciler.yaml`.
- **VxLAN source-IP filter**: Fixed permanently by setting `remote 0.0.0.0` on VxLAN
  interfaces. See `scripts/fix-networking.sh`.
- **ARP on transit interfaces**: Kernel ARP is disabled on launcher-pod transit interfaces.
  Re-applied automatically by `k8s/network-reconciler.yaml` on pod restart.

---

## Networking Fixes

### Root Causes

Four separate issues exist with Clabbernetes on EKS:

1. **VxLAN source-IP mismatch** — Clabbernetes sets VxLAN `remote` to Kubernetes ClusterIP
   addresses. kube-proxy DNATs ClusterIP → pod IP in-flight, so incoming VxLAN packets
   arrive with a pod IP as their source. The Linux VxLAN module rejects them because
   `pod-IP ≠ configured-remote`.

2. **Spurious ARP replies** — Clabbernetes uses TC `mirred mirror` mode to forward L2 frames
   into VxLAN interfaces. The Linux kernel continues processing the *original* copy of each
   frame, generating ARP replies from veth/VxLAN MAC addresses. These corrupt client ARP caches
   and break end-to-end connectivity.

3. **MTU fragmentation** — Two layers of VxLAN (Clabbernetes outer + SR Linux EVPN inner) add
   ~100 bytes of encapsulation overhead. With the default 9001-byte EKS node MTU, TCP jumbo
   frames are fragmented and then dropped, stalling throughput.

4. **SNMP/gNMI unreachable** — SR Linux management ports are bound to Docker container IPs on
   the `clab` bridge inside the launcher pod, not on the pod's eth0. Without DNAT, in-cluster
   tools cannot reach them.

### How They Are Fixed

| Problem | Fix | Persistence |
|---------|-----|-------------|
| VxLAN source-IP | Set `remote 0.0.0.0` — disables source filter; FDB (ClusterIPs) still routes outbound | **Permanent** — ClusterIPs are stable across pod restarts |
| Spurious ARP | `ip link set arp off` on all transit ifaces | Needs re-apply on pod restart → **reconciler handles this** |
| MTU fragmentation | `ip link set eth1 mtu 1400` inside client containers | Needs re-apply on pod restart → **reconciler handles this** |
| SNMP/gNMI reachability | iptables DNAT in launcher pods (`TELEMETRY_DNAT` chain) | Needs re-apply on pod restart → **reconciler handles this** |

`scripts/fix-networking.sh` applies all four fixes on first deploy.  
`k8s/network-reconciler.yaml` watches for pod restarts and re-applies ARP, MTU, and DNAT fixes automatically.

### UDP Security Group

The EKS managed node group security group includes a self-referencing UDP 1–65535 ingress rule
(in `terraform/eks.tf`) to allow VxLAN UDP 14789 between worker nodes across AZs. Without this,
the default EKS security group only permits TCP.

---

## Demo Scenarios

The environment supports the following walkthrough scenarios:

1. **Normal operations** — Show healthy fabric metrics, BGP sessions, and flow data in dashboards.
2. **Link failure** — Bring down a leaf-spine link; observe the interface state change alert fire and traffic reroute visible in the topology dashboard.
3. **Traffic surge** — Trigger heavy traffic between clients with `scripts/traffic.sh start`; observe flow dashboard and interface utilization spike.
4. **Inventory-driven enrichment** — Show how NetBox metadata labels (`device_role`, `site`, `platform`, `tenant`) enable filtering dashboards without changing collector config.
5. **Syslog events** — Show BGP session events and SR Linux system logs flowing into Loki, filterable by hostname and severity.

---

## Grafana Cloud Dashboards

| Dashboard | Description |
|-----------|-------------|
| **Network Topology** | Visual Clos fabric topology with live link utilization overlay |
| **Interface Health** | Per-device, per-interface metrics: traffic rates, errors, discards, operational state |
| **BGP Session Status** | BGP neighbor state, prefixes received/advertised per peer |
| **NetFlow / Traffic Flows** | Top talkers, protocol breakdown, flow volume over time |
| **Device Inventory** | Table view of devices sourced from NetBox |
| **Device Details** | CPU, memory, uptime, and interface deep-dive per SR Linux node |

---

## Cost Estimate

| Resource | Instance/Size | Est. Cost/hour |
|----------|--------------|----------------|
| EKS cluster | — | $0.10 |
| EKS nodes | 2× m5.2xlarge | $0.768 |
| Bastion | t3.micro | $0.013 |
| NAT Gateway | — | $0.048 + data |
| EBS (nodes) | 2× 100 GiB gp2 | $0.023 |
| **Total** | | **~$0.95/hour** |

To pause costs: scale the EKS managed node group to 0 (topology pods are lost but
infrastructure remains). To resume: scale back to 2 and re-run `scripts/fix-networking.sh`.

---

## Teardown

```bash
cd terraform/
source ../scripts/setup-env.sh

# Delete all K8s resources first (avoids orphaned AWS load balancers)
kubectl delete namespace network-lab c9s network-tools --ignore-not-found

tofu destroy
```

---

## Repo Structure

```
.
├── README.md
├── scripts/
│   ├── access.sh           ← Open SSH port forwards locally (NetBox, Alloy, gnmic)
│   ├── setup-env.sh        ← Load AWS credentials into env
│   ├── traffic.sh          ← Start/stop/status iperf3 traffic flows
│   ├── fix-networking.sh   ← One-shot: VxLAN, ARP, MTU, and telemetry DNAT fixes
│   ├── deploy-netbox.sh    ← Deploy NetBox + netbox-sd + populate job
│   └── deploy-telemetry.sh ← Deploy ktranslate/Alloy/gnmic + node telemetry Services
├── k8s/
│   ├── clabbernetes/
│   │   └── values.yaml              ← Helm values for Clabbernetes
│   ├── network-reconciler.yaml      ← Auto-reapplies ARP/MTU/DNAT on pod restart
│   ├── netbox/
│   │   ├── values.yaml              ← Helm values for NetBox chart (v4.5.3)
│   │   ├── netbox-secret.yaml.example  ← Template — copy, fill, apply (gitignored)
│   │   ├── populate-job.yaml        ← Job: seeds NetBox with SR Linux fabric topology
│   │   └── netbox-sd.yaml           ← Prometheus HTTP SD adapter (NetBox → Alloy)
│   ├── telemetry/
│   │   ├── grafana-cloud-secret.yaml.example  ← Template — copy, fill, apply, delete
│   │   ├── ktranslate.yaml          ← NetFlow v9 receiver → OTLP → Alloy
│   │   ├── alloy-config.yaml        ← Alloy ConfigMap (SNMP + OTLP + syslog + NetBox SD)
│   │   ├── alloy.yaml               ← Alloy Deployment + Services (ClusterIP + NodePort)
│   │   ├── gnmic-config.yaml        ← gnmic ConfigMap (gNMI subscription paths)
│   │   ├── gnmic.yaml               ← gnmic Deployment + Service
│   │   ├── srl-syslog-config.yaml   ← Job: configures syslog on SR Linux nodes via gNMI
│   │   └── node-telemetry-services.yaml  ← ClusterIP Services (SNMP/gNMI per node)
│   └── topology/
│       ├── topology.clab.yml        ← ContainerLab topology definition (source of truth)
│       ├── manifests.yaml           ← Generated Kubernetes manifests (via clabverter)
│       └── configs/fabric/          ← SR Linux startup configs (BGP + telemetry)
│           ├── leaf{1,2,3}.cfg
│           └── spine{1,2}.cfg
├── grafana/
│   ├── dashboards/                  ← Dashboard JSON files
│   ├── dashboards.py                ← Dashboard provisioning script
│   └── flow/                        ← Network topology panel assets
└── terraform/
    ├── main.tf             ← Provider + locals
    ├── vpc.tf              ← VPC, subnets, NAT GW
    ├── bastion.tf          ← Bastion EC2 instance + security group
    ├── eks.tf              ← EKS cluster + managed node group
    ├── variables.tf        ← All input variables with defaults
    ├── outputs.tf          ← Useful post-apply values
    ├── versions.tf         ← Provider version pins
    └── terraform.tfvars.example  ← Copy → terraform.tfvars (gitignored)
```
