# ktranslate customer demo — SE talk track

**Stack:** [networko11ydev.grafana.net](https://networko11ydev.grafana.net/)  
**What this is:** a live look at network telemetry in Grafana Cloud, using the collector path customers can run today. A first-party Network product is still incoming.  
**How long:** about 15 minutes. If they want a full SolarWinds replacement plan, custom MIB work, or NCM/IPAM, pause and post in **#sme-network**.

Use the links below. You do not need to browse around the stack.

---

## Before you join

Open these in tabs. Set the time range to **Last 3 hours**.

| Stop | Link |
|------|------|
| Architecture | https://networko11ydev.grafana.net/d/ktranslate-architecture |
| Device Summary | https://networko11ydev.grafana.net/d/ktranslate-device-summary |
| Device Details | https://networko11ydev.grafana.net/d/ktranslate-device-details |
| Flow Summary | https://networko11ydev.grafana.net/d/ktranslate-flow-summary |
| Traceroute (NetPath equivalent) | https://networko11ydev.grafana.net/a/grafana-synthetic-monitoring-app/checks/7294 |

Make sure Device Summary is showing devices and recent data. If a dashboard is empty, you are probably on the wrong board or a very short time range.

---

## How to open

Most companies still keep application monitoring and network monitoring in separate tools. When something like checkout gets slow, the app team and the network team each open their own console and it turns into a debate about whose problem it is.

This demo is about putting the network in the same Grafana Cloud stack they already use for apps, logs, and traces. Same time range. Same dashboards. Same Assistant. An app or syseng person can ask whether they are actually hitting a network problem before they page a network SME. Network engineers like to call that **mean time to innocence**. SolarWinds cannot do that, because the network data is still stuck in a second product.

---

## Click path

### Architecture (~1 min)

Start with the diagram.

Network devices already speak a few standard protocols: SNMP for hardware counters, NetFlow or sFlow for who is talking to whom, and syslog or traps when something happens on the box. **ktranslate** sits in front of that. It discovers devices on the network, figures out what each one is from its SNMP identity, polls the right MIBs, and also receives flows and traps. It sends all of that out as OTLP. Grafana Cloud stores it. Alloy can still be the component that forwards OTLP — it does not have to be the thing that knows a Cisco from a Fortinet.

They are not buying a second network-management product, and they are not paying per interface the way SolarWinds does. The value is one platform: the people who already live in Grafana can see the network without switching tools. When Grafana ships a first-party Network product, this still makes sense because the data is already OTLP.

### Device Summary (~5 min)

This is the fleet view. Walk the tabs in order.

| Tab | What to say |
|-----|-------------|
| **Overview** | How many devices we have, whether we are still collecting from them, and whether anything is already in a bad state. |
| **Traffic** | Which devices are moving the most traffic right now. |
| **Resources** | CPU and memory on the switches, the same kind of resource picture they are used to on servers. |
| **Interfaces** | The usual network ticket: a port is down, or error counters are going up. |
| **Routing** | BGP is how routers tell each other they can still reach a neighbor. If that session drops, it is a path problem, not an application bug. |
| **Events** | Syslog and traps from the devices. The graphs tell you the trend; the events tell you when something actually happened. |

Click a device name to open Details. That is the main handoff in the demo.

### Device Details (~4 min)

Stay on Overview, then open **Interfaces**. If the Routing tab has data, show one BGP neighbor.

If someone opened a ticket on this device, this is the board they would land on: CPU, ports, errors, and the recent events for that one box. It is also the board an app or syseng person can open when they want to see if this box is why their service looks sick, without waiting for a network SME. It is a normal Grafana dashboard, so alerts, Explore, and drill-downs work the way they already expect.

### Flow Summary (~3 min)

Look at Conversations, then the Sankey. If the world map is empty, that is fine — private or internal addresses do not have a country.

SNMP provides metrics about the network hardware. Flow tells you which devices are talking to each other over that network. Together they let someone decide if the network is actually in the path of the problem, without opening a second tool.

### Close

The point is not a prettier network console. It is one platform. App and syseng teams can ask Assistant whether a down port, a BGP drop, or a noisy conversation is sitting under their service, and get an answer before they page the network SME. That is how you shrink **mean time to innocence**. Network people get fewer 2am “is it the network?” tickets. Everyone else stops waiting on a second login.

Assistant can also help draft a rule from a panel they are looking at, or tighten a noisy one. SolarWinds is years behind on that kind of investigation and alert-tuning workflow.

A switch can page the same way a service does. Alerts and Explore are the same tools they already use.

---

## Words they will use

| They say | What that means |
|----------|-----------------|
| SNMP | Periodic asks to each device for counters — CPU, ports, BGP, and so on. |
| Trap / syslog | The device sends an event when something happens: a link goes down, a neighbor drops, someone changes config. |
| NetFlow / NTA | Records of conversations: who talked to whom, and how much data moved. |
| Interface | A port on the device. |
| BGP | The protocol routers use to stay in sync about reachability. |
| NetPath | A traceroute that runs over and over from a probe you control. In Grafana that is Synthetic Monitoring. |
| NPM | SolarWinds’ device and interface monitoring. Summary + Details here. |
| NMS | Their current network monitor, usually SolarWinds. |
| Mean time to innocence | Our line: how fast a network engineer can show it is not their box, or an app/syseng person can see that it is, without paging anyone. |

---

## If they name a SolarWinds module

| They have | Show | What to tell them |
|-----------|------|-------------------|
| **NPM** | Summary + Details | Device and port health, in Grafana. |
| **NTA** | Flow Summary | Traffic conversations in the same UI. They do not need a second product licence. |
| **Log Analyzer / Kiwi / traps** | **Events** tab | Device logs sit next to the metrics, with the same time range. |
| **NetPath / IP SLA ping** | [This traceroute check](https://networko11ydev.grafana.net/a/grafana-synthetic-monitoring-app/checks/7294) | Hops from Ohio and North Virginia to `grafana.com`. |
| **Advanced Alerts** | Grafana Alerting | Rules run on the same queries as the dashboards. Assistant can help write or tune them. IRM if they also want on-call. |
| **PerfStack** | Explore or dashboard variables | They can overlay the series they care about. |
| **IPAM / NCM / SAM / wireless** | Skip it | Different project. Post in **#sme-network**. |

---

## Questions that come up

**“Is this Kentik?”**  
ktranslate started at Kentik and is open source. Grafana Cloud is what you are showing. This is not a Kentik licence.

**“When is Grafana’s own network product?”**  
It is on the roadmap. This is what we recommend until then, and it is not throwaway work — the devices still speak SNMP, flow, and syslog, and Grafana still stores OTLP.

**“Why not just Alloy `snmp_exporter`?”**  
Alloy’s SNMP exporter is a poller. You give it a target list and module names, and you already have to know every box and which MIBs to walk.

That is not usually where a SolarWinds shop is starting. They need to find devices, tell a Cisco from a Fortinet without maintaining a spreadsheet, poll the right counters, and also get traps and flow. ktranslate does that in one strategy:

| Need | Alloy SNMP exporter | ktranslate |
|------|---------------------|------------|
| Finding devices | You keep the list | It can scan a range or a credential group |
| Identifying the vendor / OS | You choose the module | It reads `sysObjectID` and applies a vendor profile |
| SNMP polling | Yes | Yes, driven by that profile |
| Traps | Separate work | The same collector that polls can listen for traps |
| Flow and syslog | Separate work | Included in the same approach |

If the fleet is small and already well documented, Alloy SNMP is enough. If they are trying to replace NPM and NTA, ktranslate is the shorter path. Alloy can still forward the OTLP either way. Those are different jobs.

**“Will this work on Cisco / Arista / Fortinet / Palo?”**  
Yes. Each platform has an SNMP profile. What you are looking at is live hardware, not screenshots. Unusual or very old gear might need a profile added, which is implementation work, not a new product.

**“We have UnDPs.”**  
Those custom OIDs become part of a profile and a normal Grafana panel. You do it once for that device type, not once per box.

**“We poll every 5 minutes. Can you go faster?”**  
Yes. These dashboards are updating about once a minute. Polling much faster than that can put real load on the device. If they need to know the moment something breaks, traps and syslog are the better signal.

**“Where do I see interface utilization, errors, or discards?”**  
Device Summary → Interfaces, then Device Details → Interfaces. Same counters they already know, and the syslog for that device is on the same board.

**“What about fans, power supplies, temperature?”**  
The Hardware tab, when that vendor’s profile includes those sensors. If a device does not show them, that MIB is not on the box — the dashboard is not missing a panel by accident.

**“A BGP neighbor dropped at 14:32.”**  
Routing tab for session state. Events tab for the syslog in that same window.

**“Where is NetPath?”**  
Open the [traceroute check](https://networko11ydev.grafana.net/a/grafana-synthetic-monitoring-app/checks/7294). That is the same idea: a probe you place, a hop list, and latency along the path. They can put private probes in their own sites the way they placed NetPath agents. The Flow Sankey is the NTA view (who talked to whom), not traceroute.

**“Can I see top talkers?”**  
Flow Summary → Conversations or Sankey.

**“We get trap storms. We also use parent/child alerts and Unmanage.”**  
Traps show up as logs. You can alert on volume, and you can suppress child alerts when the parent link is already down. Maintenance windows are silences in Grafana Alerting. It is not a copy of the Orion calendar, but the operations are there.

**“How do we tag site or role, like custom properties?”**  
Those become labels on the metrics. NetBox is the usual source of truth later, so the CMDB and the dashboards do not drift apart.

**“We cannot turn NPM off.”**  
They should not, at first. Run this next to SolarWinds. Start with a small set of devices they know well, compare the numbers, then widen. Move flows and logs first if they want a low-risk cutover. The easier internal story is “we are adding observability,” not “we are ripping out NPM this quarter.”

**“Can Grafana Assistant actually use this?”**  
Yes. That is the point of putting the network on the same platform. App and syseng teams can ask Assistant if they are hitting a network problem before they page the person who owns the routers. Network SMEs get fewer drive-by tickets. People also use it to draft or adjust alerts from the panel in front of them. SolarWinds does not have an equivalent. If they want to see it live, open Assistant on Device Details or Flow Summary and ask something concrete, like what is using bandwidth or whether any interfaces on this device look unhealthy. You do not need a scripted demo for that.

**“Our dashboards are already green. Why switch?”**  
They get one platform instead of two consoles and a Slack argument. App and syseng can check the network themselves, which is what people mean when they talk about mean time to innocence. Assistant can take that data into RCA and alert work, which SolarWinds is years behind on. Pricing is based on what they ingest, not on how many interfaces they added this year. The Grafana skills transfer to the rest of the estate. For money, use their actual SolarWinds renewal and a Cloud AE — not a generic range from a blog post.

---

## When to post in #sme-network

Anything past this walkthrough: a full replacement plan, NCM or IPAM, wireless / SD-WAN / voice, a large custom MIB library, collector sizing, or importing a huge SolarWinds alert pack. Write it down and post in **#sme-network**. Do not try to demo it on the spot.
