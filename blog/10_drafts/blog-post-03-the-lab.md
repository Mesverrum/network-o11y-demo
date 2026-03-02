# Building the Lab: SR Linux on Kubernetes

*Part 3 of 7 — Network Observability Without the Lock-in*

---

Every good observability story needs something to observe. In this post, we build the lab: a Nokia SR Linux Clos fabric running as Kubernetes pods on AWS EKS, fully instrumented with four telemetry streams. By the end, you'll have a working environment you can pull apart, rebuild, and hand to a colleague — no rack hardware required.

The full source is at [github.com/grafana/network-o11y-demo](https://github.com/grafana/network-o11y-demo).

## Why a simulated lab?

Real network hardware is expensive, physically constrained, and difficult to share. The solution is **ContainerLab** — a tool that runs real network operating system images as containers — combined with **Clabbernetes**, which orchestrates those topologies as Kubernetes pods.

Nokia SR Linux ships a fully functional container image under a free developer licence. You get a real routing stack — BGP, EVPN, gNMI — not a simulator. The topology is:

- **Reproducible** — tear it down and rebuild in minutes
- **Shareable** — anyone with `kubectl` access can use it
- **Observable** — the same telemetry interfaces (SNMP, gNMI, syslog, NetFlow) as physical hardware

## The topology: a Nokia SR Linux Clos fabric

We built a two-tier IP Clos fabric — the standard architecture for modern data center networks.

```
          ┌──────────┐       ┌──────────┐
          │  spine1  │       │  spine2  │
          └──┬───┬───┘       └───┬──┬───┘
             │   └──────┐ ┌─────┘  │
         ┌───┴────┐  ┌──┴─┴──┐  ┌──┴─────┐
         │ leaf1  │  │ leaf2 │  │ leaf3  │
         └───┬────┘  └───┬───┘  └───┬────┘
             │            │          │
         ┌───┴────┐  ┌───┴───┐  ┌───┴────┐
         │client1 │  │client2│  │client3 │
         └────────┘  └───────┘  └────────┘
```

Eight devices total: 2 spines, 3 leaves, 3 Linux clients. The routing design uses eBGP underlay between spines and leaves, with an iBGP/EVPN overlay for L2VPN (VNI 1) carrying client traffic. Linux clients run softflowd to generate NetFlow telemetry.

## Infrastructure: EKS on AWS

The lab runs on Amazon EKS, provisioned with **OpenTofu** (the open-source Terraform fork). What gets provisioned:

- A VPC with public and private subnets across two availability zones
- A bastion host (EC2) for kubectl access
- An EKS cluster with three `m5.large` worker nodes
- EBS storage via the AWS EBS CSI driver for persistent workloads like NetBox's PostgreSQL

**Cost:** approximately **$0.95/hour**. Spin up for a demo, tear down after. Five commands from zero to a running cluster:

```bash
cd tofu && tofu init
tofu apply
aws eks update-kubeconfig --name network-o11y-demo --region eu-west-1
ssh -i network-o11y-demo.pem ec2-user@$(tofu output -raw bastion_public_ip)
./scripts/deploy-all.sh
```

## The networking quirks (and how we fixed them)

Running virtual network devices inside Kubernetes introduces four specific problems that need solving before telemetry works. SolarWinds would hit the same issues polling a Clabbernetes topology — it would just fail silently.

**VxLAN source-IP filtering.** Clabbernetes uses VxLAN to connect SR Linux containers across nodes. The outer UDP source IP is that of the launcher pod, not the virtual SR Linux interface. Fix: an iptables NAT rule on each node.

**Spurious ARP replies from launcher pods.** Launcher pods respond to ARP for the SR Linux management IP before SR Linux is fully up, causing stale cache entries in Alloy's SNMP poller. Fix: an iptables DROP rule blocking ARP replies until SR Linux is ready.

**MTU fragmentation.** Double VxLAN encapsulation reduces the effective MTU below 1500 bytes. gNMI streams large protobuf messages that fragment silently. Fix: set MTU to 1400 on SR Linux management and client Linux interfaces.

**Port reachability.** SNMP (UDP 161) and gNMI (TCP 57400) on SR Linux pods aren't exposed as Kubernetes Services by default. Fix: NodePort rules applied by a reconciler DaemonSet (`scripts/fix-srlinux-networking.sh`) that re-applies after pod restarts.

## The telemetry pipeline

With the topology running and networking fixed, four telemetry streams flow from the fabric to Grafana Cloud.

**SNMP metrics.** [Grafana Alloy](https://grafana.com/oss/alloy/)'s `prometheus.exporter.snmp` component polls each SR Linux device every 60 seconds, exposing standard IF-MIB and enterprise MIBs as Prometheus metrics. Target addresses come from NetBox HTTP SD — no hardcoded device list.

**gNMI streaming telemetry.** gnmic subscribes to SR Linux on TCP 57400, streaming updates for interface counters, BGP session state, and system CPU/memory. Updates arrive within milliseconds of a state change. gnmic exposes them as Prometheus metrics; Alloy scrapes the endpoint.

**Syslog.** SR Linux forwards syslog to Alloy on UDP 6514 via a NodePort service. Alloy parses and forwards to [Loki](https://grafana.com/oss/loki/) with labels: `job="syslog"`, `host=<device>`, `severity=<level>`.

**NetFlow.** The three Linux clients run softflowd, exporting NetFlow v9 to ktranslate. ktranslate normalizes flows, converts to OTLP log records, and forwards to Alloy, which writes to Loki. This gives you top-talker and protocol breakdown visibility in Grafana.

## What you have at the end

After running through this post:

- A Nokia SR Linux Clos fabric (2 spines, 3 leaves, 3 clients) running on EKS
- All four telemetry streams — SNMP, gNMI, syslog, NetFlow — flowing to Grafana Cloud
- An Alloy pipeline ready to receive inventory enrichment from NetBox
- A fully reproducible environment rebuildable in under 30 minutes

Every metric at this point carries only bare context: an IP address and a job name. The next post adds the intelligence layer — NetBox wiring device inventory labels into every metric automatically.

---

*Next: [Part 4 — NetBox as Your Source of Truth](#), where we populate the device inventory and wire it into the metrics pipeline.*

[Grafana Cloud](https://grafana.com/products/cloud/) is the easiest way to get started with metrics, logs, traces, and dashboards. We have a generous forever-free tier and plans for every use case. [Sign up for free now.](https://grafana.com/auth/sign-up/create-user/)

**Tags:** Network Observability, Grafana Alloy, SR Linux, gNMI, Kubernetes, ContainerLab, SNMP
