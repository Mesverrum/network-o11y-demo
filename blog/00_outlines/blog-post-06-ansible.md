# Post 6: Network Config Management with Ansible

**Series:** Network Observability Without the Lock-in
**Audience:** Network engineers, NetOps/NetDevOps teams
**Tone:** Technical — concepts + Ansible playbook walkthrough

---

## Outline

### I. The Missing Piece: Configuration Management
- Observability tells you what is happening — config management controls what should happen
- SolarWinds NCM: backup configs, detect drift, push changes, compliance reporting
- This is the last major gap in the open replacement stack

### II. Why Ansible for Network Config
- Agentless — no software to install on network devices
- Declarative playbooks: describe the desired state, Ansible figures out the diff
- Huge ecosystem of network modules: Nokia SR Linux, Juniper Junos, Arista EOS, Cisco IOS
- Native NetBox integration: use device inventory directly as the Ansible inventory source

### III. NetBox as the Ansible Inventory Source
- The `netbox.netbox.nb_inventory` Ansible plugin
- NetBox device list → Ansible inventory groups automatically
- Devices grouped by `device_role`, `site`, `platform` — the same labels used in Grafana
- When a device is added to NetBox, it automatically appears in the next Ansible run
- No more separate `hosts` files to maintain alongside your CMDB

### IV. Playbook Walkthrough: Configuring SR Linux

#### Baseline Config Push
- Example: push BGP neighbour configuration to all leaf nodes
- Using the `nokia.srlinux` Ansible collection
- Idempotent: running the playbook twice has no effect if config is already correct

#### Config Backup
- Pull running config from all devices and store in Git
- Scheduled via cron or triggered by a Grafana alert (config change detected via syslog)
- Diff against the previous backup: instant audit trail

#### Drift Detection and Remediation
- Define the desired state in a playbook
- Run in check mode (`--check`) to report drift without applying changes
- Run normally to remediate — push only what has changed

### V. The Closed Loop: Grafana → Ansible
- Scenario: Grafana alert fires — "BGP session down on leaf1"
- Syslog shows the NOTIFICATION message in Loki
- Runbook link in the alert points to the Ansible playbook that can re-establish the session
- Manually triggered first; eventually automated via Grafana IRM webhook → Ansible AWX/AAP
- This is the NetDevOps vision: observe → alert → remediate

### VI. Compliance Reporting
- Generate a compliance report: which devices match the desired BGP config template?
- Export results to NetBox custom fields or a Grafana dashboard
- SolarWinds NCM equivalent: built-in compliance policies — but proprietary rule language
  and no integration with external observability

### VII. What This Combination Replaces
- SolarWinds NCM: Ansible + Git + NetBox
- SolarWinds NTA + NPM alerts: Grafana Alerting + Ansible playbooks as runbooks
- The difference: every component is auditable, versionable, and extensible

---

**Next post:** Total Cost of Ownership and the Migration Path — making the business case and planning the cutover.
