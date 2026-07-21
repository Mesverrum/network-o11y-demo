# Makefile — local WSL / ContainerLab / Docker lab
#
# Collector pattern follows Mesverrum/KtransToGrafana golden path:
#   groups/*.env → make generate → compose-groups.generated.yaml
#   make discover GROUP=srl populates state/devices-srl.yaml
#
# Quick start:
#   cp .env.example .env && cp groups/srl.env.sample groups/srl.env
#   sudo chown -R 1000:1000 config state
#   make generate && make up && make traffic

SHELL := /bin/bash
.DEFAULT_GOAL := help

ROOT := $(dir $(abspath $(lastword $(MAKEFILE_LIST))))
export CLAB_NETWORK ?= clab

# Prefer explicit KTRANS_HOST in .env; else hostname (same as KtransToGrafana).
KTRANS_HOST := $(shell $(ROOT)scripts/host-id.sh 2>/dev/null)
export KTRANS_HOST

COMPOSE := docker compose --env-file .env \
  -f compose-base.yaml \
  -f compose-groups.generated.yaml \
  -f compose-limits.generated.yaml

.PHONY: help
help: ## Show this help
	@echo ""
	@echo "Local network-o11y lab (WSL + ContainerLab + KtransToGrafana golden path)"
	@echo "========================================================================="
	@echo ""
	@grep -E '^[a-zA-Z0-9_-]+:.*?## ' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  %-22s %s\n", $$1, $$2}'
	@echo ""

.PHONY: check
check: ## Verify docker, containerlab, .env, groups/srl.env
	@command -v docker >/dev/null || (echo "ERROR: docker not found"; exit 1)
	@command -v containerlab >/dev/null || command -v clab >/dev/null \
	  || (echo "ERROR: containerlab not found — https://containerlab.dev"; exit 1)
	@docker compose version >/dev/null || (echo "ERROR: docker compose not found"; exit 1)
	@command -v envsubst >/dev/null || (echo "ERROR: envsubst missing — sudo apt install gettext-base"; exit 1)
	@command -v yq >/dev/null || (echo "ERROR: yq missing — sudo apt install yq"; exit 1)
	@test -f $(ROOT).env || (echo "ERROR: missing .env — cp .env.example .env"; exit 1)
	@grep -qE 'glc_REPLACE_ME|YOUR-REGION|GC_OTLP_KEY=glc_foo$$' $(ROOT).env 2>/dev/null \
	  && echo "WARNING: .env still has placeholder Grafana Cloud values" || true
	@test -f $(ROOT)groups/srl.env || (echo "ERROR: missing groups/srl.env — cp groups/srl.env.sample groups/srl.env"; exit 1)
	@echo "OK: prerequisites look good (deployment.host=$(KTRANS_HOST))"

.PHONY: preflight
preflight: ## KtransToGrafana-style readiness checks
	@cd $(ROOT) && ./scripts/preflight.sh

.PHONY: generate
generate: ## Render poller/discovery configs + compose-groups.generated.yaml
	@cd $(ROOT) && ./scripts/generate-groups.sh

.PHONY: bootstrap
bootstrap: ## Seed empty state/devices-<group>.yaml stubs
	@mkdir -p $(ROOT)state $(ROOT)config
	@for envfile in $(ROOT)groups/*.env; do \
	  [ -f "$$envfile" ] || continue; \
	  group=$$(awk -F= '/^GROUP=/{print $$2; exit}' "$$envfile"); \
	  [ -z "$$group" ] && continue; \
	  if [ ! -f "$(ROOT)state/devices-$$group.yaml" ]; then \
	    echo '{}' > "$(ROOT)state/devices-$$group.yaml"; \
	    echo "seeded empty state/devices-$$group.yaml"; \
	  fi; \
	done

.PHONY: limits
limits: ## Compute per-container memory limits from host RAM
	@cd $(ROOT) && ./scripts/compute-limits.sh

.PHONY: limits-show
limits-show: ## Preview memory limits without writing
	@cd $(ROOT) && ./scripts/compute-limits.sh --dry-run

.PHONY: host
host: ## Print deployment.host (KTRANS_HOST)
	@echo "$(KTRANS_HOST)"

.PHONY: discover
discover: ## Run one-shot SNMP discovery (GROUP=srl)
	@test -n "$(GROUP)" || { echo "ERROR: pass GROUP=<name>, e.g. make discover GROUP=srl" >&2; exit 1; }
	@cd $(ROOT) && ./scripts/run-discovery.sh $(GROUP)

.PHONY: up
up: check generate bootstrap limits ## Deploy fabric + telemetry + discover SRL + softflowd + syslog
	@echo "==> Deploying ContainerLab topology..."
	cd $(ROOT) && (command -v containerlab >/dev/null && containerlab deploy -t topology.clab.yml \
	  || clab deploy -t topology.clab.yml)
	@echo "==> Waiting for SR Linux nodes to settle (60s)..."
	@sleep 60
	@echo "==> Applying fabric config (postdeploy workaround for /mnt/c)..."
	@bash $(ROOT)scripts/apply-fabric-config.sh
	@echo "==> deployment.host = $(KTRANS_HOST)"
	@echo "==> Starting telemetry compose stack..."
	cd $(ROOT) && $(COMPOSE) up -d
	@echo "==> Syncing NetBox Cloud inventory..."
	@if grep -q '^DISCOVERY_SOURCE=netbox' "$(ROOT)groups/srl.env" 2>/dev/null; then \
	  bash $(ROOT)scripts/netbox-bootstrap.sh; \
	else \
	  bash $(ROOT)scripts/update-snmp-targets.sh; \
	fi
	@echo "==> Discovering SRL devices (GROUP=srl)..."
	cd $(ROOT) && ./scripts/run-discovery.sh srl || echo "WARNING: discovery failed — check snmpwalk / groups/srl.env"
	@echo "==> Updating topology-exporter targets..."
	bash $(ROOT)scripts/update-topology-targets.sh
	@echo "==> Starting softflowd on clients..."
	bash $(ROOT)scripts/softflowd.sh
	@echo "==> Configuring SR Linux syslog → ktranslate_syslog..."
	bash $(ROOT)scripts/syslog-config.sh || echo "WARNING: syslog config failed — check sr_cli syntax"
	@echo "==> Configuring SR Linux SNMP traps → ktranslate_snmp_srl..."
	bash $(ROOT)scripts/snmp-trap-config.sh || echo "WARNING: snmp trap config failed — check sr_cli syntax"
	@echo ""
	@echo "Lab is up. Next: make status && make traffic && make emit-events"
	@echo "Grafana: count by (device_name, service_name) (kentik_snmp_DeviceMetrics)"

.PHONY: fabric-apply
fabric-apply: ## Apply configs/fabric/*.cfg via sr_cli (WSL /mnt/c postdeploy workaround)
	bash $(ROOT)scripts/apply-fabric-config.sh

.PHONY: stabilize
stabilize: ## Recover lab without clab --reconfigure (start SRL, apply config, discover)
	bash $(ROOT)scripts/stabilize-lab.sh

.PHONY: down
down: ## Destroy fabric + stop compose
	@echo "==> Stopping compose..."
	cd $(ROOT) && $(COMPOSE) down || true
	@echo "==> Destroying ContainerLab topology..."
	cd $(ROOT) && (command -v containerlab >/dev/null && containerlab destroy -t topology.clab.yml --cleanup \
	  || clab destroy -t topology.clab.yml --cleanup) || true

.PHONY: status
status: ## Show clab nodes, compose, and a quick ping check
	@echo "── ContainerLab ──"
	@cd $(ROOT) && (containerlab inspect -t topology.clab.yml 2>/dev/null \
	  || clab inspect -t topology.clab.yml 2>/dev/null || docker ps --filter label=clab-node-name)
	@echo ""
	@echo "── Compose ──"
	@cd $(ROOT) && $(COMPOSE) ps
	@echo ""
	@echo "── Client ping (client2 → client1) ──"
	@docker exec client2 ping -c 2 -W 2 172.17.0.1 2>/dev/null || echo "(clients not ready)"

.PHONY: snmp-targets
snmp-targets: ## Rewrite groups/srl.env TARGETS from live clab mgmt IPs + regenerate
	bash $(ROOT)scripts/update-snmp-targets.sh

.PHONY: topology-exporter-image
topology-exporter-image: ## Download release binary and build local topology-exporter image
	@mkdir -p $(ROOT)topology-exporter/build
	@test -f $(ROOT)topology-exporter/build/topology-exporter-linux-amd64 \
	  || curl -fsSL -o $(ROOT)topology-exporter/build/topology-exporter-linux-amd64 \
	       https://github.com/grafana/network-topology-exporter/releases/download/v1.0.0/topology-exporter-linux-amd64
	@chmod +x $(ROOT)topology-exporter/build/topology-exporter-linux-amd64
	cd $(ROOT)topology-exporter && docker build -t srl-local/network-topology-exporter:v1.0.0 .

.PHONY: netbox-bootstrap netbox-sync
netbox-bootstrap netbox-sync: ## Populate NetBox Cloud + sync clab mgmt IPs
	bash $(ROOT)scripts/netbox-bootstrap.sh

.PHONY: netbox-sync-mgmt
netbox-sync-mgmt: ## Refresh NetBox primary_ip4 from live clab mgmt IPs
	@set -a && . $(ROOT).env && set +a && python3 $(ROOT)scripts/update-netbox-mgmt-ips.py

.PHONY: netbox-populate
netbox-populate: ## Seed NetBox with local lab topology (idempotent)
	@set -a && . $(ROOT).env && set +a && python3 $(ROOT)scripts/netbox-populate.py

.PHONY: topology-targets
topology-targets: ## Rewrite topology-exporter target hosts from live clab mgmt IPs
	bash $(ROOT)scripts/update-topology-targets.sh

.PHONY: softflowd
softflowd: ## (Re)start softflowd on clients
	bash $(ROOT)scripts/softflowd.sh

.PHONY: syslog
syslog: ## (Re)apply syslog remote-server on SR Linux nodes
	bash $(ROOT)scripts/syslog-config.sh

.PHONY: snmp-traps-config
snmp-traps-config: ## (Re)apply SNMP trap-group → ktranslate_snmp_srl
	bash $(ROOT)scripts/snmp-trap-config.sh

.PHONY: emit-events
emit-events: ## Flap links to emit real SRL traps + syslog (configures destinations first)
	bash $(ROOT)scripts/emit-events.sh

.PHONY: events-loop
events-loop: ## Background: synthetic traps every 3m + emit-events every 5m
	bash $(ROOT)scripts/events-loop.sh start

.PHONY: events-stop
events-stop: ## Stop background events-loop
	bash $(ROOT)scripts/events-loop.sh stop

.PHONY: events-status
events-status: ## Show events-loop status / recent log
	bash $(ROOT)scripts/events-loop.sh status

.PHONY: traffic
traffic: ## Start ongoing UDP workloads (steady+burst+reverse+ping)
	bash $(ROOT)scripts/traffic.sh start

.PHONY: traffic-stop
traffic-stop: ## Stop traffic workloads
	bash $(ROOT)scripts/traffic.sh stop

.PHONY: traffic-status
traffic-status: ## Show traffic workload status
	bash $(ROOT)scripts/traffic.sh status

.PHONY: join-app
join-app: ## Build+deploy OTel Clos join demo (client1→client2 EVPN + traces→Alloy)
	bash $(ROOT)scripts/join-app.sh start

.PHONY: join-app-stop
join-app-stop: ## Stop Clos join demo on clients
	bash $(ROOT)scripts/join-app.sh stop

.PHONY: join-app-status
join-app-status: ## Show Clos join demo status
	bash $(ROOT)scripts/join-app.sh status

.PHONY: join-app-build
join-app-build: ## Build join-app binary only
	bash $(ROOT)scripts/join-app.sh build

.PHONY: join-fault
join-fault: ## Inject netem delay/loss on client eth1 (join demo talk track)
	bash $(ROOT)scripts/join-fault.sh start

.PHONY: join-fault-stop
join-fault-stop: ## Clear join-fault netem on clients
	bash $(ROOT)scripts/join-fault.sh stop

.PHONY: join-fault-status
join-fault-status: ## Show tc qdisc on client eth1
	bash $(ROOT)scripts/join-fault.sh status

.PHONY: traps
traps: ## Send SNMPv2c test traps to ktranslate_snmp_srl (:1620)
	bash $(ROOT)scripts/trap-gen.sh suite

.PHONY: traps-burst
traps-burst: ## Send a burst of mixed SNMP traps (default 20)
	bash $(ROOT)scripts/trap-gen.sh burst $${N:-20}

.PHONY: traps-loop
traps-loop: ## Foreground trap suite loop (default every 180s; prefer events-loop)
	bash $(ROOT)scripts/trap-gen.sh loop

.PHONY: logs
logs: ## Tail compose logs
	cd $(ROOT) && $(COMPOSE) logs -f --tail=100
