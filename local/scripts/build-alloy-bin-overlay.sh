#!/usr/bin/env bash
# Fast path: compile Alloy on /mnt/c (module cache warm), overlay onto grafana/alloy:latest.
set -euo pipefail
ALLOY_SRC="${ALLOY_SRC:-/mnt/c/Users/mesve/projects/alloy}"
TAG="${ALLOY_NETWORK_TAG:-srl-local/alloy:network-dev}"
WORKDIR="/tmp/alloy-network-bin-$$"
mkdir -p "$WORKDIR"
trap 'rm -rf "$WORKDIR"' EXIT

cd "$ALLOY_SRC"
echo "==> pwd=$(pwd)"
[[ -f internal/build/build.go ]] || { echo "missing internal/build"; exit 1; }
[[ -d internal/component/discovery/snmp ]] || { echo "missing discovery.snmp"; exit 1; }
[[ -d internal/component/loki/source/snmptrap ]] || { echo "missing loki.source.snmptrap"; exit 1; }
[[ -d internal/snmpdiscovery ]] || { echo "missing snmpdiscovery"; exit 1; }

mkdir -p build
export CGO_ENABLED=0
echo "==> go build alloy (collector, tags=netgo)"
( cd collector && go build -tags 'netgo' -o ../build/alloy . )
echo "==> go build snmp-discovery"
go build -o build/snmp-discovery ./cmd/snmp-discovery

[[ -f snmp/snmp-network.yml ]]
[[ -f snmp/fingerprinters.yml ]]

cat >"$WORKDIR/Dockerfile" <<'EOF'
FROM grafana/alloy:latest
COPY alloy /bin/alloy
COPY snmp-discovery /usr/bin/snmp-discovery
COPY snmp-network.yml /etc/alloy/snmp-network.yml
COPY fingerprinters.yml /etc/alloy/fingerprinters.yml
COPY auths.yml /etc/alloy/auths.yml
COPY NOTICE /etc/alloy/NOTICE.snmp-profiles
EOF

cp -f build/alloy build/snmp-discovery snmp/snmp-network.yml snmp/fingerprinters.yml snmp/auths.yml snmp/NOTICE "$WORKDIR/"
mv "$WORKDIR/NOTICE" "$WORKDIR/NOTICE" 2>/dev/null || true
cp -f snmp/NOTICE "$WORKDIR/NOTICE"

echo "==> docker build $TAG"
docker build -t "$TAG" "$WORKDIR"
docker image inspect "$TAG" --format 'ok {{.Id}} {{.Created}}'
echo "==> strings check discovery.snmp + loki.source.snmptrap"
docker run --rm --entrypoint /bin/sh "$TAG" -c 'grep -a -E "discovery.snmp|loki.source.snmptrap" /bin/alloy | head -c 400; echo'
