#!/usr/bin/env bash
# Compile Alloy (discovery.snmp + otelcol receivers) with snmp-sd as a Go
# module, then overlay the binary + library onto grafana/alloy:latest.
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
[[ -d internal/component/otelcol/receiver/snmptrap ]] || { echo "missing otelcol.receiver.snmptrap"; exit 1; }
[[ -d internal/component/otelcol/receiver/syslog ]] || { echo "missing otelcol.receiver.syslog"; exit 1; }
grep -q 'github.com/Mesverrum/snmp-sd' go.mod || { echo "go.mod missing github.com/Mesverrum/snmp-sd"; exit 1; }

mkdir -p build
export CGO_ENABLED=0
GO_BIN="$(command -v go || true)"
GO_VER=""
if [[ -n "${GO_BIN}" ]]; then
  GO_VER="$("${GO_BIN}" env GOVERSION 2>/dev/null || true)"
fi

build_in_docker() {
  echo "==> go 1.26 docker build (host ${GO_VER:-none} is too old or missing)"
  docker run --rm \
    -v "${ALLOY_SRC}:/src" \
    -v "${HOME}/.cache/alloy-gomod:/go/pkg/mod" \
    -v "${HOME}/.cache/alloy-gobuild:/root/.cache/go-build" \
    -w /src \
    -e CGO_ENABLED=0 \
    -e GOPROXY="${GOPROXY:-https://proxy.golang.org,direct}" \
    golang:1.26.6 \
    bash -c '
      set -euo pipefail
      ( cd collector && go build -tags netgo -o ../build/alloy . )
      go build -o build/snmp-discovery github.com/Mesverrum/snmp-sd/cmd/snmp-discovery
      SNMPSD="$(go list -m -f "{{.Dir}}" github.com/Mesverrum/snmp-sd)"
      rm -rf build/snmp-lib
      mkdir -p build/snmp-lib
      cp -a "${SNMPSD}/snmp/." build/snmp-lib/
    '
}

if [[ "${GO_VER}" == go1.26* ]]; then
  echo "==> go build alloy (collector, tags=netgo) with ${GO_VER}"
  ( cd collector && go build -tags 'netgo' -o ../build/alloy . )
  echo "==> go build snmp-discovery from Mesverrum/snmp-sd"
  go build -o build/snmp-discovery github.com/Mesverrum/snmp-sd/cmd/snmp-discovery
  SNMPSD="$(go list -m -f '{{.Dir}}' github.com/Mesverrum/snmp-sd)"
  rm -rf build/snmp-lib
  mkdir -p build/snmp-lib
  cp -a "${SNMPSD}/snmp/." build/snmp-lib/
else
  build_in_docker
fi

[[ -f build/alloy ]]
[[ -f build/snmp-discovery ]]
[[ -f build/snmp-lib/snmp-network.yml ]]
[[ -f build/snmp-lib/fingerprinters.yml ]]

cat >"$WORKDIR/Dockerfile" <<'EOF'
FROM grafana/alloy:latest
COPY alloy /bin/alloy
COPY snmp-discovery /usr/bin/snmp-discovery
COPY snmp-lib/ /etc/alloy/
EOF

cp -f build/alloy build/snmp-discovery "$WORKDIR/"
cp -a build/snmp-lib "$WORKDIR/snmp-lib"

echo "==> docker build $TAG"
docker build -t "$TAG" "$WORKDIR"
docker image inspect "$TAG" --format 'ok {{.Id}} {{.Created}}'
echo "==> strings check discovery.snmp + otelcol.receiver.syslog + snmp-sd"
docker run --rm --entrypoint /bin/sh "$TAG" -c \
  'grep -a -E "discovery.snmp|otelcol.receiver.syslog|otelcol.receiver.snmptrap|Mesverrum/snmp-sd" /bin/alloy | head -c 500; echo; ls /etc/alloy/snmp-network.yml /usr/bin/snmp-discovery'
