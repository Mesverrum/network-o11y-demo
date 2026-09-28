#!/usr/bin/env bash
# Compile Alloy (discovery.snmp + otelcol receivers) with snmp-sd as a Go
# module, then overlay the binary + library onto grafana/alloy:latest.
set -euo pipefail
ALLOY_SRC="${ALLOY_SRC:-/mnt/c/Users/mesve/projects/alloy}"
SNMPSD_SRC="${SNMPSD_SRC:-$(cd "${ALLOY_SRC}/../snmp-sd" 2>/dev/null && pwd || echo /mnt/c/Users/mesve/projects/snmp-sd)}"
TAG="${ALLOY_NETWORK_TAG:-srl-local/alloy:network-dev}"
WORKDIR="/tmp/alloy-network-bin-$$"
mkdir -p "$WORKDIR"
MOD_DIRTY=0
cleanup() {
  if [[ "${MOD_DIRTY}" == 1 ]]; then
    git checkout -- go.mod go.sum collector/go.mod collector/go.sum || true
  fi
  chmod -R u+w "$WORKDIR" 2>/dev/null || true
  rm -rf "$WORKDIR" || true
}
trap cleanup EXIT

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
  echo "==> snmp-sd=${SNMPSD_SRC}"
  [[ -f "${SNMPSD_SRC}/go.mod" ]] || { echo "missing snmp-sd at ${SNMPSD_SRC}"; exit 1; }
  docker run --rm \
    -v "${ALLOY_SRC}:/src" \
    -v "${SNMPSD_SRC}:/snmp-sd" \
    -v "${HOME}/.cache/alloy-gomod:/go/pkg/mod" \
    -v "${HOME}/.cache/alloy-gobuild:/root/.cache/go-build" \
    -w /src \
    -e CGO_ENABLED=0 \
    -e GOPROXY="${GOPROXY:-https://proxy.golang.org,direct}" \
    golang:1.26.6 \
    bash -c '
      set -euo pipefail
      git config --global --add safe.directory /src
      go mod edit -replace github.com/Mesverrum/snmp-sd=/snmp-sd
      ( cd collector && go mod edit -replace github.com/Mesverrum/snmp-sd=/snmp-sd )
      ( cd collector && go build -tags netgo -o ../build/alloy . )
      go build -o build/snmp-discovery github.com/Mesverrum/snmp-sd/cmd/snmp-discovery
      if [[ -d build/snmp-lib ]]; then
        chmod -R u+w build/snmp-lib 2>/dev/null || true
        rm -rf build/snmp-lib
      fi
      mkdir -p build/snmp-lib
      cp -a /snmp-sd/snmp/. build/snmp-lib/
      git checkout -- go.mod go.sum collector/go.mod collector/go.sum
    '
}

if [[ "${GO_VER}" == go1.26* ]]; then
  echo "==> go build alloy (collector, tags=netgo) with ${GO_VER}"
  echo "==> replace snmp-sd with ${SNMPSD_SRC}"
  [[ -f "${SNMPSD_SRC}/go.mod" ]] || { echo "missing snmp-sd at ${SNMPSD_SRC}"; exit 1; }
  go mod edit -replace "github.com/Mesverrum/snmp-sd=${SNMPSD_SRC}"
  ( cd collector && go mod edit -replace "github.com/Mesverrum/snmp-sd=${SNMPSD_SRC}" )
  MOD_DIRTY=1
  ( cd collector && go build -tags 'netgo' -o ../build/alloy . )
  echo "==> go build snmp-discovery from local snmp-sd"
  go build -o build/snmp-discovery github.com/Mesverrum/snmp-sd/cmd/snmp-discovery
  # A previous Docker build can leave this tree root-owned.
  if [[ -d build/snmp-lib ]] && ! chmod -R u+w build/snmp-lib 2>/dev/null; then
    docker run --rm -v "${PWD}/build:/build" alpine chmod -R a+w /build/snmp-lib
  fi
  rm -rf build/snmp-lib
  mkdir -p build/snmp-lib
  cp -a "${SNMPSD_SRC}/snmp/." build/snmp-lib/
  git checkout -- go.mod go.sum collector/go.mod collector/go.sum
  MOD_DIRTY=0
else
  build_in_docke
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
docker run --rm --entrypoint /bin/sh "$TAG" -c '
  for s in discovery.snmp discovery_snmp_group_info otelcol.receiver.syslog otelcol.receiver.snmptrap Mesverrum/snmp-sd; do
    n=$(grep -a -o -F "$s" /bin/alloy | wc -l)
    echo "$s $n"
    test "$n" -gt 0
  done
  ls /etc/alloy/snmp-network.yml /etc/alloy/fingerprinters.yml /usr/bin/snmp-discovery
'
