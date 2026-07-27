# Local SNMP profile overrides (temporary)

**Until [kentik/snmp-profiles#889](https://github.com/kentik/snmp-profiles/pull/889) merges**, the lab bind-mounts
`nokia/nokia-srlinux.yml` into ktranslate SNMP poller + discover containers so
`MemoryUsed` + `MemoryFree` tags produce auto-computed `MemoryUtilization`.

| Host path | Container path |
|-----------|----------------|
| `local/snmp-profiles/nokia/nokia-srlinux.yml` | `/etc/ktranslate/profiles/kentik_snmp/nokia/nokia-srlinux.yml` |

Configured in `templates/compose-snippet.yaml.tmpl` (regenerate with `make generate`).

**After upstream merge:** remove the bind-mount blocks from `compose-snippet.yaml.tmpl`,
run `make generate`, and recreate `ktranslate_snmp_*` — bundled image profiles are preferred.

**Operators (normal bring-up):** ktranslate ships profiles from
[kentik/snmp-profiles](https://github.com/kentik/snmp-profiles). Discovery matches each
device's `sysObjectID` to a profile automatically. New platforms →
[profile tutorial](https://github.com/kentik/ktranslate/wiki/Tutorial:-Writing-a-custom-yaml-file-for-SNMP)
→ PR upstream.
