#!/usr/bin/env python3
"""Mirror portable dashboard skills from network-o11y-demo to KtransToGrafana.

Dashboard JSON is authored in KtransToGrafana only — this script copies skills docs.

Usage:
  python3 local/scripts/mirror-skills-to-upstream.py
  python3 local/scripts/mirror-skills-to-upstream.py --upstream /path/to/KtransToGrafana
"""
from __future__ import annotations

import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
DEFAULT_UPSTREAM = REPO.parent / "KtransToGrafana"

SKILL_MAP = {
    "grafana-network-dashboard-design-patterns.md": "network_dashboard_design.md",
    "grafana-network-dashboard-expand-hardware.md": "network_dashboard_new_hardware.md",
    "grafana-network-dashboard-skills-README.md": "README.md",
}


def adapt_skill_readme(text: str) -> str:
    return (
        text.replace(
            "[`grafana-network-dashboard-design-patterns.md`](grafana-network-dashboard-design-patterns.md)",
            "[Design Patterns](network_dashboard_design.md)",
        )
        .replace(
            "[`grafana-network-dashboard-expand-hardware.md`](grafana-network-dashboard-expand-hardware.md)",
            "[Expanding for New Hardware](network_dashboard_new_hardware.md)",
        )
        .replace(
            "[Design Patterns](grafana-network-dashboard-design-patterns.md)",
            "[Design Patterns](network_dashboard_design.md)",
        )
        .replace(
            "[Expanding for New Hardware](grafana-network-dashboard-expand-hardware.md)",
            "[Expanding for New Hardware](network_dashboard_new_hardware.md)",
        )
        .replace(
            "[Skills README](grafana-network-dashboard-skills-README.md)",
            "[Skills README](README.md)",
        )
        .replace(
            "See also: [`grafana-dashboard-playbook.md`](grafana-dashboard-playbook.md)",
            "See also: [docs/grafana.md](../docs/grafana.md)",
        )
        .replace(
            "## network-o11y-demo lab (optional)\n\nThis repo's local lab uses the same skills with extra helpers under `local/`:\n\n- Live dashboard pulls: `make -C local dash-live-sync`\n- Playbook: `docs/grafana-dashboard-playbook.md`\n- Lab-specific probes under `local/scripts/`\n",
            "## network-o11y-demo lab (optional)\n\nLab helpers: drift check `make -C local dash-live-sync`, push `make -C local dash-push`, playbook `docs/grafana-dashboard-playbook.md`.\n",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Mirror skills docs to KtransToGrafana")
    parser.add_argument(
        "--upstream",
        type=Path,
        default=DEFAULT_UPSTREAM,
        help=f"KtransToGrafana repo path (default: {DEFAULT_UPSTREAM})",
    )
    args = parser.parse_args()
    upstream: Path = args.upstream
    if not upstream.is_dir():
        raise SystemExit(f"upstream repo not found: {upstream}")

    skills_dir = upstream / "skills"
    skills_dir.mkdir(parents=True, exist_ok=True)

    for src_name, dest_name in SKILL_MAP.items():
        src = REPO / "docs" / src_name
        if not src.is_file():
            raise SystemExit(f"missing skill doc: {src}")
        text = src.read_text(encoding="utf-8")
        if dest_name == "README.md":
            text = adapt_skill_readme(text)
        for s, d in SKILL_MAP.items():
            if s != dest_name:
                text = text.replace(s, d)
        (skills_dir / dest_name).write_text(text, encoding="utf-8")
        print(f"skill: {dest_name}")

    print(f"\nMirrored {len(SKILL_MAP)} skills to {upstream}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
