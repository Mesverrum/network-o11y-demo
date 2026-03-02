# Post 1: The Case Against SolarWinds

**Series:** Network Observability Without the Lock-in
**Audience:** Network engineers, IT leaders, infrastructure architects
**Tone:** Narrative/opinion — no code, no architecture diagrams

---

## Outline

### I. The Default That Stuck Around
- SolarWinds NPM has been the industry default for 20+ years
- Most network teams inherited it; few actively chose it recently
- It works — until it doesn't

### II. The Cost Reality
- NPM + NTA + IPAM + NCM licensing adds up fast — easily $50k–$200k/year for mid-size orgs
- Per-node licensing model penalises growth
- Renewal leverage: once your data is in SolarWinds, migration feels impossible
- Hidden costs: dedicated server infrastructure, DBA overhead, Windows-only stack

### III. The Trust Problem
- December 2020: SUNBURST supply chain attack via SolarWinds Orion update mechanism
- Attackers had access to victim environments for months before discovery
- SolarWinds was used by 18,000+ organisations including US federal agencies
- The fundamental question it raised: should your monitoring platform be a proprietary black box?

### IV. Built for a Different Era
- SolarWinds NPM was designed around physical appliances, SNMP polling, and on-prem Windows servers
- It has no native answer for:
  - Containerised/Kubernetes infrastructure
  - Cloud-native services (no SNMP endpoint to poll)
  - Streaming telemetry (gNMI) — the direction the entire network industry is moving
  - Unified metrics + logs + traces in a single pane of glass

### V. What the Alternative Looks Like
- The open-source ecosystem has quietly caught up
- Prometheus, Loki, Grafana, Alloy, NetBox, Ansible — each does one thing well
- No per-node licensing. No proprietary agents. No single vendor to trust blindly.
- Teaser: the rest of this series shows you exactly how to build it

### VI. Who This Series Is For
- Teams evaluating alternatives to SolarWinds at renewal time
- Organisations that need to justify the switch to leadership
- Engineers who want to understand how the pieces fit together before committing

---

**Next post:** The Open Network Observability Stack — a protocol-by-protocol map of what replaces what.
