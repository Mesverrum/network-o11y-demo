#!/usr/bin/env python3
"""Regression checks for dynamic Alloy SNMP discovery."""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DISCOVER = ROOT / "scripts" / "alloy-snmp-discover.sh"
SCRAPE = ROOT / "scripts" / "render-alloy-snmp-scrape.sh"
FINGERPRINTERS = Path(
    os.environ.get(
        "ALLOY_SNMP_TEST_FINGERPRINTERS",
        ROOT / "fixtures" / "alloy-snmp" / "fingerprinters.yml",
    )
)
NOKIA_TOPOLOGY = ROOT / "fixtures" / "alloy-snmp" / "modules" / "nokia" / "nokia_srlinux_topo.yml"


class DynamicDiscoveryContract(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.discover = DISCOVER.read_text(encoding="utf-8")
        cls.scrape = SCRAPE.read_text(encoding="utf-8")
        cls.fingerprinters = FINGERPRINTERS.read_text(encoding="utf-8")
        cls.nokia_topology = NOKIA_TOPOLOGY.read_text(encoding="utf-8")

    def test_management_subnet_replaces_device_ip_inventory(self) -> None:
        self.assertIn("docker network inspect", self.discover)
        self.assertIn(".IPAM.Config", self.discover)
        self.assertNotIn('for n in "${SRL_NODES[@]}"', self.discover)
        self.assertNotIn('cidrs+=("${ip}/32")', self.discover)

    def test_ip_shuffle_cannot_apply_a_stale_name_pin(self) -> None:
        self.assertFalse((ROOT / "scripts" / "render-snmp-topology-overrides.sh").exists())
        self.assertNotRegex(self.discover, r'echo\s+"  name:')
        self.assertIn("removing legacy address/name topology overrides", self.discover)

    def test_nokia_topology_modules_come_from_sysobjectid_fingerprint(self) -> None:
        matcher = re.search(
            r"regex: \^\\\.\?1\\\.3\\\.6\\\.1\\\.4\\\.1\\\.6527\\\.1\\\.20\\\.26.*?"
            r"modules_topology:\s*(?:&\w+\s*)?\n\s+- nokia_srlinux_topo\s*\n",
            self.fingerprinters,
            flags=re.DOTALL,
        )
        self.assertIsNotNone(matcher)
        self.assertIn("snmp_tBgpPeerNgConnState", self.nokia_topology)
        self.assertIn("snmp_lldpRemSysName", self.nokia_topology)

    def test_site_metadata_does_not_select_discovery_targets(self) -> None:
        self.assertIn('regex         = ".*-br([12])$"', self.scrape)
        self.assertIn('replacement   = "branch$1"', self.scrape)
        for device in ("spine1", "leaf1", "leaf2", "leaf-br1", "leaf-br2"):
            self.assertNotIn(device, self.scrape)

    def test_stale_addresses_age_out_of_persistent_state(self) -> None:
        self.assertIn('state_path       = "/var/lib/alloy/data/snmp-discovery.state.json"', self.scrape)
        self.assertIn("misses           = 3", self.scrape)


if __name__ == "__main__":
    unittest.main()
