#!/usr/bin/env python3
"""Check projected waterlines for inversions and intersections."""

from __future__ import annotations

import argparse
import itertools
import json
from pathlib import Path

import ezdxf
import numpy as np


def waterline_curves(document, samples):
    curves = []
    for entity in document.modelspace().query("SPLINE"):
        try:
            metadata = json.loads(
                "".join(
                    item.value
                    for item in entity.get_xdata("HULLCURVE")
                    if item.code == 1000
                )
            )
        except (ValueError, ezdxf.DXFError):
            continue
        if metadata.get("view") != "waterline" or metadata.get("kind") != "WL":
            continue
        points = np.asarray(
            [tuple(item)[:2] for item in entity.construction_tool().approximate(samples)],
            dtype=float,
        )
        if not len(points):
            continue
        side = metadata.get("side")
        if side is None:
            side = 1 if float(np.mean(points[:, 1])) >= 0 else -1
        curves.append(
            {
                "number": float(metadata["number"]),
                "layer": entity.dxf.layer,
                "side": int(side),
                "points": points,
            }
        )
    return curves


def compare(curves, grid_samples):
    results = []
    minimum_separation = float("inf")
    for side in sorted({curve["side"] for curve in curves}):
        side_curves = sorted(
            (curve for curve in curves if curve["side"] == side),
            key=lambda curve: curve["number"],
        )
        for low, high in itertools.combinations(side_curves, 2):
            low_points = low["points"]
            high_points = high["points"]
            start = max(low_points[:, 0].min(), high_points[:, 0].min())
            end = min(low_points[:, 0].max(), high_points[:, 0].max())
            if start >= end:
                continue
            x_values = np.linspace(start, end, grid_samples)

            def interpolate(points):
                order = np.argsort(points[:, 0])
                return np.abs(
                    np.interp(
                        x_values, points[order, 0], points[order, 1]
                    )
                )

            difference = interpolate(high_points) - interpolate(low_points)
            minimum_separation = min(
                minimum_separation, float(difference.min())
            )
            negative = np.flatnonzero(difference < -1e-6)
            regions = []
            if len(negative):
                groups = np.split(
                    negative, np.flatnonzero(np.diff(negative) > 1) + 1
                )
                regions = [
                    {
                        "x_start": float(x_values[group[0]]),
                        "x_end": float(x_values[group[-1]]),
                        "minimum_m": float(difference[group].min()),
                    }
                    for group in groups
                    if len(group) > 1
                ]
            if regions:
                results.append(
                    {
                        "side": side,
                        "low": low["layer"],
                        "high": high["layer"],
                        "regions": regions,
                    }
                )
    return results, (
        minimum_separation if minimum_separation < float("inf") else None
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--samples", type=int, default=2000)
    parser.add_argument("--grid-samples", type=int, default=5000)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args(argv)
    if args.samples < 100 or args.grid_samples < 100:
        parser.error("sample counts must be at least 100")

    document = ezdxf.readfile(args.input)
    curves = waterline_curves(document, args.samples)
    intersections, minimum_separation = compare(curves, args.grid_samples)
    report = {
        "input": str(args.input.resolve()),
        "waterlines": len(curves),
        "curve_samples": args.samples,
        "grid_samples": args.grid_samples,
        "minimum_high_minus_low_m": minimum_separation,
        "intersections": intersections,
        "status": "passed" if not intersections else "review",
        "native_CAD_check": "not performed",
    }
    output = json.dumps(report, indent=2, ensure_ascii=False)
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(output + "\n", encoding="utf-8")
    print(output)
    return 0 if not intersections else 1


if __name__ == "__main__":
    raise SystemExit(main())
