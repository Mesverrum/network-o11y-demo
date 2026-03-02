# Total Cost of Ownership and the Migration Path

*Part 7 of 7 — Network Observability Without the Lock-in*

---

The previous six posts assembled a complete open network observability stack. This post addresses the remaining questions: how much does it cost, how do you get from here to there without disrupting operations, and what do you tell leadership?

## The full replacement map

| SolarWinds | Open replacement | Covered in |
|---|---|---|
| NPM (SNMP metrics) | Grafana Alloy + Prometheus | Posts 3 & 5 |
| NTA (NetFlow/sFlow) | ktranslate + Loki + Grafana | Post 3 |
| Log Analyzer / Kiwi Syslog | Alloy + Loki | Posts 3 & 5 |
| IPAM | NetBox | Post 4 |
| NCM (config backup, compliance) | Ansible + Git + NetBox | Post 6 |
| Network Atlas (topology maps) | Grafana topology panel | Post 5 |
| *(nothing in SolarWinds)* | gnmic + gNMI streaming telemetry | Posts 2 & 5 |

That last row is not a replacement — it's a net-new capability. The open stack doesn't just achieve parity; it closes a gap that will widen as more of the industry adopts gNMI-capable platforms.

## Cost comparison

### SolarWinds licensing reality

SolarWinds prices by *elements* — nodes, interfaces, volumes, flows. A mid-market organization monitoring 500 devices across NPM, NTA, IPAM, and NCM typically pays **$50,000–$150,000/year in licence fees** at negotiated rates. Add:

- Windows Server licences (2 for HA): ~$3,000–$6,000/year
- SQL Server Standard or Enterprise: $5,000–$30,000/year
- Annual maintenance: 20–25% of the licence total
- DBA/sysadmin time for patching, backups, performance

Total cost of ownership at 500 nodes is often **$80,000–$200,000/year** before engineering hours.

### The open stack cost model

Software licensing: **zero** for all components.

Infrastructure depends on your deployment:

- **[Grafana Cloud](https://grafana.com/products/cloud/)** — consumption-based pricing on active metrics series and log volume. A 500-node environment with detailed SNMP and gNMI collection might generate 500k–2M active series: approximately **$2,000–$8,000/month**.
- **Demo environment (AWS EKS)** — approximately **$0.95/hour**. Spin up for a demo, tear down after.
- **Self-hosted Prometheus + Loki** — the marginal cost of adding Alloy, Loki, and NetBox to a cluster you already run is close to zero.

### The crossover point

As a rule of thumb: the open stack becomes cheaper than SolarWinds licensing at around **100–200 monitored nodes**, even accounting for Grafana Cloud consumption and setup engineering time. At 500 nodes, the five-year savings typically exceed $400,000.

## The migration strategy

The most important principle: **do not decommission anything until the replacement is proven**. The goal of the first phase is parallel running, not replacement.

### Phase 1: Parallel running (months 1–3)

Deploy the open stack alongside SolarWinds. Do not touch the existing deployment.

- Deploy Grafana Alloy with SNMP targets for 10–20 non-critical, well-understood devices
- Deploy NetBox, populate it with those devices, wire netbox-sd into Alloy
- Push initial dashboards to Grafana Cloud
- Compare Grafana metrics against NPM data for the same devices and time windows
- Identify discrepancies (usually SNMP community mismatches, missing MIBs, or timing differences)
- Train the team on PromQL and LogQL — budget time for this, it's a real learning curve

**Deliverable:** Grafana dashboards showing accurate data for a pilot device set. SolarWinds unchanged.

### Phase 2: Coverage expansion (months 3–6)

- Onboard remaining device types into Alloy: different vendors, different MIBs, edge cases
- Deploy gnmic for gNMI-capable devices
- Deploy ktranslate for NetFlow if NTA replacement is a priority
- Populate NetBox fully and enable netbox-sd for all targets
- Migrate alert rules from SolarWinds to [Grafana Alerting](https://grafana.com/docs/grafana/latest/alerting/) and run both systems in parallel for 4–6 weeks
- Start Ansible config backup — pull running configs, commit to Git

**Deliverable:** Full device coverage in Grafana, alert parity validated, Ansible backing up all devices.

### Phase 3: Cutover (months 6–12)

Decommission SolarWinds modules one at a time, starting with the lowest operational risk:

1. **NTA first** — replace with ktranslate + Grafana. Teams are least dependent on flow analysis for daily operations.
2. **Log Analyzer second** — replace with Loki. Syslog is available in both systems during the transition.
3. **NPM third** — make Grafana the primary NOC view, then decommission. This is the biggest change for the NOC; give it time.
4. **IPAM fourth** — at this point NetBox is already the live inventory source; decommissioning SolarWinds IPAM is administrative.
5. **NCM last** — after Ansible has been running backups and drift detection for several months.

At each decommission step, notify procurement. The licence reduction will be tangible and visible. This is the business case materializing.

## Honest gaps: what this stack doesn't do yet

A credible migration plan requires honesty about where the open stack still falls short.

**Auto-discovery.** SolarWinds NPM can scan subnets and auto-onboard devices without scripting. NetBox requires devices to be registered — manually, via a populate script, or via a discovery tool like `netdisco`. For organizations with large, dynamic device populations, this requires upfront automation investment.

**Canned compliance reports.** SolarWinds NCM ships pre-built compliance report templates. Grafana dashboards are more flexible, but the initial setup effort is higher.

**Vendor support contract.** SolarWinds comes with TAC support. The open stack's model is Grafana Cloud support (on paid plans), community forums for open-source components, and internal expertise.

**Legacy SNMP MIBs.** Very old or unusual devices may need custom MIB work in Alloy. SolarWinds has a larger pre-compiled MIB library. The Alloy MIB story is improving, but it's a valid consideration.

## Making the business case to leadership

Start with risk, not cost. Post-SUNBURST, the argument that you're moving your privileged network monitoring platform to software whose source code you can actually read is a legitimate security argument. The question of whether your monitoring platform is a supply chain attack surface is no longer hypothetical — it was answered in 2020. That framing tends to get attention in ways that cost spreadsheets don't.

Then quantify the savings at renewal time. Get the current SolarWinds renewal quote. Price out Grafana Cloud consumption for the same coverage. Show the difference. Multiply by five years. Add avoided Windows Server and SQL Server costs. The number is usually large enough to fund the migration and leave a surplus.

The skills argument is worth making explicitly: every engineer who gets comfortable with Prometheus, Grafana, Loki, and Ansible gets better at their job across the entire infrastructure stack — not just the network monitoring tool. Those skills apply to application observability, cloud infrastructure, and CI/CD pipelines. SolarWinds expertise applies to other SolarWinds environments. That's a meaningful difference when you're thinking about hiring and retention.

Finally, use parallel running to manage political risk. SolarWinds stays running until the replacement is validated. Frame Phase 1 as "adding observability capability" — which is true — rather than "replacing SolarWinds." The outcome is the same and the conversation is easier.

## Getting started today

The demo environment in this series is designed to be spun up in an afternoon:

```bash
git clone https://github.com/grafana/network-o11y-demo
cd network-o11y-demo
cd tofu && tofu apply
./scripts/deploy-all.sh
```

Start with SNMP and one dashboard. Get comfortable with PromQL. Add a second signal type. The migration is not a big bang — it's an incremental capability build that ends with a lower cost, more capable, and more trustworthy monitoring stack.

If this series has been useful, star the repo, open an issue with feedback, or contribute a dashboard for your own device types. The goal is a community-maintained library that covers common network environments without anyone having to start from scratch.

---

*This concludes the series: Network Observability Without the Lock-in.*

[Grafana Cloud](https://grafana.com/products/cloud/) is the easiest way to get started with metrics, logs, traces, and dashboards. We have a generous forever-free tier and plans for every use case. [Sign up for free now.](https://grafana.com/auth/sign-up/create-user/)

**Tags:** Network Observability, Monitoring, Grafana, Open Source, Migration, TCO, SolarWinds
