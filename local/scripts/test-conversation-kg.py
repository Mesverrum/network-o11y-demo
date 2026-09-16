#!/usr/bin/env python3
"""Unit tests for conversation KG recording rules + model (no Grafana token)."""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "provision_conversation_kg",
    Path(__file__).resolve().parent / "provision-conversation-kg.py",
)
kg = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(kg)

INSIGHTS_SPEC = importlib.util.spec_from_file_location(
    "provision_network_device_insights",
    Path(__file__).resolve().parent / "provision-network-device-insights.py",
)
insights = importlib.util.module_from_spec(INSIGHTS_SPEC)
assert INSIGHTS_SPEC.loader is not None
INSIGHTS_SPEC.loader.exec_module(insights)


class ConversationKGContract(unittest.TestCase):
    def test_iface_catalog_stamps_peer(self) -> None:
        expr = kg._iface_catalog()
        self.assertIn('peer_interface", "leaf1:ethernet-1/49"', expr)
        self.assertIn('peer_interface", "spine1:ethernet-1/1"', expr)
        self.assertIn("iface_role", expr)

    def test_iface_connected_catalog_pairs(self) -> None:
        expr = kg._iface_connected()
        self.assertIn("spine1:ethernet-1/1", expr)
        self.assertIn("leaf1:ethernet-1/49", expr)
        self.assertIn("leaf-br2:ethernet-1/49", expr)

    def test_iface_connected_joins_live_lldp(self) -> None:
        expr = kg._iface_connected_live()
        self.assertIn("network_topology_edge_info", expr)
        self.assertIn("label_join", expr)
        self.assertIn("src_interface", expr)
        self.assertIn("dst_interface", expr)
        self.assertIn("Eth-(.+)", expr)
        self.assertIn("ethernet-", expr)
        self.assertIn("INTERFACE_NAME", expr)

    def test_interface_lookup_aliases_cable_labels(self) -> None:
        iface = next(e for e in kg.model_rules()["entities"] if e["type"] == "Interface")
        self.assertIn("src_interface", iface["lookup"]["interface"])
        self.assertIn("dst_interface", iface["lookup"]["interface"])
        peers = [e for e in iface["enrichedBy"] if "peer_interface" in e.get("labelValues", {})]
        self.assertEqual(len(peers), 1)

    def test_interface_connects_to_has_property_and_metrics(self) -> None:
        rels = [
            r
            for r in kg.model_rules()["relations"]
            if r["type"] == "CONNECTS_TO"
            and r["startEntityType"] == "Interface"
            and r["endEntityType"] == "Interface"
        ]
        self.assertFalse(
            any(
                r["type"] == "ROUTES"
                and r["startEntityType"] == "Interface"
                for r in kg.model_rules()["relations"]
            )
        )
        sources = {r["definedBy"]["source"] for r in rels}
        self.assertEqual(sources, {"PROPERTY_MATCH", "METRICS"})
        prop = next(r for r in rels if r["definedBy"]["source"] == "PROPERTY_MATCH")
        self.assertEqual(prop["definedBy"]["startEntityProperties"][0], "peer_interface")
        metrics = next(r for r in rels if r["definedBy"]["source"] == "METRICS")
        self.assertIn("interface_connected:info", metrics["definedBy"]["pattern"])

    def test_export_snapshots_match_generators(self) -> None:
        kg.export_yaml(kg.rule_specs())
        kg.export_model()
        rules = (ROOT / "fixtures" / "conversation-kg" / "recording-rules.yaml").read_text(
            encoding="utf-8"
        )
        model = (ROOT / "fixtures" / "conversation-kg" / "model-rules.yaml").read_text(
            encoding="utf-8"
        )
        self.assertIn("network_lab:interface_connected:info", rules)
        self.assertIn("network_topology_edge_info", rules)
        self.assertIn("peer_interface", rules)
        self.assertIn("interface | src_interface | dst_interface", model)
        self.assertIn("startEntityProperties: [peer_interface, env, site]", model)
        self.assertIn("type: CONNECTS_TO", model)
        self.assertNotIn(
            "Interface ROUTES Interface",
            model,
        )
        self.assertIn("type: Endpoint", model)
        self.assertNotIn("type: Host\n", model)
        self.assertNotIn("startEntityType: Host", model)

    def test_lab_clients_are_endpoint_not_host(self) -> None:
        types = {e["type"] for e in kg.model_rules()["entities"]}
        self.assertIn("Endpoint", types)
        self.assertNotIn("Host", types)
        routes = [
            r
            for r in kg.model_rules()["relations"]
            if r["type"] == "ROUTES"
            and r["startEntityType"] == "Endpoint"
            and r["endEntityType"] == "Endpoint"
        ]
        self.assertTrue(routes)
        attach = [
            r
            for r in kg.model_rules()["relations"]
            if r["type"] == "HOSTS" and r["endEntityType"] == "Endpoint"
        ]
        self.assertTrue(attach)

    def test_recording_rules_are_alloy_not_kentik(self) -> None:
        exprs = {
            "device_info": kg._device_info(),
            "iface_wan": kg._iface_wan(),
            "iface_fault": kg._iface_fault(),
            "conversation": kg._conversation_bytes(),
            "host_info": kg._host_info(),
        }
        for name, expr in exprs.items():
            self.assertNotIn("kentik_", expr, msg=name)
            self.assertNotRegex(
                expr, r"(?<!alloy_)network_io_by_flow_bytes", msg=name
            )
        self.assertIn("snmp_CPU", exprs["device_info"])
        self.assertIn("snmp_ifAdminStatus", exprs["iface_wan"])
        self.assertIn("snmp_ifOperStatus", exprs["iface_fault"])
        self.assertIn("alloy_network_io_by_flow_bytes", exprs["conversation"])
        self.assertIn("increase(", exprs["conversation"])
        self.assertIn("ip-172-17-0-1", exprs["host_info"])

    def test_insights_are_alloy_not_kentik(self) -> None:
        for expr in (
            insights._cpu(),
            insights._memory(),
            insights._snmp_unhealthy(),
            insights._access_if_down(),
            insights._interface_down(),
        ):
            self.assertNotIn("kentik_", expr)
        self.assertEqual(insights.DETAIL_UID, "alloy-device-details")
        self.assertIn("snmp_CPU", insights._cpu())
        self.assertIn("device:snmp_MemoryUtilization:percent", insights._memory())
        self.assertIn('job="alloy-snmp"', insights._snmp_unhealthy())


if __name__ == "__main__":
    unittest.main()
