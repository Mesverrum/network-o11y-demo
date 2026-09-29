#!/usr/bin/env python3
"""Token-gated HTTP API that toggles catalogued Clos circuits (admin-state).

Env:
  LAB_FAULT_TOKEN          required (except /healthz)
  LAB_FAULT_BIND           default 0.0.0.0
  LAB_FAULT_PORT           default 8788
  LAB_CIRCUITS_FILE        default next to repo fixtures
  LAB_FAULT_SCRIPT         default ../scripts/lab-circuit-fault.sh
  LAB_FAULT_DASH_URL       optional redirect after GET mutate
  LAB_FAULT_CORS_ORIGIN    default https://*.grafana.net (prefix match)
"""
from __future__ import annotations

import hmac
import json
import os
import re
import subprocess
import sys
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CIRCUIT_RE = re.compile(r"^[A-Z0-9][A-Z0-9_-]{0,47}$")
STATE_RE = re.compile(r"^(enable|disable)$")


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


TOKEN = _env("LAB_FAULT_TOKEN")
BIND = _env("LAB_FAULT_BIND", "0.0.0.0")
PORT = int(_env("LAB_FAULT_PORT", "8788") or "8788")
CATALOG = Path(_env("LAB_CIRCUITS_FILE") or str(ROOT / "fixtures" / "lab-circuits.json"))
SCRIPT = Path(_env("LAB_FAULT_SCRIPT") or str(ROOT / "scripts" / "lab-circuit-fault.sh"))
DASH_URL = _env("LAB_FAULT_DASH_URL")
CORS_ORIGIN = _env("LAB_FAULT_CORS_ORIGIN", "https://")


def load_catalog() -> dict:
    return json.loads(CATALOG.read_text(encoding="utf-8"))


def token_ok(provided: str) -> bool:
    if not TOKEN or not provided:
        return False
    return hmac.compare_digest(provided.encode(), TOKEN.encode())


def extract_token(handler: BaseHTTPRequestHandler) -> str:
    auth = handler.headers.get("Authorization") or ""
    if auth.lower().startswith("bearer "):
        return auth[7:].strip()
    hdr = handler.headers.get("X-Lab-Fault-Token") or ""
    if hdr:
        return hdr.strip()
    parsed = urllib.parse.urlparse(handler.path)
    qs = urllib.parse.parse_qs(parsed.query)
    vals = qs.get("token") or []
    return vals[0] if vals else ""


def cors_ok(origin: str) -> bool:
    if not origin:
        return False
    if CORS_ORIGIN.endswith(".grafana.net") or CORS_ORIGIN == "https://":
        return origin.startswith("https://") and origin.endswith(".grafana.net")
    return origin == CORS_ORIGIN or origin.startswith(CORS_ORIGIN.rstrip("*"))


def parse_status(text: str) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    admin = out.get("admin_state", "")
    if "enable" in admin and "disable" not in admin:
        out["admin_state"] = "enable"
    elif "disable" in admin:
        out["admin_state"] = "disable"
    return out


def run_fault(action: str, circuit: str) -> tuple[int, str]:
    if action not in ("enable", "disable", "status"):
        return 400, "bad action"
    if not CIRCUIT_RE.match(circuit):
        return 400, "bad circuit id"
    if not SCRIPT.is_file():
        return 500, f"missing script {SCRIPT}"
    try:
        proc = subprocess.run(
            ["bash", str(SCRIPT), action, circuit],
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return 504, "device command timed out"
    text = (proc.stdout or "") + (("\n" + proc.stderr) if proc.stderr else "")
    return (200 if proc.returncode == 0 else 500), text


class Handler(BaseHTTPRequestHandler):
    server_version = "lab-fault-webhook/1.0"

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        msg = fmt % args
        msg = re.sub(r"([?&]token=)[^&\s]+", r"\1[redacted]", msg, flags=re.I)
        sys.stderr.write("%s - %s\n" % (self.address_string(), msg))

    def _cors(self) -> None:
        origin = self.headers.get("Origin") or ""
        if cors_ok(origin):
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Authorization, Content-Type, X-Lab-Fault-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

    def _json(self, code: int, payload: object) -> None:
        raw = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self._cors()
        self.end_headers()
        self.wfile.write(raw)

    def _redirect(self, url: str) -> None:
        self.send_response(302)
        self.send_header("Location", url)
        self._cors()
        self.end_headers()

    def do_OPTIONS(self) -> None:  # noqa: N802
        self.send_response(204)
        self._cors()
        self.end_headers()

    def do_GET(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        qs = urllib.parse.parse_qs(parsed.query)
        if path in ("/healthz", "/health"):
            self._json(200, {"ok": True})
            return
        if not token_ok(extract_token(self)):
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        if path == "/v1/circuits":
            self._json(200, self._list_circuits())
            return
        m = re.fullmatch(r"/v1/circuits/([A-Z0-9][A-Z0-9_-]{0,47})", path)
        if not m:
            self._json(404, {"ok": False, "error": "not found"})
            return
        circuit = m.group(1)
        action = (qs.get("admin_state") or [""])[0].strip()
        redirect = (qs.get("redirect") or [""])[0] in ("1", "true", "yes")
        if action:
            if not STATE_RE.match(action):
                self._json(400, {"ok": False, "error": "admin_state must be enable|disable"})
                return
            self._mutate(circuit, action, redirect=redirect)
            return
        self._status(circuit)

    def do_POST(self) -> None:  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/") or "/"
        if not token_ok(extract_token(self)):
            self._json(401, {"ok": False, "error": "unauthorized"})
            return
        m = re.fullmatch(r"/v1/circuits/([A-Z0-9][A-Z0-9_-]{0,47})", path)
        if not m:
            self._json(404, {"ok": False, "error": "not found"})
            return
        length = int(self.headers.get("Content-Length") or "0")
        raw = self.rfile.read(length) if length else b"{}"
        try:
            body = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            self._json(400, {"ok": False, "error": "invalid json"})
            return
        action = str(body.get("admin_state") or "").strip()
        if not STATE_RE.match(action):
            self._json(400, {"ok": False, "error": "admin_state must be enable|disable"})
            return
        self._mutate(m.group(1), action, redirect=False)

    def _list_circuits(self) -> dict:
        data = load_catalog()
        rows = []
        for cid, spec in (data.get("circuits") or {}).items():
            code, text = run_fault("status", cid)
            parsed = parse_status(text)
            rows.append(
                {
                    "circuit_id": cid,
                    "description": spec.get("description"),
                    "node": spec.get("node"),
                    "iface": spec.get("iface"),
                    "peer_node": spec.get("peer_node"),
                    "peer_iface": spec.get("peer_iface"),
                    "admin_state": parsed.get("admin_state") if code == 200 else "unknown",
                    "ok": code == 200,
                }
            )
        return {"ok": True, "circuits": rows}

    def _status(self, circuit: str) -> None:
        code, text = run_fault("status", circuit)
        parsed = parse_status(text)
        self._json(
            200 if code == 200 else code,
            {"ok": code == 200, "circuit_id": circuit, **parsed, "raw": text.strip()},
        )

    def _mutate(self, circuit: str, action: str, *, redirect: bool) -> None:
        code, text = run_fault(action, circuit)
        parsed = parse_status(text)
        if redirect and DASH_URL and code == 200:
            sep = "&" if "?" in DASH_URL else "?"
            self._redirect(f"{DASH_URL}{sep}var-flash={action}-{circuit}")
            return
        self._json(
            200 if code == 200 else code,
            {
                "ok": code == 200,
                "circuit_id": circuit,
                "admin_state": parsed.get("admin_state") or action,
                "raw": text.strip(),
            },
        )


def main() -> int:
    if not TOKEN:
        print("LAB_FAULT_TOKEN is required", file=sys.stderr)
        return 2
    if not CATALOG.is_file():
        print(f"missing catalog {CATALOG}", file=sys.stderr)
        return 2
    httpd = ThreadingHTTPServer((BIND, PORT), Handler)
    print(f"lab-fault-webhook listening on {BIND}:{PORT}", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
