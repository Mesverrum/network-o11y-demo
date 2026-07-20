#!/usr/bin/env python3
"""Find Commvault-specific strings in ktranslate dashboard exports."""
from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / ".dash-payloads" / "ktranslate-import"
FILES = ["mavgvqv.json", "magz6qw1.json", "be8hpir89dds0a.json", "masjqrs.json"]
PATS = [
    r"commvault",
    r"netgraff",
    r"CV-[A-Za-z0-9_-]+",
    r"CVNJ",
    r"CVIN",
    r"CVBANG",
    r"COEProd",
    r"BLRCOE",
    r"N9K-",
    r"G8332",
    r"CV-TF",
    r"India",
    r"TF / NJ",
]


def main() -> None:
    for name in FILES:
        path = ROOT / name
        if not path.exists():
            print(f"missing {path}")
            continue
        text = path.read_text(encoding="utf-8")
        print("=" * 60, name)
        seen = set()
        for pat in PATS:
            for m in re.finditer(pat, text, re.I):
                start = max(0, m.start() - 50)
                end = min(len(text), m.end() + 90)
                snippet = text[start:end].replace("\n", " ")
                key = (pat, snippet)
                if key in seen:
                    continue
                seen.add(key)
                print(f"  [{pat}] {snippet!r}")


if __name__ == "__main__":
    main()
