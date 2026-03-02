# The Case Against SolarWinds

*Part 1 of 7 — Network Observability Without the Lock-in*

---

There's a reasonable chance SolarWinds NPM is running somewhere in your organization right now — and an equally reasonable chance that nobody on your current team chose it. It was there when they arrived. It's, in the language of enterprise IT, simply *the thing you use.*

That inertia is worth examining. The assumptions that made SolarWinds the obvious choice in 2005 are not the assumptions that should drive a purchasing decision in 2025. And yet, for many teams, renewal comes around and the path of least resistance wins again.

This series is for teams that want to ask the question properly this time.

## The default that stuck around

SolarWinds NPM launched in 1999 and offered something genuinely valuable: a GUI-driven, SNMP-polling network monitor that didn't require a PhD to operate. It ran on Windows, stored data in SQL Server, and was affordable for the era. Network teams adopted it, and the flywheel of familiarity kept spinning.

Twenty-five years later, NPM is structurally the same product. The same Windows-based architecture. The same per-node licensing model. The same SNMP polling at five-minute intervals. The same siloed product family — NPM for metrics, NTA for flows, IPAM for addresses, NCM for configs — each with a separate licence and its own learning curve.

Most organizations using SolarWinds today are not actively choosing it. They are continuing it.

## The cost reality

Continuing it is expensive.

SolarWinds prices by *elements* — nodes, interfaces, volumes — and the count grows with your network. A mid-market organization monitoring 500 devices across NPM, NTA, IPAM, and NCM can easily spend **$50,000–$200,000 per year in licence fees alone**, before factoring in dedicated Windows Server infrastructure, SQL Server licences, and the DBA overhead to keep it all running.

The renewal dynamic is particularly pernicious. Once your historical metrics, alert configurations, and dashboard layouts live inside SolarWinds, the friction of leaving feels enormous. Every year you stay, your data becomes more entrenched and the migration cost feels higher. The licence renewal team knows this.

## The trust problem

Then came December 2020.

The SUNBURST attack compromised SolarWinds' software build pipeline and inserted malicious code into routine Orion updates. The backdoor was distributed to approximately 18,000 customers, including the US Treasury and the Department of Homeland Security. Attackers had persistent, silent access to victim environments for months before discovery.

The technical details are well-documented elsewhere. What matters is the question it raised: **should your network monitoring platform be a proprietary black box with privileged access to every device on your network?**

SolarWinds is not uniquely untrustworthy — any complex proprietary software is unauditable by its customers. But SUNBURST made that theoretical risk concrete in a way that no amount of vendor reassurance can walk back.

## Built for a different era

Even setting aside trust and cost, there's a more fundamental problem: SolarWinds NPM was designed for a network that no longer exists.

It was built around physical appliances, predictable polling intervals, and the assumption that everything worth monitoring speaks SNMP. That assumption is increasingly wrong. Kubernetes clusters don't have SNMP endpoints. Cloud-native services expose Prometheus metrics or OpenTelemetry traces, not MIB trees. And the network industry has been moving to **gNMI** for years — a streaming protocol where devices push state changes in real time, at sub-second granularity, rather than waiting to be polled every five minutes.

Nokia, Juniper, Arista, and Cisco all ship gNMI support on current platforms. SolarWinds has no gNMI support and no roadmap for it.

## What the alternative looks like

The open-source ecosystem has quietly assembled everything SolarWinds offers, and several things it can't. [Grafana Alloy](https://grafana.com/oss/alloy/) handles SNMP polling, OTLP ingestion, and syslog in one agent — no Windows licence required. gnmic handles gNMI streaming. ktranslate handles NetFlow and sFlow. [Grafana Loki](https://grafana.com/oss/loki/) stores logs. NetBox manages device inventory and IP space. Ansible handles config backup, drift detection, and remediation. [Grafana Cloud](https://grafana.com/products/cloud/) ties it together with a shared UI, alerting, and on-call management.

None of these charge per node. All are open source — auditable, forkable, extensible, and designed to interoperate through open standards rather than proprietary APIs.

This series shows you how to assemble that stack against a real simulated network. The result is a working replacement for everything SolarWinds NPM, NTA, IPAM, NCM, and Log Analyzer provide — running on infrastructure you control.

It's written for network engineers facing a renewal decision who want to understand what a migration actually involves before committing. For IT leaders who need to make the case to the business — with numbers, a migration plan, and an honest accounting of gaps. And for engineers in adjacent roles — platform, SRE, DevOps — who inherited a SolarWinds environment and want to understand how it fits into a modern observability stack. That last group tends to find this the most useful: SolarWinds expertise transfers to other SolarWinds shops. Prometheus, Grafana, and Ansible don't have that problem.

---

*Next in the series: [Part 2 — The Open Network Observability Stack](#), where we map every SolarWinds product to its open replacement, protocol by protocol.*

[Grafana Cloud](https://grafana.com/products/cloud/) is the easiest way to get started with metrics, logs, and dashboards. We have a generous forever-free tier and plans for every use case. [Sign up for free now.](https://grafana.com/auth/sign-up/create-user/)

**Tags:** Monitoring, Network Observability, Grafana, Prometheus, Open Source
