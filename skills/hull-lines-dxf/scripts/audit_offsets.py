#!/usr/bin/env python3
"""Audit hull-offset data for material anomalies without fitting or drawing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from collections import Counter

import numpy as np

from hull_data import load_bundle


def audit(bundle, spike_ratio, spike_absolute_mm, order_drop_mm):
    findings = []
    missing_by_source = Counter()
    unreadable = 0

    for cell in bundle.inventory:
        status = cell["status"]
        if status == "missing":
            missing_by_source[cell["source"]] += 1
        elif status in {"text", "needs_interpretation"}:
            unreadable += 1
            findings.append(
                {
                    "severity": "review",
                    "type": "unreadable_or_out_of_scale",
                    "source": cell["source"],
                    "station": cell["row"],
                    "column": cell["field"],
                    "raw": cell["raw"],
                    "status": status,
                }
            )

    inversions = []
    for row, values in zip(bundle.rows_effective, bundle.b):
        known = [
            (column, float(value))
            for column, value in zip(bundle.fields, values)
            if np.isfinite(value)
        ]
        for (low_column, low_value), (high_column, high_value) in zip(
            known, known[1:]
        ):
            drop_mm = (low_value - high_value) * 1000.0
            if drop_mm >= order_drop_mm:
                inversions.append(
                    {
                        "station": row["station"],
                        "lower_waterline": low_column,
                        "upper_waterline": high_column,
                        "lower_mm": round(low_value * 1000.0, 3),
                        "upper_mm": round(high_value * 1000.0, 3),
                        "drop_mm": round(drop_mm, 3),
                    }
                )

    spikes = []
    for index in range(1, len(bundle.stations) - 1):
        for column_index, column in enumerate(bundle.fields):
            previous = bundle.b[index - 1, column_index]
            value = bundle.b[index, column_index]
            following = bundle.b[index + 1, column_index]
            if not (
                np.isfinite(previous)
                and np.isfinite(value)
                and np.isfinite(following)
            ):
                continue
            expected = (previous + following) / 2.0
            difference_mm = abs(value - expected) * 1000.0
            relative = abs(value - expected) / max(abs(expected), 1e-12)
            if (
                difference_mm >= spike_absolute_mm
                and relative >= spike_ratio
            ):
                spikes.append(
                    {
                        "station": f"{bundle.stations[index]:g}",
                        "column": column,
                        "value_mm": round(value * 1000.0, 3),
                        "neighbor_mean_mm": round(expected * 1000.0, 3),
                        "absolute_difference_mm": round(difference_mm, 3),
                        "relative_difference": round(relative, 4),
                    }
                )

    for finding in inversions:
        findings.append(
            {"severity": "review", "type": "waterline_order_inversion", **finding}
        )
    for finding in spikes:
        findings.append(
            {"severity": "review", "type": "longitudinal_spike", **finding}
        )
    return {
        "status": "user_confirmation_required" if findings else "clear",
        "drawing_allowed": not findings,
        "main_missing_cells": missing_by_source["half"],
        "missing_by_source": dict(sorted(missing_by_source.items())),
        "unreadable_or_out_of_scale_cells": unreadable,
        "waterline_order_inversions": inversions,
        "longitudinal_spikes": spikes,
        "findings": findings,
        "thresholds": {
            "spike_ratio": spike_ratio,
            "spike_absolute_mm": spike_absolute_mm,
            "order_drop_mm": order_drop_mm,
        },
        "recommended_next_step": (
            "Pause and ask the user whether the findings are source errors, OCR "
            "errors, intended multivalued geometry, or values to replace. Only an "
            "explicit fitting authorisation permits a refit."
            if findings
            else "No material anomaly was detected by these checks; continue with "
            "the requested drawing scope while retaining ordinary REVIEW items."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--profile-csv", type=Path)
    parser.add_argument("--deck-csv", type=Path)
    parser.add_argument("--transom-json", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--spike-ratio", type=float, default=0.35)
    parser.add_argument("--spike-absolute-mm", type=float, default=500.0)
    parser.add_argument("--order-drop-mm", type=float, default=100.0)
    args = parser.parse_args(argv)
    if args.spike_ratio < 0 or args.spike_absolute_mm < 0 or args.order_drop_mm < 0:
        parser.error("audit thresholds must be nonnegative")

    bundle = load_bundle(
        args.csv,
        args.config,
        profile_csv=args.profile_csv,
        deck_csv=args.deck_csv,
        transom_json=args.transom_json,
    )
    report = {
        "input": str(args.csv.resolve()),
        **audit(
            bundle,
            args.spike_ratio,
            args.spike_absolute_mm,
            args.order_drop_mm,
        ),
    }
    output = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if report["status"] == "clear" else 2


if __name__ == "__main__":
    raise SystemExit(main())
