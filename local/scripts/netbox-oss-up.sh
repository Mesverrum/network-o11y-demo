#!/usr/bin/env bash
# Bring up NetBox OSS via netbox-community/netbox-docker (sidecar; not on main lab path).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OSS="${ROOT}/netbox-oss"
STACK="${OSS}/netbox-docker"
TAG="${NETBOX_DOCKER_TAG:-5.0.2}"
PORT="${NETBOX_OSS_PORT:-8000}"
BASE="http://127.0.0.1:${PORT}"

info() { echo "==> $*"; }
die()  { echo "ERROR: $*" >&2; exit 1; }

command -v docker >/dev/null || die "docker required"
docker compose version >/dev/null || die "docker compose plugin required"
command -v git >/dev/null || die "git required"

mkdir -p "$OSS"
if [[ ! -d "${STACK}/.git" ]]; then
  info "cloning netbox-community/netbox-docker @ ${TAG}"
  git clone --depth 1 --branch "$TAG" \
    https://github.com/netbox-community/netbox-docker.git "$STACK"
else
  info "netbox-docker already present — checkout ${TAG}"
  git -C "$STACK" fetch --depth 1 origin "refs/tags/${TAG}:refs/tags/${TAG}" 2>/dev/null || true
  git -C "$STACK" checkout -q "$TAG" || git -C "$STACK" checkout -q "tags/${TAG}"
fi

cp -f "${OSS}/docker-compose.override.yml" "${STACK}/docker-compose.override.yml"
# Ensure lab env override for lighter workers is applied (also in compose override)
if [[ -f "${STACK}/env/netbox.env" ]]; then
  # Force create superuser on first boot (default env has SKIP_SUPERUSER=true)
  if grep -q '^SKIP_SUPERUSER=true' "${STACK}/env/netbox.env"; then
    sed -i 's/^SKIP_SUPERUSER=true/SKIP_SUPERUSER=false/' "${STACK}/env/netbox.env"
  fi
fi

info "pulling images"
( cd "$STACK" && NETBOX_OSS_PORT="$PORT" docker compose pull )

info "starting NetBox OSS on :${PORT} (postgres/redis/netbox first — migrations can take several minutes)"
( cd "$STACK" && NETBOX_OSS_PORT="$PORT" docker compose up -d postgres redis redis-cache netbox )

info "waiting for UI/API (up to 10m; /api/status may 403 until login_required is satisfied)"
ok=0
for i in $(seq 1 120); do
  login_code="$(curl -sS -o /dev/null -w '%{http_code}' --max-time 5 "${BASE}/login/" 2>/dev/null || echo 000)"
  if [[ "$login_code" == "200" ]]; then
    ok=1
    break
  fi
  if [[ $((i % 12)) -eq 0 ]]; then
    ( cd "$STACK" && docker compose ps netbox || true )
  fi
  sleep 5
done
[[ "$ok" == "1" ]] || {
  ( cd "$STACK" && docker compose logs netbox --tail 40 || true )
  die "NetBox UI not ready at ${BASE}/login/ (last http=${login_code:-?})"
}

info "starting netbox-worker"
( cd "$STACK" && NETBOX_OSS_PORT="$PORT" docker compose up -d )

info "ensuring API token for admin"
TOKEN_FILE="$(mktemp)"
( cd "$STACK" && docker compose exec -T netbox /opt/netbox/venv/bin/python /opt/netbox/netbox/manage.py shell <<'PY'
from users.models import Token, User
u = User.objects.filter(username='admin').first()
if u is None:
    raise SystemExit('admin user missing')
Token.objects.filter(user=u, description='network-o11y-lab').delete()
t = Token(user=u, description='network-o11y-lab', version=2)
t.save()
# NetBox 4.5+ v2: store Bearer value nbt_<key>.<plaintext> (plaintext only at create)
print('TOKEN_BEGIN')
print(f'nbt_{t.key}.{t.token}')
print('TOKEN_END')
PY
) >"$TOKEN_FILE" 2>"${TOKEN_FILE}.err" || true
TOKEN="$(awk '/^TOKEN_BEGIN$/{getline; print; exit}' "$TOKEN_FILE" | tr -d '\r')"
if [[ -z "$TOKEN" || "$TOKEN" != nbt_* ]]; then
  echo "---- manage.py stdout ----" >&2
  cat "$TOKEN_FILE" >&2 || true
  echo "---- manage.py stderr ----" >&2
  cat "${TOKEN_FILE}.err" >&2 || true
  rm -f "$TOKEN_FILE" "${TOKEN_FILE}.err"
  die "failed to create API token"
fi
echo "==> API token created (v2, len=${#TOKEN})"
rm -f "$TOKEN_FILE" "${TOKEN_FILE}.err"

ENV_FILE="${ROOT}/.env"
[[ -f "$ENV_FILE" ]] || die "missing ${ENV_FILE} — copy from .env.example first"

python3 - "$ENV_FILE" "$BASE" "$TOKEN" <<'PY'
import pathlib, re, sys
path = pathlib.Path(sys.argv[1])
base, token = sys.argv[2], sys.argv[3]
text = path.read_text(encoding="utf-8")
pairs = {
    "NETBOX_URL": base,
    "NETBOX_HOST_URL": base,
    "NETBOX_API_URL": f"{base.rstrip('/')}/api/dcim/devices/",
    "NETBOX_TOKEN": token,
}
for k, v in pairs.items():
    line = f"{k}={v}"
    if re.search(rf"^{k}=.*$", text, flags=re.M):
        text = re.sub(rf"^{k}=.*$", line, text, count=1, flags=re.M)
    else:
        if not text.endswith("\n"):
            text += "\n"
        text += f"\n# NetBox OSS (make netbox-oss-up)\n{line}\n"
path.write_text(text, encoding="utf-8")
print(f"updated {path} ({', '.join(pairs)})")
PY

info "NetBox UI: ${BASE}/  (admin / admin)"
info "Creds written to local/.env — next: make netbox-sync"
info "Stop later: make netbox-oss-down"
