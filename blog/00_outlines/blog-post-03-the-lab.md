# Post 3: Building the Lab — SR Linux on Kubernetes

**Series:** Network Observability Without the Lock-in
**Audience:** Network engineers, platform engineers
**Tone:** Hands-on technical — architecture, commands, real screenshots

---

## Outline

### I. Why a Simulated Lab?
- Real network hardware is expensive, hard to share, and impossible to destroy/recreate
- ContainerLab + Clabbernetes: run Nokia SR Linux (and other NOS images) as Kubernetes pods
- Fully reproducible — tear it down, rebuild it, hand it to a colleague
- The demo repo: link to GitHub

### II. The Topology: A Nokia SR Linux Clos Fabric
- What a Clos fabric is and why it's the standard for modern data centres
- What we built: 2 spines, 3 leaves, 3 Linux clients
- eBGP underlay + iBGP/EVPN overlay
- Diagram of the fabric

### III. Infrastructure: EKS on AWS
- Why EKS? Managed, multi-node, close enough to production
- What gets provisioned (VPC, bastion, EKS cluster, EBS storage) via OpenTofu
- Cost: ~$0.95/hour — spin up for a demo, tear down after
- Five commands from zero to a running cluster

### IV. The Networking Quirks (and How We Fixed Them)
- Clabbernetes on EKS has four specific issues that need fixing before telemetry works
  - VxLAN source-IP filter
  - Spurious ARP replies from launcher pods
  - MTU fragmentation (double VxLAN encapsulation)
  - SNMP/gNMI ports not reachable from the Kubernetes network
- The fix script + the reconciler that re-applies fixes after pod restarts
- Why this matters: SolarWinds has the same problem silently — it just fails to poll

### V. The Telemetry Pipeline
- Walk through the full data path:
  - SR Linux → SNMP UDP 161 → iptables DNAT → Alloy `prometheus.exporter.snmp`
  - SR Linux → gNMI TCP 57400 → gnmic → Prometheus → Alloy
  - SR Linux → syslog UDP → Alloy NodePort → Loki
  - Linux clients → softflowd → NetFlow v9 → ktranslate → OTLP → Alloy
- Everything converges in Grafana Cloud
- Architecture diagram (full pipeline)

### VI. Deploying It
- Step-by-step: `tofu apply`, bastion SSH, Clabbernetes, topology, telemetry stack
- What to expect at each stage
- How to verify: `kubectl get pods`, Alloy UI, a first metric appearing in Grafana

### VII. What You Have Now
- A fully instrumented simulated network
- All four telemetry streams flowing
- Ready to enrich with inventory — which is what Post 4 covers

---

**Next post:** NetBox as Your Source of Truth — auto-discovering devices and wiring inventory into the metrics pipeline.
