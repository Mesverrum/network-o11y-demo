#!/bin/bash
# cloud-init: install docker and kick a oneshot that builds the Kafka plugin fork.
set -euxo pipefail
exec > >(tee -a /var/log/kafka-plugin-lab-userdata.log) 2>&1

dnf install -y docker git jq python3 tar xz
systemctl enable --now docker
usermod -aG docker ec2-user || true

# Amazon Linux 2023 has no docker-compose-plugin RPM.
mkdir -p /usr/local/lib/docker/cli-plugins
curl -fsSL -o /usr/local/lib/docker/cli-plugins/docker-compose \
  https://github.com/docker/compose/releases/download/v2.32.4/docker-compose-linux-x86_64
chmod +x /usr/local/lib/docker/cli-plugins/docker-compose
ln -sfn /usr/local/lib/docker/cli-plugins/docker-compose /usr/local/bin/docker-compose
docker compose version

mkdir -p /opt/kafka-plugin-lab /var/lib/kafka-plugin-lab
echo "starting" > /var/lib/kafka-plugin-lab/status

cat >/opt/kafka-plugin-lab/bootstrap.sh <<BOOT
#!/bin/bash
set -euxo pipefail
exec > >(tee -a /var/log/kafka-plugin-lab-bootstrap.log) 2>&1
echo "bootstrapping" > /var/lib/kafka-plugin-lab/status

PLUGIN_REPO="${plugin_repo}"
PLUGIN_BRANCH="${plugin_branch}"
DST=/opt/kafka-ds
export PATH=/usr/local/go/bin:/usr/local/node/bin:/root/go/bin:\$PATH
export HOME=/root
export GOPATH=/root/go
export GOMODCACHE=/root/go/pkg/mod
mkdir -p "\$GOPATH"

if [[ ! -x /usr/local/go/bin/go ]]; then
  curl -fsSL https://go.dev/dl/go1.26.8.linux-amd64.tar.gz -o /tmp/go.tgz
  rm -rf /usr/local/go
  tar -C /usr/local -xzf /tmp/go.tgz
fi

if [[ ! -x /usr/local/node/bin/node ]]; then
  curl -fsSL https://nodejs.org/dist/v22.20.0/node-v22.20.0-linux-x64.tar.xz -o /tmp/node.txz
  mkdir -p /usr/local/node
  tar -C /usr/local/node --strip-components=1 -xJf /tmp/node.txz
fi

corepack enable
corepack prepare pnpm@11.13.1 --activate
go install github.com/magefile/mage@v1.15.0

if [[ -d "\$DST/.git" ]]; then
  git -C "\$DST" fetch origin
  git -C "\$DST" checkout "\$PLUGIN_BRANCH"
  git -C "\$DST" pull --ff-only origin "\$PLUGIN_BRANCH"
else
  git clone --branch "\$PLUGIN_BRANCH" "\$PLUGIN_REPO" "\$DST"
fi

cd "\$DST"
pnpm install --frozen-lockfile
pnpm run test:ci
pnpm run typecheck
pnpm run build
mage -v testRace
mage -v build:linux

docker compose up -d --build
# dist/ is bind-mounted; restart so Grafana picks up the binary from this boot.
docker compose restart grafana

cd /opt/kafka-ds/example/go
go build -o /usr/local/bin/kafka-json-producer .

cat >/etc/systemd/system/kafka-json-producer.service <<'UNIT'
[Unit]
Description=Kafka JSON sample producer
After=docker.service
[Service]
Environment=HOME=/root
Environment=GOPATH=/root/go
Environment=GOMODCACHE=/root/go/pkg/mod
ExecStart=/usr/local/bin/kafka-json-producer -broker 127.0.0.1:9094 -topic sensor-json -interval 1000 -shape flat -format json
Restart=always
RestartSec=5
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload

for i in \$(seq 1 90); do
  if curl -fsS http://127.0.0.1:3000/api/health >/dev/null; then
    break
  fi
  sleep 5
done
curl -fsS http://127.0.0.1:3000/api/health

systemctl enable --now kafka-json-producer.service

python3 /opt/kafka-plugin-lab/validate.py
echo "ready" > /var/lib/kafka-plugin-lab/status
BOOT
chmod +x /opt/kafka-plugin-lab/bootstrap.sh

cat >/opt/kafka-plugin-lab/validate.py <<'PY'
#!/usr/bin/env python3
"""Hit Grafana on localhost: prove unsigned plugin, QueryData snapshot, and alert eval."""
import json
import sys
import time
import urllib.error
import urllib.request

BASE = "http://127.0.0.1:3000"


def req(method, path, body=None):
    data = None if body is None else json.dumps(body).encode()
    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    r = urllib.request.Request(BASE + path, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(r, timeout=60) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw.decode() or "{}")
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        raise SystemExit(f"{method} {path} -> {e.code} {raw}") from e


def main():
    _, health = req("GET", "/api/health")
    print("grafana health", health)

    _, plugins = req("GET", "/api/plugins")
    kafka = [p for p in plugins if p.get("id") == "hamedkarbasi93-kafka-datasource"]
    if not kafka:
        sys.exit("plugin not loaded")
    print("plugin loaded", kafka[0].get("name"), kafka[0].get("info", {}).get("version"))

    _, ds_list = req("GET", "/api/datasources")
    ds = next((d for d in ds_list if d.get("type") == "hamedkarbasi93-kafka-datasource"), None)
    if not ds:
        sys.exit("kafka datasource not provisioned")
    uid = ds["uid"]
    print("datasource uid", uid)

    time.sleep(8)

    query = {
        "queries": [
            {
                "refId": "A",
                "datasource": {"type": "hamedkarbasi93-kafka-datasource", "uid": uid},
                "topicName": "sensor-json",
                "partition": "all",
                "autoOffsetReset": "latest",
                "messageFormat": "json",
                "timestampMode": "message",
                "selectedField": "value1",
            }
        ],
        "from": "now-5m",
        "to": "now",
    }
    _, qres = req("POST", "/api/ds/query?ds_type=hamedkarbasi93-kafka-datasource", query)
    results = qres.get("results", {})
    a = results.get("A") or results.get("a")
    if not a:
        sys.exit(f"no QueryData result A: {json.dumps(qres)[:2000]}")
    if a.get("error"):
        sys.exit(f"QueryData error: {a['error']}")
    frames = a.get("frames") or []
    if not frames:
        sys.exit(f"QueryData returned no frames: {json.dumps(a)[:2000]}")
    print("snapshot frames", len(frames))
    open("/var/lib/kafka-plugin-lab/query-ok", "w").write("ok\n")

    _, folder = req("POST", "/api/folders", {"title": "kafka-plugin-lab"})
    folder_uid = folder.get("uid")
    print("folder", folder_uid)

    rule = {
        "orgID": 1,
        "folderUID": folder_uid,
        "ruleGroup": "kafka-plugin-lab",
        "title": "sensor-json value1 last > 0",
        "condition": "C",
        "noDataState": "NoData",
        "execErrState": "Error",
        "for": "0s",
        "data": [
            {
                "refId": "A",
                "relativeTimeRange": {"from": 600, "to": 0},
                "datasourceUid": uid,
                "model": {
                    "refId": "A",
                    "topicName": "sensor-json",
                    "partition": "all",
                    "autoOffsetReset": "latest",
                    "messageFormat": "json",
                    "timestampMode": "message",
                    "selectedField": "value1",
                    "datasource": {"type": "hamedkarbasi93-kafka-datasource", "uid": uid},
                },
            },
            {
                "refId": "B",
                "datasourceUid": "__expr__",
                "model": {
                    "type": "reduce",
                    "expression": "A",
                    "reducer": "last",
                    "refId": "B",
                    "datasource": {"type": "__expr__", "uid": "__expr__"},
                },
            },
            {
                "refId": "C",
                "datasourceUid": "__expr__",
                "model": {
                    "type": "threshold",
                    "expression": "B",
                    "refId": "C",
                    "conditions": [
                        {
                            "evaluator": {"type": "gt", "params": [0]},
                            "operator": {"type": "and"},
                            "query": {"params": ["C"]},
                            "reducer": {"type": "last", "params": []},
                            "type": "query",
                        }
                    ],
                    "datasource": {"type": "__expr__", "uid": "__expr__"},
                },
            },
        ],
    }
    _, created = req("POST", "/api/v1/provisioning/alert-rules", rule)
    print("alert rule uid", created.get("uid"))
    open("/var/lib/kafka-plugin-lab/alert-uid", "w").write(str(created.get("uid") or ""))

    deadline = time.time() + 180
    last = None
    while time.time() < deadline:
        _, groups = req("GET", "/api/prometheus/grafana/api/v1/rules")
        last = groups
        for g in groups.get("data", {}).get("groups", []):
            for rule_st in g.get("rules", []):
                if rule_st.get("name") == "sensor-json value1 last > 0":
                    state = rule_st.get("state")
                    health = rule_st.get("health")
                    print("alert state", state, "health", health, "lastError", rule_st.get("lastError"))
                    if health in ("error", "Error") or (rule_st.get("lastError") or "").strip():
                        continue
                    if state in ("firing", "pending", "inactive"):
                        open("/var/lib/kafka-plugin-lab/alert-state", "w").write(f"{state} {health}")
                        if state == "inactive" and health == "ok":
                            # Wait for a firing eval when the threshold is last > 0.
                            continue
                        if state in ("firing", "pending") and health == "ok":
                            return
                        if health == "ok" and time.time() > deadline - 20:
                            return
        time.sleep(10)
    sys.exit(f"alert never evaluated: {json.dumps(last)[:3000] if last else 'no rules'}")


if __name__ == "__main__":
    main()
PY
chmod +x /opt/kafka-plugin-lab/validate.py

cat >/etc/systemd/system/kafka-plugin-lab-bootstrap.service <<'UNIT'
[Unit]
Description=Build Kafka Grafana plugin lab and start compose
Wants=network-online.target docker.service
After=network-online.target docker.service
[Service]
Type=oneshot
TimeoutStartSec=0
ExecStart=/opt/kafka-plugin-lab/bootstrap.sh
RemainAfterExit=yes
[Install]
WantedBy=multi-user.target
UNIT

systemctl daemon-reload
systemctl enable --now kafka-plugin-lab-bootstrap.service
