# Post 7: Total Cost of Ownership and the Migration Path

**Series:** Network Observability Without the Lock-in
**Audience:** IT leaders, network architects, anyone making the business case
**Tone:** Strategic — cost tables, migration framework, honest gaps

---

## Outline

### I. The Full Replacement Map (Recap)
- One-page summary table: SolarWinds product → open replacement
- What the series has covered, end to end
- What the complete stack looks like in production

### II. Cost Comparison

#### SolarWinds Licensing Reality
- NPM, NTA, IPAM, NCM — each licensed separately
- Per-node/element model: costs grow with the network
- Typical mid-market organisation (500 nodes): ballpark licence cost range
- Add Windows Server, SQL Server, dedicated hardware — hidden infrastructure costs
- Annual maintenance (20–25% of licence cost)

#### The Open Stack Cost Model
- Software: zero licence cost for all components
- Infrastructure: consumption-based (Grafana Cloud) or self-hosted
- AWS demo environment: ~$0.95/hour (~$700/month for always-on)
- Grafana Cloud: consumption pricing on metrics/logs ingested — scales with what you use
- Engineering time: the real cost — but also an investment in transferable skills

#### The Crossover Point
- At what node count does open-source + cloud become cheaper than SolarWinds?
- Rule of thumb: most organisations break even below 200 nodes

### III. The Migration Strategy

#### Phase 1: Parallel Running (Months 1–3)
- Deploy the open stack alongside SolarWinds — do not decommission anything yet
- Instrument a subset of devices (non-critical, well-understood)
- Build and validate dashboards; identify gaps
- Train the team

#### Phase 2: Coverage Expansion (Months 3–6)
- Onboard remaining device types into Alloy/gnmic
- Populate NetBox fully; enable netbox-sd enrichment
- Migrate alert rules from SolarWinds to Grafana Alerting
- Begin using Ansible for config backups and drift detection

#### Phase 3: Cutover (Months 6–12)
- SolarWinds becomes read-only reference; new dashboards are primary NOC view
- Decommission SolarWinds modules one at a time (NTA first, then NPM, then NCM/IPAM)
- Capture the licence renewal savings

### IV. Honest Gaps (What This Stack Doesn't Do Yet)

- **Auto-discovery**: NetBox requires devices to be registered (manually or via script).
  SolarWinds NPM can scan subnets and auto-onboard — the open stack needs scripting
  or a tool like `netdisco` to match this.
- **Out-of-the-box reporting**: SolarWinds has canned compliance and availability reports.
  Grafana dashboards are more powerful but require more initial setup.
- **Vendor support contract**: SolarWinds comes with TAC support. The open stack relies on
  community support, Grafana Cloud support tiers, and internal expertise.
- **Legacy SNMP MIBs**: Very old or unusual devices may need custom MIB work in Alloy.
  SolarWinds has a larger pre-built MIB library.

### V. Making the Business Case to Leadership
- Frame it as risk reduction, not just cost saving (post-SUNBURST trust argument)
- Quantify the licence savings at renewal
- Emphasise: skills on Prometheus/Grafana/Ansible are transferable industry-wide;
  SolarWinds skills are not
- The open stack grows with the business without a licence negotiation

### VI. Getting Started Today
- The demo repo: spin up a working stack in an afternoon
- Start with one protocol (SNMP) and one dashboard before trying to replace everything
- The community: Grafana forums, NetBox GitHub, ktranslate Slack
- Call to action: star the repo, open an issue, contribute a dashboard

---

*End of series.*
