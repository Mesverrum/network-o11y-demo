#!/usr/bin/env python3
"""Minimal Loki push API sink — appends streams to JSONL for Alloy syslog tests."""
from __future__ import annotations

import json
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

OUT = Path(sys.argv[1] if len(sys.argv) > 1 else "/tmp/alloy-syslog-capture.jsonl")
OUT.parent.mkdir(parents=True, exist_ok=True)
OUT.write_text("", encoding="utf-8")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt: str, *args) -> None:  # quieter
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except Exception as e:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(str(e).encode())
            return
        with OUT.open("a", encoding="utf-8") as f:
            for stream in payload.get("streams") or []:
                labels = stream.get("stream") or {}
                for ts, line in stream.get("values") or []:
                    rec = {"labels": labels, "ts": ts, "line": line}
                    f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    print("CAPTURE", labels.get("mode"), "|", line[:160], flush=True)
        self.send_response(204)
        self.end_headers()

    def do_GET(self) -> None:
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"ok")


if __name__ == "__main__":
    port = int(sys.argv[2]) if len(sys.argv) > 2 else 3100
    print(f"loki-sink listening :{port} → {OUT}", flush=True)
    HTTPServer(("0.0.0.0", port), Handler).serve_forever()
