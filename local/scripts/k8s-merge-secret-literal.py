#!/usr/bin/env python3
"""Merge one stringData key into an existing Kubernetes Secret (no full replace)."""
from __future__ import annotations

import argparse
import os
import subprocess
import sys


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("-n", "--namespace", required=True)
    p.add_argument("secret")
    p.add_argument("key")
    p.add_argument(
        "--env",
        default="",
        help="Read value from this environment variable (default: same as key)",
    )
    args = p.parse_args()
    env_name = args.env or args.key
    value = os.environ.get(env_name)
    if value is None:
        print(f"ERROR: ${env_name} is not set", file=sys.stderr)
        return 1
    patch = '{"stringData":{"%s":%s}}' % (
        args.key,
        _json_str(value),
    )
    subprocess.run(
        [
            "kubectl",
            "-n",
            args.namespace,
            "patch",
            "secret",
            args.secret,
            "--type=merge",
            "-p",
            patch,
        ],
        check=True,
    )
    return 0


def _json_str(s: str) -> str:
    import json

    return json.dumps(s)


if __name__ == "__main__":
    raise SystemExit(main())
