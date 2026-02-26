#!/usr/bin/env bash
# fix-networking.sh — apply Clabbernetes VxLAN, ARP, telemetry port-forwarding,
# and SR Linux telemetry configuration (one-shot).
#
# Run this once after the topology is first deployed. After that, the
# network reconciler Deployment (k8s/network-reconciler.yaml) keeps things
# correct automatically across pod restarts.
#
# What this script does (and why):
#
#   1. Sets VxLAN remote to 0.0.0.0 on every launcher-pod VxLAN interface.
#      Why: Clabbernetes sets VxLAN remote = ClusterIP of the peer service.
#      kube-proxy DNATs ClusterIP → pod-IP in transit, so incoming VxLAN packets
#      arrive with pod-IP as their source. The kernel drops them because pod-IP ≠
#      configured remote. Setting remote=0.0.0.0 disables this source check; the
#      FDB catch-all (00:00:00:00:00:00 → ClusterIP) still routes outbound traffic
#      correctly via kube-proxy.
#      PERMANENT — ClusterIPs are stable across pod restarts; no re-application needed.
#
#   2. Disables kernel ARP on transit interfaces (veths + VxLANs).
#      Why: Clabbernetes uses TC mirred-mirror mode to forward L2 frames into VxLAN
#      interfaces. The Linux kernel still processes the original copy of each frame,
#      generating ARP replies from launcher-pod MAC addresses. These spurious replies
#      corrupt client ARP caches and break end-to-end L2 connectivity. Disabling ARP
#      on transit interfaces stops them.
#      Re-applied by the reconciler on pod restart.
#
#   3. Clamps client eth1 MTU to 1400.
#      Why: Two VxLAN layers (Clabbernetes outer + SR Linux EVPN inner) add ~100 bytes
#      of encapsulation overhead. Without this clamp, TCP jumbo frames are fragmented
#      and then silently dropped by the intermediate VxLAN path, stalling all throughput
#      between client nodes.
#      Re-applied by the reconciler on pod restart.
#
#   4. Adds iptables DNAT rules in each SR Linux launcher pod to forward:
#        - UDP 161   → SR Linux SNMP agent   (for Alloy's prometheus.exporter.snmp)
#        - TCP 57400 → SR Linux gNMI server  (for gnmic)
#      Why: SR Linux containers run inside the launcher pod's Docker daemon on an
#      internal bridge network, not on the pod's eth0. Without DNAT, Alloy and gnmic
#      cannot reach SR Linux management ports from the Kubernetes network. iptables
#      DNAT in the launcher pod forwards traffic that arrives on eth0 into the Docker
#      bridge where SR Linux actually listens. The companion Services
#      (node-telemetry-services.yaml) route cluster traffic to these launcher pods.
#      Re-applied by the reconciler on pod restart.
#
#   5. Configures SNMP v2c, sFlow, and gNMI on each SR Linux node via sr_cli.
#      Why: The startup-config-based approach is unreliable in Clabbernetes — SR Linux's
#      default running config already includes a community entry for 'public', which
#      causes a uniqueness conflict when the startup config tries to add the same entry
#      via `set /`. Applying live via sr_cli is idempotent and sidesteps the conflict.

set -euo pipefail

NAMESPACE="${1:-network-lab}"

info() { echo "==> $*"; }
warn() { echo "WARN: $*" >&2; }

# ─── Helpers ──────────────────────────────────────────────────────────────────

pod_for() {
  kubectl get pod -n "$NAMESPACE" \
    -l "clabernetes/topologyNode=${1}" \
    -o jsonpath='{.items[0].metadata.name}' 2>/dev/null
}

fix_launcher() {
  local pod="$1"; shift
  # Fix VxLAN remotes (set to 0.0.0.0) and disable ARP on all transit ifaces.
  # When the original remote is still set, capture and use it as the FDB catch-all.
  # For links where remote is already 0.0.0.0 (script ran before), ensure_fdb
  # below will add any missing FDB entries using Kubernetes service lookups.
  kubectl exec -n "$NAMESPACE" "$pod" -- sh -c '
    for iface in $(ip link show | grep "^[0-9]" | awk "{print \$2}" | tr -d ":" | sed "s/@.*//" | grep "^vx-"); do
      original_remote=$(ip -d link show dev "$iface" 2>/dev/null | grep -o "remote [0-9.]*" | awk "{print \$2}")
      ip link set dev "$iface" type vxlan remote 0.0.0.0 2>/dev/null \
        && echo "  vxlan remote cleared: $iface" \
        || echo "  WARN: could not clear remote on $iface"
      if [ -n "$original_remote" ] && [ "$original_remote" != "0.0.0.0" ]; then
        bridge fdb append 00:00:00:00:00:00 dev "$iface" dst "$original_remote" 2>/dev/null || true
      fi
    done

    # ARP off on all transit interfaces (veths + VxLANs)
    for iface in $(ip link show | grep "^[0-9]" | awk "{print \$2}" | tr -d ":" | sed "s/@.*//" \
        | grep -E "^(vx-|$(hostname)-e|$(hostname)-eth)"); do
      ip link set dev "$iface" arp off 2>/dev/null \
        && echo "  arp off: $iface" || true
    done
  ' 2>&1 | sed "s/^/  [$pod] /"
}

# Look up ClusterIP for a -vx Clabbernetes service.
vx_svc_ip() {
  kubectl get svc -n "$NAMESPACE" "${1}-vx" \
    -o jsonpath='{.spec.clusterIP}' 2>/dev/null
}

# Ensure a catch-all FDB entry (00:00:00:00:00:00) exists for a given VxLAN
# interface on a launcher pod. Idempotent — no-op if already present.
ensure_fdb() {
  local pod="$1" iface="$2" dst="$3"
  [[ -z "$dst" ]] && { warn "ensure_fdb: empty dst for $iface on $pod"; return; }
  kubectl exec -n "$NAMESPACE" "$pod" -- sh -c "
    if bridge fdb show dev ${iface} 2>/dev/null | grep -q '00:00:00:00:00:00'; then
      echo '  FDB ok: ${iface}'
    else
      bridge fdb append 00:00:00:00:00:00 dev ${iface} dst ${dst} 2>/dev/null && \
        echo '  FDB added: ${iface} -> ${dst}' || \
        echo '  WARN: FDB add failed: ${iface} -> ${dst} (interface may not exist)'
    fi
  " 2>&1 | grep -v '^$' | sed "s/^/  [$pod] /"
}

ensure_all_fdbs() {
  info "Ensuring VxLAN FDB catch-all entries for all topology links..."
  # Look up all -vx service ClusterIPs once
  local spine1_vx spine2_vx leaf1_vx leaf2_vx leaf3_vx client1_vx client2_vx client3_vx collector_vx
  spine1_vx=$(vx_svc_ip spine1);    spine2_vx=$(vx_svc_ip spine2)
  leaf1_vx=$(vx_svc_ip leaf1);      leaf2_vx=$(vx_svc_ip leaf2);      leaf3_vx=$(vx_svc_ip leaf3)
  client1_vx=$(vx_svc_ip client1);  client2_vx=$(vx_svc_ip client2);  client3_vx=$(vx_svc_ip client3)
  collector_vx=$(vx_svc_ip collector)

  local pod
  # Spine launchers
  pod=$(pod_for spine1) && [[ -n "$pod" ]] && {
    ensure_fdb "$pod" vx-spine1-e1-1 "$leaf1_vx"
    ensure_fdb "$pod" vx-spine1-e1-2 "$leaf2_vx"
    ensure_fdb "$pod" vx-spine1-e1-3 "$leaf3_vx"
  }
  pod=$(pod_for spine2) && [[ -n "$pod" ]] && {
    ensure_fdb "$pod" vx-spine2-e1-1 "$leaf1_vx"
    ensure_fdb "$pod" vx-spine2-e1-2 "$leaf2_vx"
    ensure_fdb "$pod" vx-spine2-e1-3 "$leaf3_vx"
  }
  # Leaf launchers
  pod=$(pod_for leaf1) && [[ -n "$pod" ]] && {
    ensure_fdb "$pod" vx-leaf1-e1-49  "$spine1_vx"
    ensure_fdb "$pod" vx-leaf1-e1-50  "$spine2_vx"
    ensure_fdb "$pod" vx-leaf1-e1-1   "$client1_vx"
    ensure_fdb "$pod" vx-leaf1-e1-2   "$collector_vx"
  }
  pod=$(pod_for leaf2) && [[ -n "$pod" ]] && {
    ensure_fdb "$pod" vx-leaf2-e1-49  "$spine1_vx"
    ensure_fdb "$pod" vx-leaf2-e1-50  "$spine2_vx"
    ensure_fdb "$pod" vx-leaf2-e1-1   "$client2_vx"
  }
  pod=$(pod_for leaf3) && [[ -n "$pod" ]] && {
    ensure_fdb "$pod" vx-leaf3-e1-49  "$spine1_vx"
    ensure_fdb "$pod" vx-leaf3-e1-50  "$spine2_vx"
    ensure_fdb "$pod" vx-leaf3-e1-1   "$client3_vx"
  }
  # Client launchers
  pod=$(pod_for client1) && [[ -n "$pod" ]] && ensure_fdb "$pod" vx-client1-eth1  "$leaf1_vx"
  pod=$(pod_for client2) && [[ -n "$pod" ]] && ensure_fdb "$pod" vx-client2-eth1  "$leaf2_vx"
  pod=$(pod_for client3) && [[ -n "$pod" ]] && ensure_fdb "$pod" vx-client3-eth1  "$leaf3_vx"
  # Collector launcher
  pod=$(pod_for collector) && [[ -n "$pod" ]] && ensure_fdb "$pod" vx-collector-eth1 "$leaf1_vx"
}

fix_client_mtu() {
  local pod="$1"; local container="$2"
  kubectl exec -n "$NAMESPACE" "$pod" -- \
    docker --host unix:///run/docker.sock exec "$container" \
    ip link set dev eth1 mtu 1400 2>/dev/null \
    && echo "  [$pod] eth1 MTU → 1400" \
    || warn "[$pod] MTU clamp failed"
}

# Add iptables DNAT rules in a launcher pod to expose the SR Linux node's SNMP
# (UDP 161) and gNMI (TCP 57400) ports on the launcher pod's eth0.
# Alloy and gnmic reach these ports via the node-telemetry-services.yaml Services.
expose_telemetry_ports() {
  local pod="$1"; local node="$2"
  kubectl exec -n "$NAMESPACE" "$pod" -- sh -c "
    # SR Linux containers attach to the 'clab' Docker network, not the default
    # bridge, so NetworkSettings.IPAddress is empty. Query the clab network directly.
    SRL_IP=\$(docker --host unix:///run/docker.sock inspect ${node} \
      --format '{{(index .NetworkSettings.Networks \"clab\").IPAddress}}' 2>/dev/null)
    if [ -z \"\$SRL_IP\" ]; then echo '  WARN: could not get SR Linux IP for ${node}'; exit 0; fi

    echo 1 > /proc/sys/net/ipv4/ip_forward

    # Use a custom chain to avoid clobbering Docker's own nat rules
    iptables -t nat -N TELEMETRY_DNAT 2>/dev/null || true
    iptables -t nat -F TELEMETRY_DNAT

    # Jump from PREROUTING into our chain (idempotent)
    iptables -t nat -C PREROUTING -j TELEMETRY_DNAT 2>/dev/null || \
      iptables -t nat -A PREROUTING -j TELEMETRY_DNAT

    # SNMP UDP 161
    iptables -t nat -A TELEMETRY_DNAT -p udp --dport 161 -j DNAT --to-destination \${SRL_IP}:161
    # gNMI TCP 57400
    iptables -t nat -A TELEMETRY_DNAT -p tcp --dport 57400 -j DNAT --to-destination \${SRL_IP}:57400

    # Allow forwarding to the SR Linux container
    iptables -C FORWARD -d \"\${SRL_IP}\" -j ACCEPT 2>/dev/null || \
      iptables -A FORWARD -d \"\${SRL_IP}\" -j ACCEPT

    echo \"  [${node}] SNMP+gNMI → \${SRL_IP} via DNAT\"
  " 2>&1 | grep -v '^$' || warn "[$node] telemetry port setup failed"
}

# ─── Main ─────────────────────────────────────────────────────────────────────

info "Applying networking fixes to namespace: $NAMESPACE"

for node in spine1 spine2 leaf1 leaf2 leaf3 client1 client2 client3 collector; do
  pod=$(pod_for "$node") || { warn "Pod not found for $node — skipping"; continue; }
  [[ -z "$pod" ]] && { warn "Pod not found for $node — skipping"; continue; }
  echo "  $node → $pod"
  fix_launcher "$pod"
done

ensure_all_fdbs

info "Clamping client MTU to 1400..."
for node in client1 client2 client3; do
  pod=$(pod_for "$node") || continue
  [[ -z "$pod" ]] && continue
  fix_client_mtu "$pod" "$node"
done

info "Setting up SNMP + gNMI port forwarding in SR Linux launcher pods..."
for node in spine1 spine2 leaf1 leaf2 leaf3; do
  pod=$(pod_for "$node") || continue
  [[ -z "$pod" ]] && continue
  expose_telemetry_ports "$pod" "$node"
done

# Configure SNMP v2c, sFlow, and gNMI on each SR Linux node via sr_cli.
# SR Linux's startup config mechanism is unreliable in Clabbernetes because
# the default running config already has a community entry with 'public', which
# causes a uniqueness conflict when the startup config tries to add ce1=public.
# Applying live via stdin pipe to sr_cli -e is idempotent and reliable.
configure_srl_telemetry() {
  local pod="$1"; local node="$2"; local system_ip="$3"
  docker_exec="docker --host unix:///run/docker.sock exec -i $node"

  printf '%s\n' \
    "set / system snmp network-instance mgmt admin-state enable" \
    "set / system snmp network-instance default admin-state enable" \
    "set / system snmp access-group ag1 admin-state enable" \
    "set / system snmp access-group ag1 security-level no-auth-no-priv" \
    "set / system sflow admin-state enable" \
    "set / system sflow sample-rate 10000" \
    "set / system sflow collector 1 collector-address 10.0.3.2" \
    "set / system sflow collector 1 network-instance default" \
    "set / system sflow collector 1 source-address ${system_ip}" \
    "set / system sflow collector 1 port 6343" \
    "commit now" | \
  kubectl exec -i -n "$NAMESPACE" "$pod" -- $docker_exec sr_cli -e 2>&1 | \
  grep -v '^$' | sed "s/^/  [$node] /" || warn "[$node] telemetry config failed"

  # Add the community entry separately (idempotent — startup config may have already
  # configured a community 'public', so we tolerate AlreadyExists and continue).
  printf '%s\n' \
    "set / system snmp access-group ag1 community-entry ce1 community public" \
    "commit now" | \
  kubectl exec -i -n "$NAMESPACE" "$pod" -- $docker_exec sr_cli -e 2>&1 | \
  grep -vE '^$|AlreadyExists|community that is not unique' | \
  sed "s/^/  [$node] /" || true
}

info "Configuring SNMP, sFlow, and gNMI on SR Linux nodes..."
declare -A SRL_SYSTEM_IPS=(
  [spine1]=10.0.2.1 [spine2]=10.0.2.2
  [leaf1]=10.0.1.1  [leaf2]=10.0.1.2  [leaf3]=10.0.1.3
)
for node in spine1 spine2 leaf1 leaf2 leaf3; do
  pod=$(pod_for "$node") || continue
  [[ -z "$pod" ]] && continue
  configure_srl_telemetry "$pod" "$node" "${SRL_SYSTEM_IPS[$node]}"
done

info "Waiting 45s for BGP to converge..."
sleep 45

info "BGP summary on leaf1:"
leaf1_pod=$(pod_for leaf1)
kubectl exec -n "$NAMESPACE" "$leaf1_pod" -- \
  docker --host unix:///run/docker.sock exec leaf1 \
  sr_cli "show network-instance default protocols bgp neighbor | grep -E 'State|established'" \
  2>/dev/null || warn "Could not reach leaf1 SR Linux"

info "Done."
info "Next steps:"
info "  1. kubectl apply -f k8s/network-reconciler.yaml"
info "  2. bash scripts/deploy-telemetry.sh"
info "  3. bash scripts/traffic.sh start"
