#!/usr/bin/env bash
# Run ON colocated EC2: NetBox OSS (+ Diode plugin) + Diode + live Orb → Alloy OTLP.
# Invoked by scripts/netbox-deploy-colocated.py via SSM.
set -euo pipefail

REPO_ROOT="${REPO_ROOT:-/opt/network-o11y-demo}"
LAB="${REPO_ROOT}/local"
OSS_SRC="${LAB}/netbox-oss"
STACK="${OSS_SRC}/netbox-docker"
DIODE_DIR="${DIODE_DIR:-/opt/diode}"
TAG="${NETBOX_DOCKER_TAG:-5.0.2}"
PORT="${NETBOX_OSS_PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"

info() { echo "==> $*"; }
die()  { echo "ERROR: $*" >&2; exit 1; }

command -v docker >/dev/null || die "docker required"
docker compose version >/dev/null || die "docker compose required"
command -v git >/dev/null || die "git required"
command -v curl >/dev/null || die "curl required"
command -v jq >/dev/null || {
  info "installing jq"
  if command -v apt-get >/dev/null; then
    sudo apt-get update -y && sudo apt-get install -y jq
  else
    die "jq required"
  fi
}

mkdir -p "$OSS_SRC"
if [[ ! -d "${STACK}/.git" ]]; then
  info "cloning netbox-community/netbox-docker @ ${TAG}"
  git clone --depth 1 --branch "$TAG" \
    https://github.com/netbox-community/netbox-docker.git "$STACK"
else
  info "netbox-docker present — checkout ${TAG}"
  git -C "$STACK" fetch --depth 1 origin "refs/tags/${TAG}:refs/tags/${TAG}" 2>/dev/null || true
  git -C "$STACK" checkout -q "$TAG" || git -C "$STACK" checkout -q "tags/${TAG}" || true
fi

# --- Diode first (oauth secrets drive plugin config) ---
info "preparing Diode at ${DIODE_DIR}"
mkdir -p "$DIODE_DIR"
cd "$DIODE_DIR"
if [[ ! -f quickstart.sh ]]; then
  curl -sSfLo quickstart.sh \
    https://raw.githubusercontent.com/netboxlabs/diode/release/diode-server/docker/scripts/quickstart.sh
  chmod +x quickstart.sh
fi
if [[ ! -f docker-compose.yaml ]]; then
  ./quickstart.sh "$BASE"
fi

NETBOX_TO_DIODE_SECRET="$(jq -r '.[] | select(.client_id == "netbox-to-diode") | .client_secret' oauth2/client/client-credentials.json)"
DIODE_INGEST_ID="$(jq -r '.[] | select(.client_id == "diode-ingest") | .client_id' oauth2/client/client-credentials.json)"
DIODE_INGEST_SECRET="$(jq -r '.[] | select(.client_id == "diode-ingest") | .client_secret' oauth2/client/client-credentials.json)"
[[ -n "$NETBOX_TO_DIODE_SECRET" && "$NETBOX_TO_DIODE_SECRET" != null ]] || die "missing netbox-to-diode secret"
[[ -n "$DIODE_INGEST_SECRET" && "$DIODE_INGEST_SECRET" != null ]] || die "missing diode-ingest secret"

# Diode containers must reach NetBox on the Docker host, not 127.0.0.1 inside the container.
HOST_GW="$(docker network inspect bridge -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null | head -1 || true)"
HOST_GW="${HOST_GW:-172.17.0.1}"
NETBOX_FROM_DIODE="http://${HOST_GW}:${PORT}"
if grep -q '^NETBOX_HOST=' .env 2>/dev/null; then
  sed -i "s|^NETBOX_HOST=.*|NETBOX_HOST=${NETBOX_FROM_DIODE}|" .env
else
  echo "NETBOX_HOST=${NETBOX_FROM_DIODE}" >>.env
fi
sed -i "s|http://127.0.0.1:${PORT}|${NETBOX_FROM_DIODE}|g; s|http://localhost:${PORT}|${NETBOX_FROM_DIODE}|g" .env || true
info "Diode NETBOX_HOST=${NETBOX_FROM_DIODE}"

# --- NetBox image with Diode plugin ---
info "staging NetBox plugin build files"
cp -f "${OSS_SRC}/Dockerfile-Plugins" "${STACK}/Dockerfile-Plugins"
cp -f "${OSS_SRC}/plugin_requirements.txt" "${STACK}/plugin_requirements.txt"
cp -f "${OSS_SRC}/docker-compose.override.colocated.yml" "${STACK}/docker-compose.override.yml"
mkdir -p "${STACK}/configuration"
# Start from upstream plugins.py then overwrite with Diode config
HOST_GW_FOR_PLUGIN="$(docker network inspect bridge -f '{{range .IPAM.Config}}{{.Gateway}}{{end}}' 2>/dev/null | head -1 || true)"
HOST_GW_FOR_PLUGIN="${HOST_GW_FOR_PLUGIN:-172.17.0.1}"
if [[ -f "${OSS_SRC}/configuration/plugins.py" ]]; then
  sed -e "s|PLACEHOLDER_NETBOX_TO_DIODE_SECRET|${NETBOX_TO_DIODE_SECRET}|g" \
      -e "s|grpc://127.0.0.1:8080/diode|grpc://${HOST_GW_FOR_PLUGIN}:8080/diode|g" \
      -e "s|grpc://172.17.0.1:8080/diode|grpc://${HOST_GW_FOR_PLUGIN}:8080/diode|g" \
    "${OSS_SRC}/configuration/plugins.py" > "${STACK}/configuration/plugins.py"
else
  die "missing ${OSS_SRC}/configuration/plugins.py"
fi
info "plugin diode_target=grpc://${HOST_GW_FOR_PLUGIN}:8080/diode"

# Admin password: reuse from .env or generate (never default to admin/admin).
ENV_FILE="${LAB}/.env"
touch "$ENV_FILE"
if ! grep -qE '^NETBOX_ADMIN_PASSWORD=.+' "$ENV_FILE" 2>/dev/null; then
  info "generating NETBOX_ADMIN_PASSWORD"
  python3 - "$ENV_FILE" <<'PY'
import pathlib, re, secrets, string, sys
p = pathlib.Path(sys.argv[1])
text = p.read_text(encoding="utf-8") if p.exists() else ""
alphabet = string.ascii_letters + string.digits + "-_"
pw = "".join(secrets.choice(alphabet) for _ in range(28))
pairs = {"NETBOX_ADMIN_USER": "admin", "NETBOX_ADMIN_PASSWORD": pw, "SUPERUSER_PASSWORD": pw}
for k, v in pairs.items():
    line = f"{k}={v}"
    if re.search(rf"^{re.escape(k)}=.*$", text, flags=re.M):
        text = re.sub(rf"^{re.escape(k)}=.*$", line, text, count=1, flags=re.M)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += line + "\n"
p.write_text(text, encoding="utf-8")
print("wrote NETBOX_ADMIN_PASSWORD (len=%d)" % len(pw))
PY
fi
set -a
# shellcheck disable=SC1090
source <(sed 's/\r$//' "$ENV_FILE" | grep -E '^(NETBOX_ADMIN_|SUPERUSER_PASSWORD=)' || true)
set +a
export NETBOX_ADMIN_USER="${NETBOX_ADMIN_USER:-admin}"
export NETBOX_ADMIN_PASSWORD="${NETBOX_ADMIN_PASSWORD:?NETBOX_ADMIN_PASSWORD missing in $ENV_FILE}"
export SUPERUSER_PASSWORD="${SUPERUSER_PASSWORD:-$NETBOX_ADMIN_PASSWORD}"

if [[ -f "${STACK}/env/netbox.env" ]] && grep -q '^SKIP_SUPERUSER=true' "${STACK}/env/netbox.env"; then
  sed -i 's/^SKIP_SUPERUSER=true/SKIP_SUPERUSER=false/' "${STACK}/env/netbox.env"
fi

info "building NetBox image with diode plugin (several minutes)"
( cd "$STACK" && NETBOX_OSS_PORT="$PORT" \
  NETBOX_ADMIN_USER="$NETBOX_ADMIN_USER" \
  NETBOX_ADMIN_PASSWORD="$NETBOX_ADMIN_PASSWORD" \
  docker compose build netbox )

info "starting postgres/redis/netbox"
( cd "$STACK" && NETBOX_OSS_PORT="$PORT" \
  NETBOX_ADMIN_USER="$NETBOX_ADMIN_USER" \
  NETBOX_ADMIN_PASSWORD="$NETBOX_ADMIN_PASSWORD" \
  docker compose up -d postgres redis redis-cache netbox )

info "waiting for NetBox UI (up to 15m)"
ok=0
for i in $(seq 1 180); do
  code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "${BASE}/login/" 2>/dev/null || echo 000)"
  if [[ "$code" == "200" ]]; then
    ok=1
    break
  fi
  if [[ $((i % 12)) -eq 0 ]]; then
    ( cd "$STACK" && docker compose ps netbox || true )
  fi
  sleep 5
done
[[ "$ok" == "1" ]] || {
  ( cd "$STACK" && docker compose logs netbox --tail 80 || true )
  die "NetBox UI not ready at ${BASE}/login/"
}

info "starting netbox-worker + migrate diode plugin"
( cd "$STACK" && NETBOX_OSS_PORT="$PORT" docker compose up -d )
( cd "$STACK" && docker compose exec -T netbox \
  /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate netbox_diode_plugin ) || \
( cd "$STACK" && docker compose exec -T netbox \
  /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py migrate )

info "creating admin API token"
TOKEN="$(
  cd "$STACK" && docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell <<'PY'
from users.models import Token, User
u = User.objects.filter(username='admin').first()
if u is None:
    raise SystemExit('admin user missing')
Token.objects.filter(user=u, description='network-o11y-lab').delete()
t = Token(user=u, description='network-o11y-lab', version=2)
t.save()
print(f'nbt_{t.key}.{t.token}')
PY
)"
TOKEN="$(echo "$TOKEN" | tr -d '\r' | grep -E '^nbt_' | tail -1)"
[[ -n "$TOKEN" ]] || die "failed to create NetBox API token"

# Ensure diode user exists (plugin may create it)
( cd "$STACK" && docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell <<'PY' || true
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='diode').exists():
    User.objects.create_user('diode', password=None)
    print('created diode user')
else:
    print('diode user ok')
PY
)

info "starting Diode"
( cd "$DIODE_DIR" && docker compose up -d )
sleep 10
( cd "$DIODE_DIR" && docker compose ps ) || true

# Persist creds on the lab host
ENV_FILE="${LAB}/.env"
touch "$ENV_FILE"
python3 - "$ENV_FILE" "$BASE" "$TOKEN" "$DIODE_INGEST_ID" "$DIODE_INGEST_SECRET" "${NETBOX_ADMIN_USER}" "${NETBOX_ADMIN_PASSWORD}" <<'PY'
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
base, token, cid, csec, admin_user, admin_pw = sys.argv[2:8]
text = path.read_text(encoding="utf-8") if path.exists() else ""
pairs = {
    "NETBOX_URL": base,
    "NETBOX_HOST_URL": base,
    "NETBOX_API_URL": f"{base.rstrip('/')}/api/dcim/devices/",
    "NETBOX_TOKEN": token,
    "NETBOX_ADMIN_USER": admin_user,
    "NETBOX_ADMIN_PASSWORD": admin_pw,
    "SUPERUSER_PASSWORD": admin_pw,
    "DIODE_CLIENT_ID": cid,
    "DIODE_CLIENT_SECRET": csec,
    "ORB_DIODE_TARGET": "grpc://127.0.0.1:8080/diode",
    "ORB_DRY_RUN": "0",
    "ORB_OTLP": "1",
    "ORB_PKTVISOR": "1",
    "ORB_PKTVISOR_NETFLOW_PORT": "19995",
    "ORB_PKTVISOR_SFLOW_PORT": "16343",
    "ORB_AGENT_NAME": "network-o11y-colocated",
}
for k, v in pairs.items():
    line = f"{k}={v}"
    if re.search(rf"^{k}=.*$", text, flags=re.M):
        text = re.sub(rf"^{k}=.*$", line, text, count=1, flags=re.M)
    else:
        if text and not text.endswith("\n"):
            text += "\n"
        text += f"{line}\n"
path.write_text(text, encoding="utf-8")
print(f"updated {path}")
PY

info "reconfiguring Orb for live Diode + OTLP → Alloy :4317"
export ORB_DRY_RUN=0
export ORB_OTLP=1
export ORB_PKTVISOR=1
export ORB_PKTVISOR_NETFLOW_PORT=19995
export ORB_PKTVISOR_SFLOW_PORT=16343
export ORB_DIODE_TARGET="grpc://127.0.0.1:8080/diode"
export DIODE_CLIENT_ID="$DIODE_INGEST_ID"
export DIODE_CLIENT_SECRET="$DIODE_INGEST_SECRET"
export ORB_AGENT_NAME="network-o11y-colocated"
export ORB_SNMP_TARGETS="${ORB_SNMP_TARGETS:-172.20.20.0/24}"
export ORB_SNMP_COMMUNITY="${ORB_SNMP_COMMUNITY:-public}"
bash "${LAB}/scripts/orb-down.sh" || true
bash "${LAB}/scripts/orb-up.sh"
bash "${LAB}/scripts/softflowd.sh" || warn "softflowd dual-export failed"
bash "${LAB}/scripts/sflow-config.sh" || warn "sflow dual-collector failed"

info "NetBox SoT in Grafana is Infinity REST (no inventory OTLP sidecar)"
pkill -f netbox-inventory-otlp.py || true
rm -f /var/run/netbox-inventory-otlp.pid || true

info "DONE"
echo "NetBox UI (on host): ${BASE}/"
echo "Login: user=\${NETBOX_ADMIN_USER:-admin}  password=see NETBOX_ADMIN_PASSWORD in ${LAB}/.env (not admin/admin)"
echo "Rotate anytime: python3 ${LAB}/scripts/rotate-netbox-admin-password.py  (from laptop/repo)"
echo "Access from laptop: aws ssm start-session --target <iid> --document-name AWS-StartPortForwardingSession --parameters portNumber=${PORT},localPortNumber=${PORT}"
echo "Then open http://127.0.0.1:${PORT}/"
echo "Orb → Diode → NetBox (live). Grafana Cloud queries NetBox via Infinity datasource netbox-api."
echo "Validate NetBox: curl -s -H \"Authorization: Bearer \$NETBOX_TOKEN\" ${BASE}/api/dcim/devices/ | jq '.count'"
echo "Validate Grafana: dashboards 20/22/24/25 NetBox panels (Infinity), plus Orb collector metrics (deployment_host=orb-agent)"
