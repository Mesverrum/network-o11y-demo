# Makefile — local Docker + ContainerLab lab (macOS or WSL/Linux)
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
KTRANS_HOST := $(shell bash $(ROOT)scripts/host-id.sh 2>/dev/null)
export KTRANS_HOST

# Staggered bring-up (fabric + collectors) reduces simultaneous load on WSL laptops.
LAB_STAGGER ?= 1
LAB_STAGGER_SECS ?= 25
LAB_AUTO_TRAFFIC ?= 1
LAB_AUTO_INTERNET_PROBES ?= 1
LAB_AUTO_EVENTS ?= 1
export LAB_STAGGER LAB_STAGGER_SECS LAB_AUTO_TRAFFIC LAB_AUTO_INTERNET_PROBES LAB_AUTO_EVENTS

# Audit logging: local/state/lab-actions.log (+ docker-events.log). See make lab-log-status.
LAB_RUN := bash $(ROOT)scripts/lab-run.sh
LAB_LOG_EVENTS ?= 1
export LAB_LOG_EVENTS

COMPOSE := docker compose --env-file .env --env-file compose-host.generated.env \
  $(shell bash $(ROOT)scripts/lab-topology-exporter.sh profile 2>/dev/null) \
  -f compose-base.yaml \
  -f compose-groups.generated.yaml \
  -f compose-catalog.generated.yaml \
  -f compose-limits.generated.yaml

.PHONY: help
help: ## Show this help
	@echo ""
	@echo "Local network-o11y lab (Docker + ContainerLab + KtransToGrafana golden path)"
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
	@cd $(ROOT) && bash scripts/preflight.sh

.PHONY: generate
generate: ## Render poller/discovery configs + compose-groups.generated.yaml
	@cd $(ROOT) && bash scripts/generate-groups.sh

.PHONY: bootstrap
bootstrap: ## Seed empty state/devices-<group>.yaml stubs + flow_dns config stubs
	@mkdir -p $(ROOT)state $(ROOT)config $(ROOT)dnsmasq
	@for envfile in $(ROOT)groups/*.env; do \
	  [ -f "$$envfile" ] || continue; \
	  group=$$(awk -F= '/^GROUP=/{print $$2; exit}' "$$envfile"); \
	  [ -z "$$group" ] && continue; \
	  if [ ! -f "$(ROOT)state/devices-$$group.yaml" ]; then \
	    echo '{}' > "$(ROOT)state/devices-$$group.yaml"; \
	    echo "seeded empty state/devices-$$group.yaml"; \
	  fi; \
	done
	@[ -f $(ROOT)dnsmasq/hosts.generated.conf ] || echo '# pending refresh-flow-dns' > $(ROOT)dnsmasq/hosts.generated.conf
	@[ -f $(ROOT)dnsmasq/upstream.conf ] || echo 'server=host.docker.internal' > $(ROOT)dnsmasq/upstream.conf

.PHONY: limits
limits: ## Compute per-container memory limits from host RAM
	@cd $(ROOT) && bash scripts/compute-limits.sh

.PHONY: limits-show
limits-show: ## Preview memory limits without writing
	@cd $(ROOT) && bash scripts/compute-limits.sh --dry-run

.PHONY: host
host: ## Print deployment.host (KTRANS_HOST)
	@echo "$(KTRANS_HOST)"

.PHONY: discover
discover: ## Run one-shot SNMP discovery (GROUP=srl)
	@test -n "$(GROUP)" || { echo "ERROR: pass GROUP=<name>, e.g. make discover GROUP=srl" >&2; exit 1; }
	@cd $(ROOT) && bash scripts/run-discovery.sh $(GROUP)

.PHONY: discover-all
discover-all: ## Sync clab mgmt CIDR + run SNMP discovery for all groups
	@bash $(ROOT)scripts/sync-snmp-discovery.sh

.PHONY: snmp-discover
snmp-discover: discover-all ## Alias: CIDR sync + discovery + collector reload

.PHONY: up
up: check generate bootstrap limits ## Staggered deploy (default): fabric + collectors + discover
ifeq ($(LAB_STAGGER),0)
	$(LAB_RUN) up -- bash -c '\
	  echo "==> Deploying ContainerLab topology (parallel)..." && \
	  bash $(ROOT)scripts/clab.sh deploy && \
	  echo "==> Waiting for SR Linux nodes to settle (60s)..." && \
	  sleep 60 && \
	  echo "==> Applying fabric config..." && \
	  bash $(ROOT)scripts/apply-fabric-config.sh && \
	  echo "==> deployment.host = $(KTRANS_HOST)" && \
	  echo "==> Starting telemetry compose stack..." && \
	  cd $(ROOT) && $(COMPOSE) up -d && \
	  $(MAKE) -C $(ROOT) --no-print-directory _post-up-config'
else
	$(LAB_RUN) up -- bash $(ROOT)scripts/staggered-up.sh
endif
	@echo ""
	@echo "Lab is up — SNMP, flows, syslog, traps, sFlow, and gNMI should be streaming."
	@echo "Verify: make status"
	@echo "Grafana SNMP:  count by (device_name) (kentik_snmp_CPU)"
	@echo "Grafana flows: count(network_io_by_flow_bytes)"
	@echo "Opt out of auto workloads: LAB_AUTO_TRAFFIC=0 LAB_AUTO_INTERNET_PROBES=0 LAB_AUTO_EVENTS=0 in .env"

.PHONY: up-parallel
up-parallel: ## Legacy parallel bring-up (LAB_STAGGER=0)
	@$(MAKE) LAB_STAGGER=0 up

.PHONY: _post-up-config
_post-up-config:
	@bash $(ROOT)scripts/sync-snmp-discovery.sh
	@bash $(ROOT)scripts/post-telemetry-config.sh

.PHONY: sync-clab-workdir
sync-clab-workdir: ## (internal) sync clab deploy dir when CLAB_FORCE_EXT4=1
	bash $(ROOT)scripts/sync-clab-workdir.sh

.PHONY: fabric-up
fabric-up: sync-clab-workdir ## Deploy SRL fabric only (no o11y/NetBox)
	$(LAB_RUN) fabric-up -- bash -c '\
	  bash $(ROOT)scripts/clab.sh deploy && \
	  echo "==> Waiting for SR Linux nodes to settle (60s)..." && \
	  sleep 60 && \
	  bash $(ROOT)scripts/apply-fabric-config.sh && \
	  bash $(ROOT)scripts/fabric-watch.sh start || true'
	@echo ""
	@echo "Fabric is up. After collectors: make snmp-discover"
	@echo "Try: docker exec spine1 sr_cli -ec 'show network-instance summary'"
	@echo "Client ping: docker exec client2 ping -c 2 172.17.0.1"

.PHONY: fabric-stabilize
fabric-stabilize: ## Start stopped SRL nodes (or redeploy); no collectors
	$(LAB_RUN) fabric-stabilize -- bash $(ROOT)scripts/fabric-stabilize.sh

.PHONY: fabric-watch fabric-watch-stop fabric-watch-status
fabric-watch: ## Background: recover SRL if containers stop (poll 60s)
	bash $(ROOT)scripts/fabric-watch.sh start

fabric-watch-stop: ## Stop fabric-watch background loop
	bash $(ROOT)scripts/fabric-watch.sh stop

fabric-watch-status: ## Show fabric-watch status / recent log
	bash $(ROOT)scripts/fabric-watch.sh status

.PHONY: fabric-apply
fabric-apply: sync-clab-workdir ## Apply configs/fabric/*.cfg via sr_cli
	$(LAB_RUN) fabric-apply -- bash $(ROOT)scripts/apply-fabric-config.sh

.PHONY: stabilize
stabilize: ## Recover lab without clab --reconfigure (start SRL, apply config, discover)
	$(LAB_RUN) stabilize -- bash $(ROOT)scripts/stabilize-lab.sh

.PHONY: down
down: ## Destroy fabric + stop compose
	$(LAB_RUN) down -- bash $(ROOT)scripts/lab-down.sh

.PHONY: status
status: ## Show clab nodes, compose, and a quick ping check
	@echo "── ContainerLab ──"
	@bash $(ROOT)scripts/clab.sh inspect 2>/dev/null || docker ps --filter label=clab-node-name
	@echo ""
	@echo "── Compose ──"
	@cd $(ROOT) && $(COMPOSE) ps
	@echo ""
	@echo "── Client ping (client2 → client1) ──"
	@docker exec client2 ping -c 2 -W 2 172.17.0.1 2>/dev/null || echo "(clients not ready)"

.PHONY: snmp-targets
snmp-targets: ## Sync groups/*.env TARGETS to live clab mgmt CIDR + regenerate
	$(LAB_RUN) snmp-targets -- bash $(ROOT)scripts/update-snmp-targets.sh

.PHONY: snmp-check snmp-recover
snmp-check: ## Diagnose TARGETS vs live IPs, snmpget, poller logs
	bash $(ROOT)scripts/snmp-check.sh

snmp-recover: ## Sync mgmt CIDR, enable SNMP, discover, reload pollers (after clab redeploy)
	$(LAB_RUN) snmp-recover -- bash $(ROOT)scripts/finish-bringup.sh

.PHONY: finish-flows
finish-flows: ## EVPN + softflowd + traffic + verify flows in Grafana
	$(LAB_RUN) finish-flows -- bash $(ROOT)scripts/finish-flows.sh

.PHONY: topology-exporter-image
topology-exporter-image: ## Download release binary and build local topology-exporter image
	@mkdir -p $(ROOT)topology-exporter/build
	@test -f $(ROOT)topology-exporter/build/topology-exporter-linux-amd64 \
	  || curl -fsSL -o $(ROOT)topology-exporter/build/topology-exporter-linux-amd64 \
	       https://github.com/grafana/network-topology-exporter/releases/download/v1.0.0/topology-exporter-linux-amd64
	@chmod +x $(ROOT)topology-exporter/build/topology-exporter-linux-amd64
	cd $(ROOT)topology-exporter && docker build -t srl-local/network-topology-exporter:v1.0.0 .

.PHONY: ktranslate-dev-image
ktranslate-dev-image: ## Build ktranslate with OTLP CHF fix (Mesverrum fix/otel-chf-flow-only)
	bash $(ROOT)scripts/build-ktranslate-dev-image.sh

.PHONY: compose-host-env
compose-host-env: ## Write compose-host.generated.env (deployment.host for compose)
	@bash $(ROOT)scripts/write-compose-host-env.sh

.PHONY: ktranslate-dev-recreate
ktranslate-dev-recreate: compose-host-env ## Recreate all ktranslate containers (set KTRANSLATE_IMAGE in .env first)
	@test -n "$$(grep -E '^KTRANSLATE_IMAGE=.+' $(ROOT).env 2>/dev/null)" \
	  || { echo "Set KTRANSLATE_IMAGE=srl-local/ktranslate:otel-chf-dev in local/.env first"; exit 1; }
	$(COMPOSE) up -d --pull never --force-recreate ktranslate_snmp_srl ktranslate_flow ktranslate_sflow ktranslate_syslog
	@$(MAKE) softflowd

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

.PHONY: topology-up
topology-up: check generate topology-exporter-image ## Start optional topology_exporter (set LAB_TOPOLOGY_EXPORTER=1 in .env)
	@echo "==> Starting topology_exporter (compose profile topology)..."
	@cd $(ROOT) && LAB_TOPOLOGY_EXPORTER=1 docker compose --env-file .env --env-file compose-host.generated.env --profile topology \
	  -f compose-base.yaml -f compose-groups.generated.yaml -f compose-catalog.generated.yaml \
	  -f compose-limits.generated.yaml up -d topology_exporter
	@cd $(ROOT) && LAB_TOPOLOGY_EXPORTER=1 bash scripts/update-topology-targets.sh
	@echo "Optional: append scripts/topology-health-scrape.alloy to alloy/config.alloy and recreate alloy for :9100 health metrics."

.PHONY: softflowd
softflowd: ## (Re)start softflowd on clients
	$(LAB_RUN) softflowd -- bash $(ROOT)scripts/softflowd.sh

.PHONY: sflow
sflow: ## (Re)apply spine sFlow → ktranslate_sflow:6343
	$(LAB_RUN) sflow -- bash $(ROOT)scripts/sflow-config.sh

.PHONY: flow-dns
flow-dns: ## Regenerate flow_dns PTR records from device catalog (+ clab overlay)
	bash $(ROOT)scripts/refresh-flow-dns.sh

.PHONY: lab-dns
lab-dns: flow-dns ## Deprecated alias for flow-dns

.PHONY: syslog
syslog: ## (Re)apply syslog remote-server on SR Linux nodes
	bash $(ROOT)scripts/syslog-config.sh

.PHONY: wan-ifalias
wan-ifalias: ## Set WAN interface descriptions (ifAlias) on spine/leaves
	python3 $(ROOT)scripts/apply-wan-ifalias.py

.PHONY: network-alerts
network-alerts: ## Provision Grafana network alert rules (marcnetterfield1 / network-lab folder)
	python3 $(ROOT)scripts/provision-network-alerts.py

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
	$(LAB_RUN) traffic -- bash $(ROOT)scripts/traffic.sh start

.PHONY: traffic-stop
traffic-stop: ## Stop traffic workloads
	$(LAB_RUN) traffic-stop -- bash $(ROOT)scripts/traffic.sh stop

.PHONY: validate-flow-counts
validate-flow-counts: ## Sanity-check flow series/rates vs lab traffic (see scripts/validate-flow-counts.py)
	python3 $(ROOT)scripts/validate-flow-counts.py $(ARGS)

.PHONY: traffic-status
traffic-status: ## Show traffic workload status
	bash $(ROOT)scripts/traffic.sh status

.PHONY: north-south-flows
north-south-flows: ## Restart dual softflowd (eth0+eth1) + internet probes on running lab
	python3 $(ROOT)scripts/apply-north-south-flows.py

.PHONY: flow-dashboard-download
flow-dashboard-download: ## Download live ktranslate-flow-summary v2 manifest from Grafana
	python3 $(ROOT)scripts/download-flow-dashboard.py

.PHONY: dash-live-sync
dash-live-sync: ## Pull all ktranslate dashboards 00–04 + refresh agent docs
	python3 $(ROOT)scripts/sync-ktranslate-dashboards-live.py --pull

.PHONY: verify-flow-countries
verify-flow-countries: ## List public network_peer_country values in flow metrics
	python3 $(ROOT)scripts/verify-flow-countries.py

.PHONY: internet-probes
internet-probes: ## Start HTTPS probes for geomap country codes (mgmt eth0)
	$(LAB_RUN) internet-probes -- bash $(ROOT)scripts/internet-probes.sh start

.PHONY: internet-probes-stop
internet-probes-stop: ## Stop internet HTTPS probes
	$(LAB_RUN) internet-probes-stop -- bash $(ROOT)scripts/internet-probes.sh stop

.PHONY: internet-probes-status
internet-probes-status: ## Show internet probe status
	bash $(ROOT)scripts/internet-probes.sh status

.PHONY: join-app
join-app: ## Build+deploy OTel Clos join demo (client1→client2 EVPN + traces→Alloy)
	bash $(ROOT)scripts/join-app.sh start

.PHONY: join-app-stop
join-app-stop: ## Stop Clos join demo on clients
	bash $(ROOT)scripts/join-app.sh stop

.PHONY: join-app-status
join-app-status: ## Show Clos join demo status
	bash $(ROOT)scripts/join-app.sh status

.PHONY: mgmt-api-mock
mgmt-api-mock: ## Export SR Linux mgmt API catalog + mock samples (OTLP)
	bash $(ROOT)scripts/mgmt-api-mock.sh emit

.PHONY: mgmt-api-mock-build
mgmt-api-mock-build: ## Build mgmt-api-mock binary only
	bash $(ROOT)scripts/mgmt-api-mock.sh build

.PHONY: telegraf-poc
telegraf-poc: ## Start Telegraf exec gap-fill PoC (Flex analog → OTLP)
	bash $(ROOT)scripts/telegraf-flex-poc.sh start

.PHONY: telegraf-poc-stop
telegraf-poc-stop: ## Stop Telegraf flex PoC container
	bash $(ROOT)scripts/telegraf-flex-poc.sh stop

.PHONY: telegraf-poc-status
telegraf-poc-status: ## Show Telegraf flex PoC status / recent logs
	bash $(ROOT)scripts/telegraf-flex-poc.sh status

.PHONY: telegraf-poc-build
telegraf-poc-build: ## Build Telegraf flex PoC image only
	bash $(ROOT)scripts/telegraf-flex-poc.sh build

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

.PHONY: lab-log-events lab-log-events-stop lab-log-status
lab-log-events: ## Start background docker events log (state/docker-events.log)
	bash $(ROOT)scripts/lab-log-events.sh start

lab-log-events-stop: ## Stop docker events log
	bash $(ROOT)scripts/lab-log-events.sh stop

lab-log-status: ## Show recent lab-actions + docker-events logs
	bash $(ROOT)scripts/lab-log-status.sh $(LINES)

.PHONY: aws-lab-discover aws-lab-up aws-lab-down
aws-lab-discover: ## Write terraform/aws-dashboard-lab/terraform.tfvars from live VPC discovery
	bash $(ROOT)scripts/aws-lab-discover.sh

aws-lab-up: ## NLB + traffic hosts for Cloud Network dashboards (set AWS_PROFILE)
	bash $(ROOT)scripts/aws-lab-up.sh

aws-lab-down: ## Destroy AWS dashboard lab (run between sessions)
	bash $(ROOT)scripts/aws-lab-down.sh

.PHONY: generate-k8s deploy-ktranslate-golden verify-ktranslate-names
generate-k8s: generate ## Render k8s/ktranslate-golden from local/ golden path
	python3 $(ROOT)scripts/generate-k8s-telemetry.py

verify-ktranslate-names: ## Assert OTEL_SERVICE_NAME host suffix on compose/k3s (+ optional Prom)
	bash $(ROOT)scripts/verify-ktranslate-service-names.sh --prometheus

deploy-ktranslate-golden: generate-k8s ## kubectl apply -k k8s/ktranslate-golden (+ GC secret)
	bash $(ROOT)scripts/deploy-ktranslate-golden.sh

.PHONY: colocated-lab-discover colocated-lab-up colocated-lab-down
colocated-lab-discover: ## Write terraform/colocated-network-lab/terraform.tfvars
	bash $(ROOT)scripts/colocated-lab-discover.sh

colocated-lab-up: ## EC2 ContainerLab fabric + k3s ktranslate-golden (reads GC_OTLP_* from .env)
	bash $(ROOT)scripts/colocated-lab-up.sh

colocated-lab-down: ## Destroy colocated network lab
	bash $(ROOT)scripts/colocated-lab-down.sh

.PHONY: hybrid-probe-laptop hybrid-probe-aws hybrid-probe-once hybrid-dash-import
hybrid-probe-laptop: ## Laptop mesh probe → OTLP (listens :18080 for AWS callbacks)
	bash $(ROOT)scripts/hybrid-probe-laptop.sh

hybrid-probe-once: ## One probe cycle from laptop targets (no listener)
	python3 $(ROOT)scripts/hybrid-probe-once.py

hybrid-probe-aws: ## Deploy mesh probe to AWS lab EC2 via SSM (needs SSM agent)
	python3 $(ROOT)scripts/hybrid-probe-deploy-aws.py

hybrid-dash-import: ## Build + import dashboards 05–06 (connectivity + capacity)
	python3 $(ROOT)scripts/build-aws-hybrid-dashboards.py --import
