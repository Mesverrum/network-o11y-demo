#!/usr/bin/env python3
"""Apply suggested guards on a local clone of ktranslate PR 939. Do not push."""
from pathlib import Path

ROOT = Path.home() / "ktranslate-pr939"

RULE = ROOT / "pkg/util/rule/rule.go"
DEVICE = ROOT / "pkg/kt/device_types.go"
SNMP = ROOT / "pkg/kt/snmp.go"

rule = RULE.read_text()
old_init = '''func InitUserDeviceRuleSet(rulePath string, log logger.ContextL) error {
	byc, err := util.LoadFile(context.Background(), rulePath)
	if err != nil {
		return err
	}
	customs := map[string]map[string]string{}
	err = yaml.Unmarshal(byc, &customs)
	if err != nil {
		return err
	}

	deviceNameUserTags = map[string]map[string]string{}
	deviceIpUserTags = map[string]map[string]string{}

	for tk, mm := range customs {
		if net.ParseIP(tk) != nil {
			deviceIpUserTags[tk] = mm
		} else {
			deviceNameUserTags[tk] = mm
		}
	}

	log.Infof("Loaded %d user name device rules and %d user ip device rules.", len(deviceNameUserTags), len(deviceIpUserTags))

	return nil
}

// Global allowing any extra user tags to be pulled in.
func GetUserDeviceRuleSet(deviceName string, deviceIP string) map[string]string {
	if ud, ok := deviceNameUserTags[deviceName]; ok {
		return ud
	}
	if ud, ok := deviceIpUserTags[deviceIP]; ok {
		return ud
	}

	return nil
}
'''
new_init = '''func InitUserDeviceRuleSet(rulePath string, log logger.ContextL) error {
	if strings.TrimSpace(rulePath) == "" {
		return nil
	}

	byc, err := util.LoadFile(context.Background(), rulePath)
	if err != nil {
		return err
	}
	customs := map[string]map[string]string{}
	err = yaml.Unmarshal(byc, &customs)
	if err != nil {
		return err
	}

	deviceNameUserTags = map[string]map[string]string{}
	deviceIpUserTags = map[string]map[string]string{}

	for tk, mm := range customs {
		tk = strings.TrimSpace(tk)
		if tk == "" {
			log.Warnf("Skipping user device rule with empty key")
			continue
		}
		if ip := net.ParseIP(tk); ip != nil {
			deviceIpUserTags[ip.String()] = mm
			continue
		}
		if _, _, err := net.ParseCIDR(tk); err == nil {
			log.Warnf("Skipping CIDR user device rule %s (exact name/IP only in this change)", tk)
			continue
		}
		deviceNameUserTags[tk] = mm
	}

	log.Infof("Loaded %d user name device rules and %d user ip device rules.", len(deviceNameUserTags), len(deviceIpUserTags))

	return nil
}

// Global allowing any extra user tags to be pulled in.
func GetUserDeviceRuleSet(deviceName string, deviceIP string) map[string]string {
	if deviceNameUserTags != nil {
		if ud, ok := deviceNameUserTags[strings.TrimSpace(deviceName)]; ok {
			return ud
		}
	}
	if deviceIpUserTags != nil {
		ip := strings.TrimSpace(deviceIP)
		if parsed := net.ParseIP(ip); parsed != nil {
			ip = parsed.String()
		}
		if ud, ok := deviceIpUserTags[ip]; ok {
			return ud
		}
	}

	return nil
}
'''
if old_init not in rule:
    raise SystemExit("rule.go InitUserDeviceRuleSet block not found")
RULE.write_text(rule.replace(old_init, new_init, 1))

device = DEVICE.read_text()
old_dev = '''func (d *Device) InitUserTags(serviceName string, tags map[string]string, defaults map[string]string) {
	d.allUserTags = tags
	if serviceName != "ktranslate" {
		d.allUserTags["tags.container_service"] = serviceName
	}

	for k, v := range defaults {
		if _, ok := d.allUserTags[k]; !ok {
			d.allUserTags[k] = v
		}
	}
}
'''
new_dev = '''func (d *Device) InitUserTags(serviceName string, tags map[string]string, defaults map[string]string) {
	if tags == nil {
		tags = map[string]string{}
	}
	d.allUserTags = tags
	if serviceName != "ktranslate" {
		d.allUserTags["tags.container_service"] = serviceName
	}

	for k, v := range defaults {
		if _, ok := d.allUserTags[k]; !ok {
			d.allUserTags[k] = v
		}
	}
}
'''
if old_dev not in device:
    raise SystemExit("device_types.go InitUserTags block not found")
DEVICE.write_text(device.replace(old_dev, new_dev, 1))

snmp = SNMP.read_text()
old_snmp = '''	if serviceName != "ktranslate" {
		if d.UserTags == nil { // Prevent nil map assignment.
			d.UserTags = map[string]string{}
		}
		d.UserTags["container_service"] = serviceName
	}

	// Add in any defaults pass into the program externally.
	for k, v := range defaults {
		if _, ok := d.UserTags[k]; !ok {
			d.UserTags[k] = v
		}
	}
'''
new_snmp = '''	if d.UserTags == nil { // Prevent nil map assignment (defaults can land even when serviceName is ktranslate).
		d.UserTags = map[string]string{}
	}
	if serviceName != "ktranslate" {
		d.UserTags["container_service"] = serviceName
	}

	// Add in any defaults pass into the program externally.
	for k, v := range defaults {
		if _, ok := d.UserTags[k]; !ok {
			d.UserTags[k] = v
		}
	}
'''
if old_snmp not in snmp:
    raise SystemExit("snmp.go InitUserTags block not found")
SNMP.write_text(snmp.replace(old_snmp, new_snmp, 1))
print("patched", RULE, DEVICE, SNMP)
