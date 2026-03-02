# Network Config Management with Ansible

*Part 6 of 7 — Network Observability Without the Lock-in*

---

Observability tells you what's happening on your network. It doesn't control what the network is supposed to do. For that, you need configuration management: a system that defines the desired state of every device, detects when actual state drifts from it, and can push corrections when needed.

In the SolarWinds world, this is NCM — Network Configuration Manager. In the open stack, the same capabilities come from three components: **Ansible** for execution, **NetBox** as the inventory source, and **Git** as the config archive and audit trail.

## Why Ansible for network config

Ansible became the standard for network configuration management for reasons that hold up on real networks. It's agentless — no software to install on the device side, which matters when you're managing hardware that's been running for years and you have no appetite for additional moving parts. Ansible connects over SSH, NETCONF, or gNMI depending on the module, and issues commands directly.

It's also declarative where it matters. You describe the desired state — "this BGP neighbour should have peer-AS 65001 and this import policy" — and the network modules figure out what commands to issue. Run the same playbook twice on an already-correct device; nothing changes. That idempotency is what makes it safe to run on a schedule without human supervision.

And the module coverage is broad enough for real environments. Nokia SR Linux, Juniper Junos, Arista EOS, Cisco IOS — all have maintained Ansible Galaxy collections covering interfaces, BGP, routing policies, and VLANs. You're not starting from scratch for each vendor.

## NetBox as the Ansible inventory source

Most Ansible playbooks start with an inventory — a list of which devices to target, organized into groups. Traditionally, this is a static `hosts` file someone maintains by hand alongside the CMDB. It goes stale as devices change.

The `netbox.netbox.nb_inventory` Ansible plugin solves this by generating inventory dynamically from NetBox at runtime:

```yaml
# inventory/netbox.yml
plugin: netbox.netbox.nb_inventory
api_endpoint: http://netbox.network-tools.svc.cluster.local
token: "{{ lookup('env', 'NETBOX_TOKEN') }}"
group_by:
  - device_roles
  - sites
  - platforms
```

When Ansible runs, it queries NetBox and automatically groups devices by `device_role`, `site`, and `platform` — the same taxonomy driving the Grafana label filters. A device tagged `device_role: leaf` appears in the Ansible group `device_roles_leaf`. Target it in a playbook with `hosts: device_roles_leaf`.

When a new leaf is added to NetBox, it automatically appears in the next Ansible run. No `hosts` file to update. NetBox is the single source of truth for both the observability pipeline and the automation layer.

## Playbook walkthrough

### Pushing baseline BGP configuration

The following playbook pushes a BGP neighbour configuration to all leaf nodes using the `nokia.srlinux` collection. The `state: merged` parameter applies only what's declared — it doesn't remove BGP neighbours not in the list. Use `state: replaced` to enforce a complete desired state:

```yaml
---
- name: Configure BGP underlay neighbors on leaf nodes
  hosts: device_roles_leaf
  gather_facts: false
  tasks:
    - name: Apply BGP neighbor configuration
      nokia.srlinux.config:
        config:
          network-instance:
            - name: default
              protocols:
                bgp:
                  neighbor:
                    - peer-address: "{{ item.peer_ip }}"
                      peer-as: "{{ item.peer_as }}"
                      peer-group: underlay
        state: merged
```

### Config backup

Backing up running configurations is one of the most valuable things NCM does. In Ansible:

```yaml
---
- name: Back up running configuration
  hosts: all
  gather_facts: false
  tasks:
    - name: Fetch running config
      nokia.srlinux.config:
        state: gathered
      register: running_config

    - name: Save to file
      copy:
        content: "{{ running_config.gathered | to_nice_json }}"
        dest: "backups/{{ inventory_hostname }}_{{ ansible_date_time.date }}.json"
      delegate_to: localhost
```

Run this on a schedule and commit the output to Git. `git diff` between two backup files shows exactly what changed and when. SolarWinds NCM stores backups in SQL Server. The open approach stores them in Git — diffable, searchable, auditable, and unaffected if the monitoring platform has a database failure.

### Drift detection

Drift detection means checking whether actual device config matches the desired state without pushing changes. In Ansible, that's the `--check` flag:

```bash
ansible-playbook playbooks/configure-bgp-neighbors.yml --check --diff
```

`--check` runs in dry-run mode — shows what *would* change without applying it. `--diff` shows the specific differences. Run this on a schedule and pipe output to a notification channel, and you have continuous compliance monitoring without a separate compliance engine.

## The closed loop: Grafana alert to Ansible remediation

The most powerful aspect of this stack is that observability and automation share the same inventory and can be wired together.

**Scenario:** Grafana detects that a BGP session on `leaf2` has been `Idle` for more than 60 seconds. The alert fires. The notification includes:

1. A link to the BGP dashboard, pre-filtered to `leaf2`, showing the state change
2. A link to the runbook describing investigation steps
3. A link to the Ansible playbook that can re-establish the BGP configuration

Initially, the playbook run is manual — the on-call engineer reviews, decides a config push is appropriate, and triggers it. But the architecture supports full automation: a [Grafana IRM](https://grafana.com/products/cloud/irm/) webhook fires when the alert is acknowledged, triggers an Ansible AWX job template, and Grafana confirms the session returns to Established.

This is the NetDevOps vision: the same system that observes the problem identifies the playbook that fixes it. SolarWinds NCM has no equivalent — it's a separate product with no native integration into alerting or incident management.

## What this combination replaces

| SolarWinds | Open equivalent |
|---|---|
| NCM config backup | Ansible + Git (scheduled backup playbook) |
| NCM compliance policies | Ansible `--check` mode + reporting |
| NCM config push | Ansible playbooks with `state: merged/replaced` |
| NCM audit trail | Git history on the backup repository |
| NPM alert → manual NCM fix | Grafana alert → Ansible AWX webhook |

Every piece is auditable and version-controlled. The playbooks that configure your network live in the same Git repository as the dashboards that observe it. A pull request documents why a change was made. A merge record documents when it was applied.

---

*Next: [Part 7 — Total Cost of Ownership and the Migration Path](#), where we make the business case and plan the cutover.*

[Grafana Cloud](https://grafana.com/products/cloud/) is the easiest way to get started with metrics, logs, traces, and dashboards. We have a generous forever-free tier and plans for every use case. [Sign up for free now.](https://grafana.com/auth/sign-up/create-user/)

**Tags:** Network Observability, Ansible, NetBox, Configuration Management, NetDevOps, Grafana IRM
