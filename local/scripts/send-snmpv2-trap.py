#!/usr/bin/env python3
"""Send a minimal SNMPv2c trap (coldStart or named OID) over UDP. No net-snmp."""
from __future__ import annotations

import argparse
import socket
import time


def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    body = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(body)]) + body


def _tlv(tag: int, value: bytes) -> bytes:
    return bytes([tag]) + _len(len(value)) + value


def _int(n: int) -> bytes:
    if n == 0:
        raw = b"\x00"
    else:
        length = (n.bit_length() + 8) // 8
        raw = n.to_bytes(length, "big", signed=True)
        if raw[0] & 0x80:
            raw = b"\x00" + raw
    return _tlv(0x02, raw)


def _oid(oid: str) -> bytes:
    parts = [int(p) for p in oid.strip(".").split(".") if p]
    if len(parts) < 2:
        raise ValueError(f"bad oid {oid}")
    out = bytes([40 * parts[0] + parts[1]])
    for p in parts[2:]:
        if p < 0:
            raise ValueError(f"bad oid arc {p}")
        stack = [p & 0x7F]
        p >>= 7
        while p:
            stack.append(0x80 | (p & 0x7F))
            p >>= 7
        out += bytes(reversed(stack))
    return _tlv(0x06, out)


def _octets(s: bytes) -> bytes:
    return _tlv(0x04, s)


def _null() -> bytes:
    return _tlv(0x05, b"")


def _timeticks(n: int) -> bytes:
    return _tlv(0x43, n.to_bytes(max(1, (n.bit_length() + 7) // 8), "big"))


def _varbind(oid: str, value: bytes) -> bytes:
    return _tlv(0x30, _oid(oid) + value)


def encode_v2c_trap(community: str, trap_oid: str, sys_uptime: int = 1) -> bytes:
    vb = _tlv(
        0x30,
        _varbind("1.3.6.1.2.1.1.3.0", _timeticks(sys_uptime))
        + _varbind("1.3.6.1.6.3.1.1.4.1.0", _oid(trap_oid)),
    )
    pdu = _tlv(0xA7, _int(int(time.time()) & 0x7FFFFFFF) + _int(0) + _int(0) + vb)
    body = _int(1) + _octets(community.encode()) + pdu
    return _tlv(0x30, body)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("host")
    ap.add_argument("port", type=int)
    ap.add_argument("--community", default="public")
    ap.add_argument("--oid", default="1.3.6.1.6.3.1.1.5.1", help="trap OID (default coldStart)")
    args = ap.parse_args()
    pkt = encode_v2c_trap(args.community, args.oid)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.sendto(pkt, (args.host, args.port))
    finally:
        sock.close()
    print(f"sent {args.oid} → {args.host}:{args.port} ({len(pkt)} bytes)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
