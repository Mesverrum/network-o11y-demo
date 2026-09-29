# Alias NETTERFIELD_GRAFANA_* → GRAFANA_* (scripts still use the latter).
# Source after local/.env. Safe to source more than once.
GRAFANA_URL="${GRAFANA_URL:-${NETTERFIELD_GRAFANA_URL:-}}"
GRAFANA_TOKEN="${GRAFANA_TOKEN:-${NETTERFIELD_GRAFANA_TOKEN:-}}"
export GRAFANA_URL GRAFANA_TOKEN
