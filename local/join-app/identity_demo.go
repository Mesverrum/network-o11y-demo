package main

import (
	"context"

	"go.opentelemetry.io/otel"
	"go.opentelemetry.io/otel/attribute"
	"go.opentelemetry.io/otel/metric"
)

// Lab chassis IDs from live gnmic LLDP neighbor_id (spine sees leaf MACs; leaves see spine).
// Used only for the identity-model prove/disprove datasets — not discovery.
var labChassis = map[string]string{
	"spine1": "1a:dc:04:ff:00:00",
	"leaf1":  "1a:cb:02:ff:00:00",
	"leaf2":  "1a:c1:03:ff:00:00",
}

var labLinks = []struct {
	src, srcPort, dst, dstPort string
}{
	{"spine1", "ethernet-1/1", "leaf1", "ethernet-1/49"},
	{"spine1", "ethernet-1/2", "leaf2", "ethernet-1/49"},
	{"leaf1", "ethernet-1/49", "spine1", "ethernet-1/1"},
	{"leaf2", "ethernet-1/49", "spine1", "ethernet-1/2"},
}

// registerIdentityDemoMetrics emits parallel entity graphs labeled demo_model=…
// so the join dashboard can tab between prove/disprove scenarios.
func registerIdentityDemoMetrics() error {
	meter := otel.Meter("clos-join-demo")
	tester := attribute.String("tester_id", testerID())

	type kv = []attribute.KeyValue
	var devices, edges, aliases, addresses []kv

	addDevice := func(model, observer, id, title, kind string, extra ...attribute.KeyValue) {
		attrs := kv{
			tester,
			attribute.String("demo_model", model),
			attribute.String("observer", observer),
			attribute.String("id", id),
			attribute.String("title", title),
			attribute.String("kind", kind),
		}
		attrs = append(attrs, extra...)
		devices = append(devices, attrs)
	}
	addEdge := func(model, observer, src, dst, kind, edgeID string, extra ...attribute.KeyValue) {
		attrs := kv{
			tester,
			attribute.String("demo_model", model),
			attribute.String("observer", observer),
			attribute.String("id", edgeID),
			attribute.String("src", src),
			attribute.String("dst", dst),
			attribute.String("kind", kind),
		}
		attrs = append(attrs, extra...)
		edges = append(edges, attrs)
	}
	addAlias := func(model, id, aliasID string) {
		aliases = append(aliases, kv{
			tester,
			attribute.String("demo_model", model),
			attribute.String("id", id),
			attribute.String("alias_id", aliasID),
			attribute.String("kind", "same_as"),
		})
	}
	addAddress := func(model, addr, boundID string) {
		addresses = append(addresses, kv{
			tester,
			attribute.String("demo_model", model),
			attribute.String("id", "addr:"+addr),
			attribute.String("address", addr),
			attribute.String("bound_id", boundID),
			attribute.String("kind", "network.address"),
		})
	}
	type verdict struct {
		attrs []attribute.KeyValue
		ok    int64
	}
	var verdictList []verdict
	addVerdict := func(model, check string, ok bool) {
		v := int64(0)
		res := "fail"
		if ok {
			v = 1
			res = "pass"
		}
		verdictList = append(verdictList, verdict{
			ok: v,
			attrs: kv{
				tester,
				attribute.String("demo_model", model),
				attribute.String("check", check),
				attribute.String("result", res),
			},
		})
	}

	devicesClos := []string{"spine1", "leaf1", "leaf2"}

	// ── hostname: both observers use name:<sysName> → join works ──
	for _, d := range devicesClos {
		nid := "name:" + d
		addDevice("hostname", "snmp", nid, d, "network.device")
		addDevice("hostname", "lldp", nid, d, "network.device")
	}
	for _, l := range labLinks {
		addEdge("hostname", "lldp", "name:"+l.src, "name:"+l.dst, "connected_to",
			"hostname-"+l.src+"-"+l.dst)
	}
	addVerdict("hostname", "observer_join", true)
	addVerdict("hostname", "app_path_join", true)
	addVerdict("hostname", "edge_discipline", false) // device↔device without interface entities

	// ── hostname_poison: SNMP keys diverge from LLDP sysName → join breaks ──
	for _, d := range devicesClos {
		addDevice("hostname_poison", "snmp", "name:"+d+"-poller", d+" (poller)", "network.device")
		addDevice("hostname_poison", "lldp", "name:"+d, d, "network.device")
	}
	for _, l := range labLinks {
		addEdge("hostname_poison", "lldp", "name:"+l.src, "name:"+l.dst, "connected_to",
			"poison-"+l.src+"-"+l.dst)
	}
	addVerdict("hostname_poison", "observer_join", false)
	addVerdict("hostname_poison", "app_path_join", false)
	addVerdict("hostname_poison", "edge_discipline", false)

	// ── mac_alias: LLDP primary=mac:, SNMP primary=name: + same_as alias → exact join ──
	for _, d := range devicesClos {
		mac := "mac:" + labChassis[d]
		name := "name:" + d
		addDevice("mac_alias", "snmp", name, d, "network.device")
		addDevice("mac_alias", "lldp", mac, d, "network.device")
		addAlias("mac_alias", name, mac)
	}
	for _, l := range labLinks {
		addEdge("mac_alias", "lldp",
			"mac:"+labChassis[l.src], "mac:"+labChassis[l.dst], "connected_to",
			"mac-"+l.src+"-"+l.dst)
	}
	addVerdict("mac_alias", "observer_join", true)
	addVerdict("mac_alias", "app_path_join", true)
	addVerdict("mac_alias", "edge_discipline", false)

	// ── address: shared network.address nodes bridge app/flow ↔ hosts ──
	for _, d := range devicesClos {
		addDevice("address", "snmp", "name:"+d, d, "network.device")
	}
	addDevice("address", "host", "host:client1", "client1", "host")
	addDevice("address", "host", "host:client2", "client2", "host")
	addAddress("address", "172.17.0.1", "host:client1")
	addAddress("address", "172.17.0.2", "host:client2")
	addEdge("address", "overlay", "host:client1", "name:leaf1", "attached", "addr-c1-l1")
	addEdge("address", "overlay", "host:client2", "name:leaf2", "attached", "addr-c2-l2")
	addEdge("address", "app", "addr:172.17.0.1", "addr:172.17.0.2", "communicates", "addr-flow")
	addVerdict("address", "observer_join", true)
	addVerdict("address", "app_path_join", true)
	addVerdict("address", "edge_discipline", true)

	// ── iface: interface-level connected_to (no port attrs on device edges) ──
	for _, d := range devicesClos {
		addDevice("iface", "snmp", "name:"+d, d, "network.device")
	}
	for _, l := range labLinks {
		srcIF := "name:" + l.src + "|" + l.srcPort
		dstIF := "name:" + l.dst + "|" + l.dstPort
		addDevice("iface", "lldp", srcIF, l.src+":"+l.srcPort, "network.interface")
		addDevice("iface", "lldp", dstIF, l.dst+":"+l.dstPort, "network.interface")
		addEdge("iface", "lldp", srcIF, dstIF, "connected_to",
			"iface-"+l.src+"-"+l.srcPort)
	}
	addVerdict("iface", "observer_join", true)
	addVerdict("iface", "app_path_join", true)
	addVerdict("iface", "edge_discipline", true)

	// ── edge_attrs (Q3 disprove): device↔device adjacent_to WITH port attrs on the edge ──
	// Same smell as retired adjacent_to in the candidate model.
	for _, d := range devicesClos {
		addDevice("edge_attrs", "lldp", "name:"+d, d, "network.device")
	}
	for _, l := range labLinks {
		addEdge("edge_attrs", "lldp", "name:"+l.src, "name:"+l.dst, "adjacent_to",
			"edgeattrs-"+l.src+"-"+l.srcPort,
			attribute.String("src_port", l.srcPort),
			attribute.String("dst_port", l.dstPort),
			attribute.String("smell", "attrs_on_edge"),
		)
	}
	addVerdict("edge_attrs", "observer_join", true)
	addVerdict("edge_attrs", "app_path_join", false) // no overlay / VRF — can't place the app
	addVerdict("edge_attrs", "edge_discipline", false)

	// ── vrf (Q3 prove): MAC-VRF as entity; ports live on interface entities; EVI/VNI/RT on VRF ──
	for _, d := range devicesClos {
		addDevice("vrf", "snmp", "name:"+d, d, "network.device")
	}
	addDevice("vrf", "overlay", "vrf:vrf-1", "vrf-1", "network.vrf",
		attribute.String("vrf_type", "mac-vrf"),
		attribute.String("evi", "1"),
		attribute.String("vni", "1"),
		attribute.String("route_target", "target:100:1"),
	)
	addDevice("vrf", "host", "host:client1", "client1", "host")
	addDevice("vrf", "host", "host:client2", "client2", "host")
	addDevice("vrf", "overlay", "name:leaf1|ethernet-1/1", "leaf1:ethernet-1/1", "network.interface")
	addDevice("vrf", "overlay", "name:leaf2|ethernet-1/1", "leaf2:ethernet-1/1", "network.interface")
	addAddress("vrf", "172.17.0.1", "host:client1")
	addAddress("vrf", "172.17.0.2", "host:client2")
	// Underlay: attribute-free interface connected_to
	for _, l := range labLinks {
		srcIF := "name:" + l.src + "|" + l.srcPort
		dstIF := "name:" + l.dst + "|" + l.dstPort
		addDevice("vrf", "lldp", srcIF, l.src+":"+l.srcPort, "network.interface")
		addDevice("vrf", "lldp", dstIF, l.dst+":"+l.dstPort, "network.interface")
		addEdge("vrf", "lldp", srcIF, dstIF, "connected_to", "vrf-underlay-"+l.src+"-"+l.srcPort)
	}
	// Overlay membership — VRF owns access interfaces (attrs live on the VRF entity above)
	addEdge("vrf", "overlay", "name:leaf1|ethernet-1/1", "vrf:vrf-1", "member_of", "vrf-mem-l1")
	addEdge("vrf", "overlay", "name:leaf2|ethernet-1/1", "vrf:vrf-1", "member_of", "vrf-mem-l2")
	addEdge("vrf", "overlay", "host:client1", "name:leaf1|ethernet-1/1", "attached", "vrf-c1-if")
	addEdge("vrf", "overlay", "host:client2", "name:leaf2|ethernet-1/1", "attached", "vrf-c2-if")
	addEdge("vrf", "app", "addr:172.17.0.1", "addr:172.17.0.2", "communicates", "vrf-flow")
	addVerdict("vrf", "observer_join", true)
	addVerdict("vrf", "app_path_join", true)
	addVerdict("vrf", "edge_discipline", true)

	_, err := meter.Int64ObservableGauge("entity.demo.device.info",
		metric.WithDescription("Identity-demo network.device nodes per demo_model"),
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			for _, attrs := range devices {
				o.Observe(1, metric.WithAttributes(attrs...))
			}
			return nil
		}),
	)
	if err != nil {
		return err
	}

	_, err = meter.Int64ObservableGauge("entity.demo.edge.info",
		metric.WithDescription("Identity-demo relationships per demo_model"),
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			for _, attrs := range edges {
				o.Observe(1, metric.WithAttributes(attrs...))
			}
			return nil
		}),
	)
	if err != nil {
		return err
	}

	_, err = meter.Int64ObservableGauge("entity.demo.alias.info",
		metric.WithDescription("Identity-demo same_as aliases (name↔mac)"),
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			for _, attrs := range aliases {
				o.Observe(1, metric.WithAttributes(attrs...))
			}
			return nil
		}),
	)
	if err != nil {
		return err
	}

	_, err = meter.Int64ObservableGauge("entity.demo.address.info",
		metric.WithDescription("Identity-demo network.address shared nodes"),
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			for _, attrs := range addresses {
				o.Observe(1, metric.WithAttributes(attrs...))
			}
			return nil
		}),
	)
	if err != nil {
		return err
	}

	_, err = meter.Int64ObservableGauge("entity.demo.verdict",
		metric.WithDescription("1=pass 0=fail for identity-demo checks"),
		metric.WithInt64Callback(func(_ context.Context, o metric.Int64Observer) error {
			for _, v := range verdictList {
				o.Observe(v.ok, metric.WithAttributes(v.attrs...))
			}
			return nil
		}),
	)
	return err
}
