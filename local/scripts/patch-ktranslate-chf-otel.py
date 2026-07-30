#!/usr/bin/env python3
"""Apply CHF/otel patches to a ktranslate checkout (local dev image only).

Upstream: Mesverrum/ktranslate branch fix/otel-chf-flow-only
Open PR: https://github.com/kentik/ktranslate/compare/main...Mesverrum:ktranslate:fix/otel-chf-flow-only
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

PATCH_FORMATTER_REUSE_OLD = """\t// If we're sending self metrics via a chan to sinks. This one always get sent via nrm.
\tif kc.metricsChan != nil {
\t\t// Set up formatter
\t\tformat := formats.Format(formats.FORMAT_NRM)
\t\tif kc.config.FormatMetric != "" {
\t\t\tformat = formats.Format(kc.config.FormatMetric)
\t\t}

\t\tfmtr, err := formats.NewFormat(ctx, format, kc.log.GetLogger().GetUnderlyingLogger(), kc.registry, compression, kc.config, kc.logTee)
\t\tif err != nil {
\t\t\treturn err
\t\t}
\t\tgo kc.monitorMetricsInput(ctx, fmtr.To)
\t}"""

PATCH_FORMATTER_REUSE_NEW = """\t// If we're sending self metrics via a chan to sinks.
\tif kc.metricsChan != nil {
\t\tmetricFormat := formats.Format(formats.FORMAT_NRM)
\t\tif kc.config.FormatMetric != "" {
\t\t\tmetricFormat = formats.Format(kc.config.FormatMetric)
\t\t}

\t\tvar metricsFmtr formats.Formatter
\t\tif metricFormat == format {
\t\t\t// Reuse the main formatter when metric export uses the same encoding.
\t\t\t// A second otel formatter would replace the global MeterProvider and
\t\t\t// drop internal (jchf) metrics on flow-only receivers.
\t\t\tmetricsFmtr = kc.format
\t\t} else {
\t\t\tmf, err := formats.NewFormat(ctx, metricFormat, kc.log.GetLogger().GetUnderlyingLogger(), kc.registry, compression, kc.config, kc.logTee)
\t\t\tif err != nil {
\t\t\t\treturn err
\t\t\t}
\t\t\tmetricsFmtr = mf
\t\t}
\t\tgo kc.monitorMetricsInput(ctx, metricsFmtr.To)
\t}"""

PATCH_ROLLUP_BYPASS_OLD = """\t\tcase msgs := <-kc.metricsChan:
\t\t\tkc.handleInput(ctx, msgs, serBuf, nil, seri)"""

# Intermediate patch (single seri call) — upgrade to batched form.
PATCH_ROLLUP_BYPASS_SIMPLE_OLD = """\t\tcase msgs := <-kc.metricsChan:
\t\t\t// Internal jchf health metrics must not pass through rollup accumulation.
\t\t\tser, err := seri(msgs, serBuf)
\t\t\tif err != nil {
\t\t\t\tkc.log.Errorf("There was an error when converting metrics: %v.", err)
\t\t\t} else if ser != nil {
\t\t\t\tkc.msgsc <- ser
\t\t\t}"""

PATCH_ROLLUP_BYPASS_NEW = """\t\tcase msgs := <-kc.metricsChan:
\t\t\t// Internal jchf health metrics must not pass through rollup accumulation.
\t\t\t// Still honor MaxFlowsPerMessage batching (same loop as handleInput export).
\t\t\tkeep := len(msgs)
\t\t\tlast := 0
\t\t\tfor next := kc.config.MaxFlowsPerMessage; next < keep+kc.config.MaxFlowsPerMessage; next += kc.config.MaxFlowsPerMessage {
\t\t\t\tbatch := next
\t\t\t\tif batch > keep {
\t\t\t\t\tbatch = keep
\t\t\t\t}
\t\t\t\tser, err := seri(msgs[last:batch], serBuf)
\t\t\t\tif err != nil {
\t\t\t\t\tkc.log.Errorf("There was an error when converting metrics: %v.", err)
\t\t\t\t} else if ser != nil {
\t\t\t\t\tkc.msgsc <- ser
\t\t\t\t}
\t\t\t\tlast = next
\t\t\t\tif batch == keep {
\t\t\t\t\tbreak
\t\t\t\t}
\t\t\t}"""


PATCHED_MARKER = "exportJchfBatches"


def is_patched(text: str) -> bool:
    return PATCHED_MARKER in text or PATCH_ROLLUP_BYPASS_NEW in text


def apply_patch(text: str, name: str, old: str, new: str) -> tuple[str, bool]:
    if new in text:
        print(f"already patched ({name})")
        return text, False
    if old not in text:
        print(f"patch target not found ({name})", file=sys.stderr)
        return text, False
    print(f"patched ({name})")
    return text.replace(old, new, 1), True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "repo",
        nargs="?",
        default="/tmp/ktranslate",
        help="Path to ktranslate checkout (default: /tmp/ktranslate)",
    )
    args = parser.parse_args()
    path = Path(args.repo) / "pkg" / "cat" / "kkc.go"
    text = path.read_text(encoding="utf-8")
    changed = False

    text, c = apply_patch(text, "formatter-reuse", PATCH_FORMATTER_REUSE_OLD, PATCH_FORMATTER_REUSE_NEW)
    changed = changed or c
    text, c = apply_patch(text, "rollup-bypass", PATCH_ROLLUP_BYPASS_OLD, PATCH_ROLLUP_BYPASS_NEW)
    changed = changed or c
    text, c = apply_patch(text, "rollup-bypass-batched", PATCH_ROLLUP_BYPASS_SIMPLE_OLD, PATCH_ROLLUP_BYPASS_NEW)
    changed = changed or c

    if not changed and not is_patched(path.read_text(encoding="utf-8")):
        return 1
    if changed:
        path.write_text(text, encoding="utf-8")
        print(f"wrote {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
