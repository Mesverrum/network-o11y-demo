# AWS CSP observability dashboards — draft specification

**Status:** Draft for review (not yet implemented as JSON)  
**Audience:** Operators extending this repo from **on-prem network o11y** (ktranslate) to **Grafana Cloud AWS Observability**  
**Companion:** [network-observability-primer.md](network-observability-primer.md) · [ktranslate-unified-model.md](ktranslate-unified-model.md)

---

## Why this exists

Three recurring failure modes when teams move workloads to a CSP:

1. **Invisible boundaries** — on-prem NMS shows healthy links; cloud shows healthy instances; nobody sees *where* traffic crosses zones, regions, or the internet edge.
2. **Surprise egress bills** — NAT gateway + cross-AZ + cross-region + “data transfer out” line items spike after a seemingly small architecture change.
3. **Limits mistaken for bugs** — NAT port exhaustion, API throttles, and per-AZ bandwidth ceilings look like application latency until someone correlates infrastructure metrics.

This draft defines a **small, opinionated dashboard set** that sits *alongside* Grafana’s bundled AWS dashboards—not a replacement for them. Use Grafana’s prebuilt **NAT Gateway**, **ALB/NLB**, **Billing**, and **VPN** boards for service depth; use these for the **hybrid narrative** and **cost-of-traffic** story.

---

## Prerequisites (Grafana Cloud)

Enable **Cloud Provider Observability → AWS** on your stack:

| Capability | Recommendation | Why |
|------------|----------------|-----|
| **CloudWatch metric streams** (Data Firehose → GC) | Preferred for NAT, ELB, EC2, EKS-related namespaces | Lower lag, lower CloudWatch API cost than pull scrape |
| **Resource metadata scrape** | Enable | Enriches metrics with `tag_*`, ARN, account — essential for “which team / which app” |
| **Namespaces to stream (minimum)** | `AWS/NATGateway`, `AWS/ApplicationELB`, `AWS/NetworkELB`, `AWS/EC2`, `AWS/EBS`, `AWS/VPN`, `AWS/TransitGateway` (if used), `AWS/Billing` (if available) | Covers egress choke points |
| **On-prem side (already in this repo)** | ktranslate flow + SNMP + topology | Correlates fabric traffic with cloud edge |

**Metric naming:** Grafana stores CloudWatch metrics in Prometheus form. Exact series names depend on ingest path; after enablement, run in Explore:

```promql
{__name__=~"aws_natgateway.*"}
```

Adjust queries below to match your stack’s exported names (often `aws_<namespace>_<metric>_<statistic>`).

**Phase 2 (high value for cross-AZ attribution):** VPC Flow Logs → S3 → Firehose/Lambda → Loki. CloudWatch alone does not expose “bytes from AZ-a to AZ-b per service.” This draft calls that out where panels are proxy-only.

---

## Dashboard suite overview

| # | UID (proposed) | Title | Primary question |
|---|----------------|-------|------------------|
| **00** | `hybrid-network-boundary` | Hybrid Network Boundary | Where does on-prem end and AWS begin—and is traffic taking the path we think? |
| **01** | `aws-egress-transit-economics` | Egress & Transit Economics | What is leaving the VPC, how fast, and what does it cost? |
| **02** | `aws-cross-zone-traffic` | Cross-AZ & Cross-Region Traffic | Which AZs/regions talk to each other (the refactor trigger)? |
| **03** | `aws-network-limits-saturation` | Network Limits & Saturation | Are we hitting NAT/LB/VPN/TGW ceilings before “the app is slow”? |
| **04** | `aws-observability-tax` | Observability & Platform Tax | What does monitoring + telemetry itself cost in AWS and Grafana Cloud? |

Folder: `cloud-network` (or `network-lab` if you want one folder for demos).

---

## 00 — Hybrid Network Boundary

**Goal:** One screen for executives and architects during migration—*not* another device grid.

### Variables

| Variable | Source | Notes |
|----------|--------|-------|
| `$datasource` | Prometheus | GC default |
| `$region` | label values on AWS metrics | Multi-region if applicable |
| `$onprem_tester` | `tester_id` on topology metrics | Default `network-lab` |
| `$vpn_connection` | `vpn_connection_id` or tag | If hybrid VPN exists |

### Row A — Topology strip (subway / node graph)

| Panel | Data | Notes |
|-------|------|-------|
| On-prem fabric | `network_topology_device_info` + `network_topology_edge_info` | From topology_exporter / gnmic LLDP |
| Cloud attachment | `aws_vpn_tunnelstate` or DX `ConnectionState` | Green/yellow/red by tunnel |
| “North-south” hint | `max_over_time(network_io_by_flow_bytes{...}[1h])` top talkers to `172.20.20.0/24` or public prefixes | Lab: client mgmt probes |

### Row B — Path health (side-by-side)

| Panel | On-prem query (example) | Cloud query (example) |
|-------|-------------------------|------------------------|
| Device reachability | `avg(kentik_ping_PacketLossPct)` by `device_name` | N/A or synthetic canaries |
| VPN / DX state | N/A | `aws_vpn_tunnelstate` == 1 |
| Edge utilization | `sum(kentik_snmp_ifHCOutOctets) * 8 / 60` top interfaces | NAT bps (see dashboard 01) |
| BGP (if hybrid) | `kentik_snmp_*` BGP peer state | — |

### Row C — Migration checklist (markdown)

Static panel: links to runbooks—*“Before cutover: baseline NAT bytes 7d, enable flow logs on TGW attachments, tag ENIs by service.”*

### Alerts (draft)

- VPN tunnel down > 5m
- On-prem ping loss > 5% to DC core while cloud VPN up (split-brain path)

---

## 01 — Egress & Transit Economics

**The dashboard that pays for itself.** Start here after enabling AWS integration.

### Variables

`$region`, `$vpc_id`, `$nat_gateway_id`, `$account_id` (from tags)

### Row A — Executive KPIs (stat panels)

| Panel | Query pattern | Interpretation |
|-------|---------------|----------------|
| **Internet egress (est.)** | `sum(rate(aws_natgateway_bytes_out_to_destination_sum[5m])) * 8` | Bits/s to internet via NAT |
| **NAT processing volume** | Sum of all four NAT byte counters | Total NAT churn (in+out both directions) |
| **NAT gateway hourly cost (est.)** | `$0.045/hr * count(nat_gateway)` + data processing | Static + variable; use Billing dashboard for truth |
| **Data transfer $ (MTD)** | Billing metric if streamed; else annotation link to Cost Explorer | See panel note below |
| **Top spender (tag)** | `topk(5, sum by (tag_service) (...))` after metadata enrich | Needs consistent `service` / `app` tags on NAT subnets’ workloads |

### Row B — NAT gateway drill-down

Prebuilt **AWS/NATGateway** dashboard covers most panels. Add these **cost-oriented** views:

```promql
# Bits/s — internet-bound (classic “egress surprise”)
sum by (nat_gateway_id) (
  rate(aws_natgateway_bytes_out_to_destination_sum[$__rate_interval])
) * 8

# Total NAT bandwidth (approaches 100 Gbps / 10M pps limits)
sum by (nat_gateway_id) (
  rate(aws_natgateway_bytes_in_from_destination_sum[$__rate_interval])
  + rate(aws_natgateway_bytes_in_from_source_sum[$__rate_interval])
  + rate(aws_natgateway_bytes_out_to_destination_sum[$__rate_interval])
  + rate(aws_natgateway_bytes_out_to_source_sum[$__rate_interval])
) * 8

# NAT errors that precede “random” app failures
sum by (nat_gateway_id) (aws_natgateway_error_port_allocation_sum)
sum by (nat_gateway_id) (aws_natgateway_packets_drop_count_sum)
```

| Panel | Type | Talk-track |
|-------|------|------------|
| Egress bps over time | Time series | “This is the line finance cares about.” |
| `$ per day` annotation | Manual or Billing API | Correlate deploy dates with slope changes |
| Single-NAT warning | Stat | This repo’s Terraform uses `single_nat_gateway = true` — cheap, but cross-AZ hairpins through one AZ |

### Row C — Non-NAT egress paths

| Path | Metrics / source |
|------|------------------|
| **ALB/NLB → internet** | `AWS/ApplicationELB`, `AWS/NetworkELB` processed bytes |
| **S3 / CloudFront** | `AWS/CloudFront` `BytesDownloaded` |
| **Direct Connect / TGW** | `AWS/DX`, `AWS/TransitGateway` bytes |
| **Grafana OTLP / Firehose** | Alloy egress + Firehose `DeliveryToHttpEndpoint` bytes | Observability tax |

### Row D — On-prem correlation

Overlay (dual axis or adjacent panels):

```promql
# On-prem flow volume (lab / ktranslate)
sum(max_over_time(network_io_by_flow_bytes[$__interval]))

# Cloud NAT egress
sum(rate(aws_natgateway_bytes_out_to_destination_sum[$__rate_interval]))
```

**Story:** “Traffic left the DC” (flow) vs “traffic hit the internet” (NAT). Mismatch → local breakout, caching, or duplicate paths.

### Alerts (draft)

| Alert | Condition | Severity |
|-------|-----------|----------|
| NAT egress week-over-week | > 50% increase, 3d baseline | warning |
| NAT `ErrorPortAllocation` | > 0 for 10m | critical |
| NAT `PacketsDropCount` | sustained increase | warning |

---

## 02 — Cross-AZ & Cross-Region Traffic

**Use case:** “We refactored three microservices and the AWS bill doubled”—usually cross-AZ chatter.

### Reality check

| Signal | What CloudWatch gives you | What you need for precision |
|--------|---------------------------|-----------------------------|
| Cross-AZ bytes | **No first-class per-service metric** | VPC Flow Logs + `srcaddr`/`dstaddr` + subnet→AZ map |
| Cross-region | Billing dimensions; some TGW metrics | CUR + flow logs on TGW attachments |
| “Noisy neighbor” in K8s | Pod→node→AZ via kube labels + node_exporter | K8s topology + flow logs |

### Phase 1 panels (metrics-only — proxies)

| Panel | Query / approach | Caveat |
|-------|------------------|--------|
| **AZ spread** | Count of EC2/EKS nodes by `availability_zone` tag | Imbalance ≠ cost |
| **ELB cross-zone** | `aws_applicationelb_cross_zone_load_balancing` + processed bytes | Cross-zone LB traffic is billable |
| **Inter-AZ NAT hairpin** | Single NAT in one AZ + high `BytesInFromSource` from other AZs’ subnets | Proxy: compare NAT AZ to private subnet AZ tags |
| **TGW bytes by attachment** | `AWS/TransitGateway` `BytesIn`/`BytesOut` by attachment | Good for hub-and-spoke |
| **RDS / ElastiCache cross-AZ** | Clients in AZ-a hitting DB in AZ-b → app metrics + AZ labels | Needs app-level labels |

### Phase 2 panels (VPC Flow Logs in Loki)

LogQL sketch (after ingest):

```logql
sum by (src_az, dst_az) (
  count_over_time({job="vpc-flow"} | json | src_az != dst_az [$__interval])
)
```

Sankey: `src_az` → `dst_az` → `dst_port` (top 20).

### Row — “Refactor triggers” (markdown + thresholds)

Document internal thresholds, e.g.:

- Cross-AZ > 30% of total VPC bytes → architecture review
- Service in AZ-a calling DB in AZ-b → move workload or use read replica in AZ-a
- NAT in single AZ + multi-AZ EKS → expect cross-AZ charges to NAT

### Tie-in to this repo

The EKS path in `terraform/vpc.tf` uses **one NAT gateway** for cost control. Dashboard 02 should explicitly flag: *“Demo topology optimizes for $; production multi-AZ NAT has different economics.”*

---

## 03 — Network Limits & Saturation

**Goal:** Distinguish CSP ceilings from application bugs.

### NAT gateway

| Limit | ~100 Gbps / 10M pps | Panel |
|-------|---------------------|-------|
| Bandwidth utilization | Calculated bps / 100e9 | Gauge |
| Port allocation errors | `ErrorPortAllocation` | Stat + table |
| Connection burst | `ActiveConnectionCount` / `ConnectionAttemptCount` | Time series |

### Load balancers

| Metric family | Watch for |
|---------------|-----------|
| `TargetResponseTime`, `HTTPCode_ELB_5XX` | App vs LB |
| `RejectedConnectionCount` | LB saturation |
| `ConsumedLCUs` | NLB/ALB cost + scale |

### VPN / Direct Connect

| Metric | Meaning |
|--------|---------|
| `TunnelState` | Hybrid path up |
| `TunnelDataIn` / `TunnelDataOut` | Bytes on DX/VPN |
| `BgpStatus` (DX) | Routing health |

### EKS / VPC CNI (if node metrics available)

- Pod IP assignment failures
- ENI limits per instance type
- Node network throughput (EC2 `NetworkIn`/`NetworkOut`)

### On-prem limits (same screen)

| Panel | Query |
|-------|-------|
| Interface errors | `kentik_snmp_ifInErrors` / `ifOutErrors` |
| CPU on spine/leaf | `kentik_snmp_CPU` |
| Flow cardinality | `count(network_io_by_flow_bytes)` |

**Unified story:** “Saturation anywhere in the path”—on-prem port, VPN, NAT, or LB.

---

## 04 — Observability & Platform Tax

Networks and platforms both emit telemetry; both have **cost and egress**.

### AWS-side

| Line item | Source |
|-----------|--------|
| CloudWatch API / metric streams | AWS bill + Firehose metrics |
| NAT for agent traffic | NAT GW bytes (updates, package pulls) |
| VPC Flow Logs storage | S3 + ingestion |
| Grafana Cloud Firehose endpoint | Data transfer out of AWS |

### Grafana Cloud-side

| Line item | Source |
|-----------|--------|
| Active series (AWS metrics) | GC usage insights |
| Log volume (flow logs, syslog) | GC usage |
| On-prem OTLP | `deployment_host` cardinality from ktranslate |

### Panels

| Panel | Purpose |
|-------|---------|
| Metrics ingested by `scrape_job` / namespace | Find noisy AWS namespaces |
| Top 10 label cardinalities on `aws_*` | Tag explosion |
| ktranslate CHF health | `kentik_ktranslate_chf_kkc_*` — collector tax, not device tax |
| Bytes: NAT vs Firehose vs OTLP | “Observability traffic” stack rank |

### Alert

- AWS metric stream delivery failures (Firehose backup to S3 growing)
- GC active series week-over-week > 25% without infra change

---

## Implementation order

1. **Enable AWS integration** + stream `AWS/NATGateway`, `AWS/Billing` (if available), VPN/DX if hybrid.
2. **Import Grafana prebuilt** NAT + Billing dashboards; verify PromQL names in Explore.
3. **Build dashboard 01** (egress economics) — highest ROI.
4. **Add dashboard 00** once on-prem + cloud metrics coexist in one stack.
5. **Plan VPC Flow Logs** before investing heavily in dashboard 02 cross-AZ precision.
6. **Dashboard 04** when finance asks “why did observability cost spike?”

---

## Suggested alerts package (summary)

| Name | Dashboard | Condition |
|------|-----------|-----------|
| `nat-egress-spike` | 01 | WoW bytes_out_to_destination +50% |
| `nat-port-exhaustion` | 03 | `ErrorPortAllocation` > 0 |
| `vpn-tunnel-down` | 00 | `TunnelState` != UP |
| `hybrid-ping-degraded` | 00 | on-prem ping loss > 5% |
| `cross-az-review` | 02 | Manual monthly review + flow log panel |
| `observability-series-spike` | 04 | AWS active series +25% WoW |

---

## Open questions (for your AWS account)

- [ ] Hybrid connectivity: VPN, DX, TGW, or public-only?
- [ ] Single vs multi-AZ NAT (this repo’s Terraform: **single**)?
- [ ] Will EKS stay in-scope or only VPC networking + managed services?
- [ ] CUR / Cost Explorer integration into Grafana, or Billing metrics only?
- [ ] VPC Flow Logs: which VPCs, aggregation interval, Loki vs S3-only?

---

## Next steps in this repo

When you are ready to implement:

1. Add `grafana/dashboards/aws/` or `docs/dashboard-exports/aws/` JSON manifests (v2).
2. Optional Terraform: VPC Flow Logs, S3 bucket, IAM for flow log delivery.
3. Cross-link from `AGENTS.md` and `oneclick/README.md` (AWS path section).
4. Reuse design patterns from [grafana-network-dashboard-design-patterns.md](grafana-network-dashboard-design-patterns.md) — same row/panel naming, `has_*` gates where device-specific.

*Draft v0.1 — 2026-07-27*
