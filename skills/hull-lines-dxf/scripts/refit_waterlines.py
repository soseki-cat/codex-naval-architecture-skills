#!/usr/bin/env python3
"""Refit known half-breadths so projected waterlines do not cross."""

from __future__ import annotations

import argparse
import copy
import csv
import json
from pathlib import Path

from hull_data import load_bundle
from hull_types import read_csv


def monotone(values, gap=0.0):
    """Closest nondecreasing fit under a minimum step, using PAVA."""
    shifted = [value - index * gap for index, value in enumerate(values)]
    blocks = []
    for index, value in enumerate(shifted):
        blocks.append([index, index, 1, value])
        while len(blocks) >= 2 and blocks[-2][3] > blocks[-1][3]:
            right = blocks.pop()
            left = blocks.pop()
            count = left[2] + right[2]
            blocks.append(
                [
                    left[0],
                    right[1],
                    count,
                    (left[3] * left[2] + right[3] * right[2]) / count,
                ]
            )
    fitted = [0.0] * len(values)
    for start, end, _, mean in blocks:
        for index in range(start, end + 1):
            fitted[index] = mean + index * gap
    return fitted


def known_values(row, fields):
    known = []
    for field in fields:
        raw = str(row[field]).strip()
        if raw in {"", "-", "?"}:
            continue
        known.append((field, float(raw)))
    return known


def fit_row(row, fields, minimum_gap_mm):
    known = known_values(row, fields)
    if not known:
        return row, []
    fitted = monotone([value for _, value in known])
    for index in range(1, len(fitted)):
        fitted[index] = max(fitted[index], fitted[index - 1] + minimum_gap_mm)
    changes = []
    result = copy.deepcopy(row)
    for (field, before), value in zip(known, fitted):
        after = str(int(round(value)))
        result[field] = after
        if before != float(after):
            changes.append((field, before, float(after), "monotone"))
    return result, changes


def apply_local_gap(row, fields, station, low, high, gap, changes):
    if not low <= station <= high:
        return row
    known = known_values(row, fields)
    if not known:
        return row
    previous = None
    for field, value in known:
        fitted = value if previous is None else max(value, previous + gap)
        if fitted != value:
            row[field] = str(int(round(fitted)))
            changes.append((field, value, fitted, "local_gap"))
        previous = fitted
    return row


def write_ledger(path, records):
    with path.open("w", encoding="utf-8-sig", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "station",
                "column",
                "original_raw",
                "corrected_mm",
                "delta_mm",
                "status",
                "basis",
            ],
        )
        writer.writeheader()
        writer.writerows(records)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", required=True, type=Path)
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--corrections", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--ledger", type=Path)
    parser.add_argument("--summary", type=Path)
    parser.add_argument(
        "--approve-refit",
        action="store_true",
        help="Confirm that the user authorised the proposed table changes",
    )
    parser.add_argument("--min-gap-mm", type=float, default=20.0)
    parser.add_argument("--local-gap-mm", type=float, default=200.0)
    parser.add_argument("--local-from-station", type=float, default=0.75)
    parser.add_argument("--local-to-station", type=float, default=2.0)
    args = parser.parse_args(argv)

    if args.out.resolve() == args.csv.resolve():
        parser.error("--out must differ from --csv")
    fields, source_rows = read_csv(args.csv)
    source_fields = ["station"] + fields
    bundle = load_bundle(
        args.csv,
        args.config,
        corrections_json=args.corrections,
    )
    effective = copy.deepcopy(bundle.rows_effective)
    fitted_rows = []
    all_changes = []
    reasons_by_cell = {}
    for corrected in effective:
        row, monotone_changes = fit_row(
            copy.deepcopy(corrected), fields, args.min_gap_mm
        )
        local_changes = []
        apply_local_gap(
            row,
            fields,
            float(row["station"]),
            args.local_from_station,
            args.local_to_station,
            args.local_gap_mm,
            local_changes,
        )
        fitted_rows.append(row)
        for field, _, _, reason in monotone_changes + local_changes:
            reasons_by_cell.setdefault((row["station"], field), []).append(reason)
    for source, corrected, final in zip(source_rows, effective, fitted_rows):
        for field in fields:
            original_raw = source[field].strip()
            final_raw = final[field].strip()
            try:
                original_value = float(original_raw)
                final_value = float(final_raw)
                changed = original_value != final_value
                delta = final_value - original_value
            except ValueError:
                changed = original_raw != final_raw
                delta = None
            if not changed:
                continue
            reasons = []
            corrected_raw = corrected[field].strip()
            if corrected_raw != original_raw:
                reasons.append("authorized source correction")
            if corrected_raw != final_raw:
                reasons.extend(
                    reasons_by_cell.get((source["station"], field), [])
                )
            all_changes.append(
                {
                    "station": source["station"],
                    "column": field,
                    "original_raw": original_raw,
                    "corrected_mm": final_raw,
                    "delta_mm": f"{delta:.0f}" if delta is not None else "",
                    "status": "ESTIMATED",
                    "basis": "; ".join(dict.fromkeys(reasons))
                    or "non-crossing refit",
                }
            )

    residual_violations = 0
    for row in fitted_rows:
        known = [value for _, value in known_values(row, fields)]
        residual_violations += sum(
            right < left for left, right in zip(known, known[1:])
        )
    approval_required = bool(all_changes) and not args.approve_refit
    summary = {
        "source": str(args.csv.resolve()),
        "output": str(args.out.resolve()),
        "source_corrections": len(bundle.correction_report["targets"]),
        "changed_cells": len(all_changes),
        "approval_required": approval_required,
        "approved": bool(args.approve_refit),
        "residual_row_order_violations": residual_violations,
        "minimum_gap_mm": args.min_gap_mm,
        "local_stern_gap_mm": args.local_gap_mm,
        "local_station_range": [
            args.local_from_station,
            args.local_to_station,
        ],
        "status": (
            "blocked"
            if residual_violations
            else "user_confirmation_required"
            if approval_required
            else "ok"
        ),
    }
    if args.ledger:
        write_ledger(args.ledger, all_changes)
    if args.summary:
        args.summary.parent.mkdir(parents=True, exist_ok=True)
        args.summary.write_text(
            json.dumps(summary, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    if residual_violations or approval_required:
        print(json.dumps(summary, indent=2, ensure_ascii=False))
        return 2

    args.out.parent.mkdir(parents=True, exist_ok=True)
    with args.out.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=source_fields)
        writer.writeheader()
        writer.writerows(fitted_rows)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
