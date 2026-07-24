# SNMP profile scratch space (maintainers only)

**Operators:** you do not need this directory. ktranslate ships with profiles from
[kentik/snmp-profiles](https://github.com/kentik/snmp-profiles). Discovery matches each
device's `sysObjectID` to a profile automatically.

**If your platform is missing:**

1. [Tutorial: Writing a custom yaml file for SNMP](https://github.com/kentik/ktranslate/wiki/Tutorial:-Writing-a-custom-yaml-file-for-SNMP)
2. Open a PR to [kentik/snmp-profiles](https://github.com/kentik/snmp-profiles)
3. Use a newer `ktranslate` image after merge — do not bind-mount local YAML for production labs

Files here may be kept temporarily while developing an upstream contribution. They are
**not** mounted by `compose-groups.generated.yaml` in the golden path.
