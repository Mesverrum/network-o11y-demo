#!/usr/bin/env python3
import importlib.util

spec = importlib.util.spec_from_file_location("p", "scripts/patch-iface-bps-60s.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

samples = [
    'rate(kentik_snmp_ifHCInOctets{device_name=~"$instance"}[$__rate_interval]) * 8',
    '(sum by(if_interface_name) (rate(kentik_snmp_ifHCInOctets{device_name=~"$instance", if_interface_name=~"$interface_name"}[$__rate_interval]) * 8))',
    'topk(25, max by(if_interface_name) (rate(kentik_snmp_ifHCInOctets{device_name=~"$instance"}[$__rate_interval]) * 8))',
    '(sum by(device_name) (rate(kentik_snmp_ifHCInOctets{provider=~"$provider",device_name=~"$device_name"}[$__rate_interval]) * 8)) OR (max by(device_name) (kentik_snmp_PollingHealth{provider=~"$provider",device_name=~"$device_name"}) * 0)',
    'clamp_max(\n  topk(25,\n    max by(if_interface_name) (\n      rate(kentik_snmp_ifHCInOctets{device_name=~"$instance",if_interface_name=~"$interface_name"}[$__rate_interval])\n    ) * 8\n  ),\n  100e9\n)',
]
for s in samples:
    n, c = m.rewrite_expr(s)
    print("CHANGED" if c else "SAME")
    print(" OUT:", n.replace("\n", " | "))
    print()
