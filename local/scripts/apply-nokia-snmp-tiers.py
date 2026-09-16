#!/usr/bin/env python3
"""Apply Nokia SNMP tier split into snmp-network.yml + fingerprinters.yml.

Policy (matches Mesverrum/snmp-sd):
  hot      — if_mib + nokia_srlinux (identity + CPU/mem)
  cold     — if_mib_meta + ip_addr + nokia_srlinux_sensors
  topology — nokia_srlinux_topo + lldp_mib (opt-in via LAB_ALLOY_SNMP_TIERS / tiers=)
  Prefer tools/snmp-profile-convert/split_nokia_tiers.py in snmp-sd.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError as exc:  # pragma: no cover
    raise SystemExit("PyYAML required: pip install pyyaml") from exc

NOKIA_HOT_BLOCK = """      modules_hot: &id253
      - if_mib
      - nokia_srlinux
      modules_cold: &id254
      - if_mib_meta
      - ip_addr
      - nokia_srlinux_sensors
      modules_topology: &id255
      - nokia_srlinux_topo
      - lldp_mib"""

NOKIA_HOT_BLOCK_OLD_VARIANTS = (
    """      modules_hot: &id253
      - if_mib
      - nokia_srlinux_hot
      - nokia_srlinux
      modules_cold: &id254
      - if_mib_meta
      modules_topology: &id255 []""",
    """      modules_hot: &id253
      - if_mib
      - system_mib
      - nokia_srlinux_hot
      - nokia_srlinux
      modules_cold: &id254
      - if_mib_meta
      modules_topology: &id255 []""",
    """      modules_hot: &id253
      - if_mib
      modules_cold: &id254
      - system_mib
      - if_mib_meta
      - nokia_srlinux
      modules_topology: &id255 []""",
    """      modules_hot: &id253
      - if_mib
      - nokia_srlinux_hot
      modules_cold: &id254
      - system_mib
      - if_mib_meta
      - nokia_srlinux
      modules_topology: &id255 []""",
    """      modules_hot: &id253
      - if_mib
      - nokia_srlinux_hot
      - nokia_srlinux
      modules_cold: &id254
      - system_mib
      - if_mib_meta
      - nokia_srlinux_bgp
      modules_topology: &id255 []""",
    """      modules_hot: &id253
      - if_mib
      - nokia_srlinux_hot
      - nokia_srlinux
      modules_cold: &id254
      - system_mib
      - if_mib_meta
      modules_topology: &id255 []""",
)


def _load_module_file(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    mods = data.get("modules") or {}
    if not isinstance(mods, dict) or not mods:
        raise SystemExit(f"no modules in {path}")
    return mods


def patch_snmp_network(snmp_path: Path, module_files: list[Path]) -> None:
    doc = yaml.safe_load(snmp_path.read_text(encoding="utf-8")) or {}
    modules = doc.setdefault("modules", {})
    if not isinstance(modules, dict):
        raise SystemExit(f"{snmp_path}: modules is not a mapping")
    for src in module_files:
        incoming = _load_module_file(src)
        for name, body in incoming.items():
            modules[name] = body
            print(f"==> snmp-network.yml module {name} from {src.name}")
    # Dumping 2MB YAML loses aliases but snmp_exporter does not need them.
    snmp_path.write_text(
        yaml.safe_dump(doc, sort_keys=False, default_flow_style=False),
        encoding="utf-8",
    )


def patch_fingerprinters(fp_path: Path) -> None:
    text = fp_path.read_text(encoding="utf-8")
    if NOKIA_HOT_BLOCK in text or (
        "      - nokia_srlinux_topo\n      - lldp_mib" in text
    ):
        print(f"==> fingerprinters.yml already at current Nokia split ({fp_path})")
        return
    # Converter emit uses different YAML anchors; cold already has ip_addr.
    if (
        "      - nokia_srlinux_hot\n      modules_cold:" in text
        and "      - if_mib_meta\n      - ip_addr\n      modules_topology:" in text
    ):
        print(f"==> fingerprinters.yml Nokia cold already includes ip_addr ({fp_path})")
        return
    replaced = False
    for old in NOKIA_HOT_BLOCK_OLD_VARIANTS:
        if old in text:
            text = text.replace(old, NOKIA_HOT_BLOCK, 1)
            replaced = True
            break
    if not replaced:
        raise SystemExit(f"{fp_path}: Nokia &id253 block not found")
    fp_path.write_text(text, encoding="utf-8")
    print(f"==> patched Nokia modules_hot/cold in {fp_path}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="local/ directory",
    )
    ap.add_argument(
        "--skip-snmp-network",
        action="store_true",
        help="Only patch fingerprinters (targets). Skip rewriting the 2MB library.",
    )
    args = ap.parse_args()
    root: Path = args.root
    fixtures = root / "fixtures" / "alloy-snmp" / "modules" / "nokia"
    snmp_path = root / "alloy" / "snmp-network.yml"
    fp_path = root / "alloy" / "fingerprinters.yml"
    if not fp_path.exists():
        fp_path = root / "fixtures" / "alloy-snmp" / "fingerprinters.yml"

    if not args.skip_snmp_network:
        module_files = [
            fixtures / "nokia_srlinux.yml",
            fixtures / "nokia_srlinux_sensors.yml",
            fixtures / "nokia_srlinux_topo.yml",
        ]
        for p in module_files:
            if not p.exists():
                raise SystemExit(f"missing {p}")
        if not snmp_path.exists() or snmp_path.stat().st_size < 10_000:
            raise SystemExit(
                f"{snmp_path} missing or tiny — extract /etc/alloy/snmp-network.yml from the image first"
            )
        patch_snmp_network(snmp_path, module_files)

    patch_fingerprinters(fp_path)
    # Keep fixture copy in sync when we patched alloy/fingerprinters.yml
    fixture_fp = root / "fixtures" / "alloy-snmp" / "fingerprinters.yml"
    if fp_path.resolve() != fixture_fp.resolve() and fixture_fp.exists():
        try:
            patch_fingerprinters(fixture_fp)
        except SystemExit as exc:
            print(f"WARN: fixture fingerprinters: {exc}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
