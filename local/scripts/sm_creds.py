"""Parse SM credential files from local/state/ (probe agents + optional API access token)."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
STATE = ROOT / "local" / "state"
DEFAULT_API_SERVER = "synthetic-monitoring-grpc-us-east-0.grafana.net:443"


def parse_kv_file(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    if not path.is_file():
        return out
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            out.setdefault("api_token", line)
            continue
        key, val = line.split("=", 1)
        out[key.strip()] = val.strip()
    return out


def probe_creds(name: str) -> dict[str, str]:
    """Laptop or colocated private-probe agent credentials."""
    env_path = STATE / f"sm-probe-{name}.env"
    token_path = STATE / f"sm-probe-{name}.token"
    data = parse_kv_file(env_path)
    if not data.get("api_token") and token_path.is_file():
        raw = token_path.read_text(encoding="utf-8").strip()
        if raw and "=" not in raw.splitlines()[0]:
            data["api_token"] = raw.splitlines()[0].strip()
    data.setdefault("api_server", DEFAULT_API_SERVER)
    if not data.get("api_token"):
        raise RuntimeError(f"Missing api_token in {env_path} or {token_path}")
    return data


def sm_api_access_token() -> str:
    """Token for SM check CRUD via gcx (Config → Access tokens)."""
    api_path = STATE / "sm-api.token"
    if api_path.is_file():
        for line in api_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                return line
    path = STATE / "sm-access.token"
    data = parse_kv_file(path)
    token = data.get("api_token", "").strip()
    if token and path.read_text(encoding="utf-8").count("api_token=") > 1:
        return ""
    return token
