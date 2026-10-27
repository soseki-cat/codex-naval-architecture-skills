"""Generate source-preserving hull lines from a half-breadth matrix.

See ../references/input-and-output.md for the CSV/JSON contract.
Requires ezdxf, numpy and scipy; matplotlib is needed only for --preview.
"""
from __future__ import annotations
import argparse
import csv
import json
from pathlib import Path
import shutil
import sys

import ezdxf
from ezdxf import zoom
from ezdxf.math import Matrix44
import numpy as np
from scipy.interpolate import PchipInterpolator
from scipy.optimize import brentq

from hull_writer import Writer, control_points, load_data


def runs(values):
    groups, group = [], []
    for i, v in enumerate(values):
        if np.isfinite(v):
            group.append(i)
        elif group:
            groups.append(group)
            group = []
    if group:
        groups.append(group)
    return groups


def label(v):
    return f"{v:g}".replace("-", "m").replace(".", "p")


def source_curves(writer, t, values, mapper, name, color):
    for group in runs(values):
        if len(group) >= 2:
            writer.curve(t[group], values[group], mapper, name, color)


def buttocks(x, z, b, levels):
    output, anchors, domains = [], [], {}
    status = "not requested" if not levels else "generated"
    if not levels:
        return output, anchors, domains, status, 0.0
    if np.isnan(b).any():
        return output, anchors, domains, "not generated: missing cells prevent the complete-grid interpolator", 0.0
    wls = [PchipInterpolator(x, b[:, j]) for j in range(len(z))]
    # Examine every cubic difference at its extrema, including arbitrarily short station intervals.
    for lower, upper in zip(wls[:-1], wls[1:]):
        for i, h in enumerate(np.diff(x)):
            d = upper.c[:, i] - lower.c[:, i]
            q = d * np.array([h ** 3, h ** 2, h, 1.0])
            critical = np.roots([3 * q[0], 2 * q[1], q[2]])
            candidates = [0.0, 1.0] + [float(r.real) for r in critical
                                         if abs(r.imag) < 1e-12 and 0 < r.real < 1]
            if min(float(np.polyval(q, t)) for t in candidates) < -1e-10:
                return output, anchors, domains, "not generated: interpolated waterlines cross; a different surface model is required", 0.0
    for bp in levels:
        overlap = np.isclose(b[:, :-1], bp, atol=1e-10, rtol=0) & np.isclose(b[:, 1:], bp, atol=1e-10, rtol=0)
        if np.any(overlap):
            raise ValueError(f"BP={bp:g} m coincides with a finite source height span; a single-valued buttock inverse is not valid")

    def height(xx, target):
        vals = np.array([wl(xx) for wl in wls])
        if abs(vals[0] - target) < 1e-10:
            return z[0]
        if abs(vals[-1] - target) < 1e-10:
            return z[-1]
        if not vals[0] <= target <= vals[-1]:
            raise ValueError("Buttock sample outside supplied offset domain")
        f = PchipInterpolator(z, vals)
        return brentq(lambda zz: float(f(zz)) - target, z[0], z[-1], xtol=1e-12)

    def breadth(xx, zz):
        return float(PchipInterpolator(z, [wl(xx) for wl in wls])(zz))

    def roots(wl, target):
        found = []
        for a, c in zip(x[:-1], x[1:]):
            fa, fc = float(wl(a)) - target, float(wl(c)) - target
            if abs(fa) < 1e-12:
                found.append(float(a))
            if fa * fc < 0:
                found.append(brentq(lambda xx: float(wl(xx)) - target, a, c, xtol=1e-12))
            if abs(fc) < 1e-12:
                found.append(float(c))
        return sorted(set(round(v, 11) for v in found))

    max_residual = 0.0
    for bp in levels:
        bounds = sorted(set([float(x[0]), float(x[-1])] + roots(wls[0], bp) + roots(wls[-1], bp)))
        active = []
        for a, c in zip(bounds[:-1], bounds[1:]):
            mid = (a + c) / 2
            if float(wls[0](mid)) <= bp <= float(wls[-1](mid)):
                if active and abs(active[-1][1] - a) < 1e-9:
                    active[-1] = [active[-1][0], c]
                else:
                    active.append([a, c])
        domains[f"{bp:g}"] = active
        cuts = [(xx, float(zz)) for zz, wl in zip(z, wls) for xx in roots(wl, bp)]
        anchors.extend((bp, xx, zz) for xx, zz in cuts)
        for a, c in active:
            # Grid scales with the data span; adaptive refinement controls physical height error.
            vals = np.linspace(a, c, max(3, int(np.ceil((c - a) / ((x[-1] - x[0]) / 280))) + 1)).tolist()
            vals += [float(xx) for xx in x if a < xx < c]
            vals += [xx for xx, zz in cuts if a < xx < c]
            xx = np.array(sorted(set(vals)))
            for iteration in range(12):
                zz = np.array([height(t, bp) for t in xx])
                fit = PchipInterpolator(xx, zz)
                extra = []
                for lo, hi in zip(xx[:-1], xx[1:]):
                    if hi - lo < 1e-10:
                        continue
                    for portion in [0.25, 0.5, 0.75]:
                        t = lo + (hi - lo) * portion
                        fz = float(fit(t))
                        if abs(fz - height(t, bp)) > 0.00008 or abs(breadth(t, fz) - bp) > 0.00005:
                            extra.append(t)
                if not extra:
                    break
                xx = np.array(sorted(set(xx.tolist() + extra)))
            else:
                raise ValueError("Buttock adaptive fitting did not converge; revise interpolation, not the source offsets")
            for lo, hi in zip(xx[:-1], xx[1:]):
                for portion in [0.13, 0.37, 0.63, 0.87]:
                    t = lo + (hi - lo) * portion
                    val = float(fit(t))
                    error = abs(breadth(t, val) - bp)
                    max_residual = max(max_residual, error)
                    if error > 0.0001 or abs(val - height(t, bp)) > 0.00015:
                        raise AssertionError("Buttock sampled residual exceeds declared tolerance")
            output.append((bp, xx, zz))
    return output, anchors, domains, status, max_residual


def generate(csv_path, config_path, out, skeleton=False, preview=False):
    p, rows, fields, st, x, z, b, physical, x_note, split, origin_x, levels = load_data(csv_path, config_path, skeleton)
    try:
        cuts, anchors, domains, status, residual = buttocks(x, z, b, levels)
    except (ValueError, AssertionError) as error:
        cuts, anchors, domains, residual = [], [], {}, 0.0
        status = f"not generated: {error}"
    out.mkdir(parents=True, exist_ok=True)
    body, plan, long = Writer(), Writer(physical), Writer(physical)
    model = Writer() if skeleton else None
    max_b = float(np.nanmax(b)) if np.isfinite(b).any() else 1.0
    body_size = max(1.0, max_b * 2, float(z[-1] - z[0]))
    long_size = max(1.0, float(x[-1] - x[0]))
    bh, ph = body_size / 55, long_size / 180
    palette = [1, 30, 2, 3, 4, 5, 6, 140, 210, 40, 130, 190, 10]
    mirror = bool(p.get("mirror_3d", False))
    model_sides = [1, -1] if mirror else [1]
    for i, station in enumerate(st):
        color = palette[i % len(palette)]
        name = "ST_" + label(station)
        sides = [-1, 1] if abs(x[i] - split) < 1e-9 else [-1] if x[i] < split else [1]
        for side in sides:
            mapper = lambda zz, bb, side=side: (side * bb, zz, 0)
            source_curves(body, z, b[i], mapper, name, color)
            for j, zz in enumerate(z):
                if np.isfinite(b[i, j]):
                    meta = f"source;station={station:g};z_m={zz:g};raw={rows[i][fields[j]]};side={side}"
                    body.point(mapper(zz, b[i, j]), "SOURCE_" + name, color, meta)
        if model:
            for side in model_sides:
                mapper = lambda zz, bb, side=side, i=i: (x[i] - origin_x, side * bb, zz)
                source_curves(model, z, b[i], mapper, name, color)
                for j, zz in enumerate(z):
                    if np.isfinite(b[i, j]):
                        model.point(mapper(zz, b[i, j]), "SOURCE_POINTS", 8,
                                    f"source;station={station:g};z_m={zz:g};raw={rows[i][fields[j]]};side={side}")
    for j, zz in enumerate(z):
        color = palette[j % len(palette)]
        name = "WL_" + label(zz)
        for side in [1, -1]:
            mapper = lambda xx, bb, side=side: (xx, side * bb, 0)
            source_curves(plan, x, b[:, j], mapper, name, color)
            for i, station in enumerate(st):
                if np.isfinite(b[i, j]):
                    plan.point(mapper(x[i], b[i, j]), "SOURCE_" + name, color,
                               f"source;station={station:g};z_m={zz:g};raw={rows[i][fields[j]]};side={side}")
                    long.point((x[i], zz, 0), "SOURCE_PROJECTED", 8,
                               f"source projection, not a profile;station={station:g};z_m={zz:g};b_m={b[i,j]:g}") if side == 1 else None
        if model:
            for side in model_sides:
                mapper = lambda xx, bb, side=side, zz=zz: (xx - origin_x, side * bb, zz)
                source_curves(model, x, b[:, j], mapper, name, color)
    for bp, xx, zz in cuts:
        color = palette[levels.index(bp) % len(palette)]
        name = "BP_" + label(bp)
        long.curve(xx, zz, lambda tx, tz: (tx, tz, 0), name, color, source=False)
        if model:
            for side in model_sides:
                model.curve(xx, zz, lambda tx, tz, bp=bp, side=side: (tx - origin_x, side * bp, tz),
                            name, color, source=False)
    for bp, xx, zz in anchors:
        color = palette[levels.index(bp) % len(palette)]
        long.point((xx, zz, 0), "DERIVED_BP_" + label(bp), color, f"derived;bp_m={bp:g};z_m={zz:g}")
    for yy in z:
        body.line((-max_b * 1.1, yy, 0), (max_b * 1.1, yy, 0))
        long.line((x[0], yy, 0), (x[-1], yy, 0))
    body.line((0, z[0], 0), (0, z[-1], 0))
    for xx, station in zip(x, st):
        plan.line((xx, -max_b * 1.1, 0), (xx, max_b * 1.1, 0))
        long.line((xx, z[0], 0), (xx, z[-1], 0))
        plan.text(f"{station:g}", (xx, -max_b * 1.1 - ph * 2, 0), ph)
        long.text(f"{station:g}", (xx, z[0] - ph * 2, 0), ph)
    body.text("BODY PLAN | aft left, fore right", (-max_b, z[-1] + bh * 4, 0), bh * 1.5)
    body.text("Breadth/height in m; baseline origin is not a forced hull endpoint.", (-max_b, z[0] - bh * 4, 0), bh)
    plan.text("WATERLINE PLAN", (x[0], max_b * 1.1 + ph * 4, 0), ph * 1.5)
    plan.text(x_note, (x[0], max_b * 1.1 + ph * 2, 0), ph)
    long.text("LONGITUDINAL SECTIONS | computed fixed-breadth cuts", (x[0], z[-1] + ph * 4, 0), ph * 1.5)
    long.text(x_note, (x[0], z[-1] + ph * 2, 0), ph)
    long.text("Known offset domain only. Reference grid is not a complete keel/deck profile.", (x[0], z[0] - ph * 4, 0), ph)
    if status != "generated":
        long.text(status, (x[0], z[0] - ph * 6, 0), ph)
    writers = [("body_plan.dxf", body), ("waterline_plan.dxf", plan), ("longitudinal_sections.dxf", long)]
    if model:
        writers.append(("hull_skeleton_3d.dxf", model))
    reports = {name: writer.save_checked(out / name) for name, writer in writers}
    combined = Writer(physical)
    for writer, delta, prefix in [(plan, (0, 0, 0), "PLAN_"),
                                   (body, (x[0] + max_b * 1.2, max_b * 1.3 + body_size * 0.6, 0), "BODY_"),
                                   (long, (0, max_b * 1.3 + body_size * 0.6 + z[-1] - z[0] + body_size * 0.7, 0), "LONG_")]:
        for lay in writer.doc.layers:
            combined.layer(prefix + lay.dxf.name, lay.dxf.color)
        curve_checks = {v[0]: v[1:] for v in writer.curve_checks}
        point_checks = {v[0]: v[1:] for v in writer.point_checks}
        for ent in writer.ms:
            copied = ent.copy()
            copied.dxf.layer = prefix + copied.dxf.layer
            copied.transform(Matrix44.translate(*delta))
            combined.ms.add_entity(copied)
            if ent.dxf.handle in curve_checks:
                tt, expected, source = curve_checks[ent.dxf.handle]
                combined.curve_checks.append((copied.dxf.handle, tt, expected + np.array(delta), source))
            if ent.dxf.handle in point_checks:
                xyz, metadata = point_checks[ent.dxf.handle]
                combined.point_checks.append((copied.dxf.handle, xyz + np.array(delta), metadata))
    reports["three_views_combined.dxf"] = combined.save_checked(out / "three_views_combined.dxf")
    report = {"files": reports, "source_point_count": int(np.isfinite(b).sum()),
              "missing_cell_count": int(np.isnan(b).sum()), "station_numbers": st.tolist(),
              "station_x": x.tolist(), "x_mode": "physical_m" if physical else "station_number",
              "x_mapping": x_note, "waterline_heights_m": z.tolist(),
              "half_breadth_to_m": p["half_breadth_to_m"],
              "unit_evidence": p.get("unit_evidence", "conversion supplied in config; no independent unit claim"),
              "source_spline_point_error": max(r["source_interpolation_error"] for r in reports.values()),
              "buttock_status": status, "buttock_piece_count": len(cuts), "buttock_domains": domains,
              "buttock_sampled_breadth_residual_m": residual, "computed_intersections": len(anchors),
              "skeleton_origin_x": float(origin_x) if skeleton else None,
              "native_AutoCAD_check": "not performed", "native_Rhino_check": "not performed",
              "scope": "supplied offsets only; no inferred bottom, centreline closure or deck"}
    (out / "validation.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    if csv_path.resolve() != (out / "offsets_source.csv").resolve():
        shutil.copyfile(csv_path, out / "offsets_source.csv")
    if config_path.resolve() != (out / "parameters_source.json").resolve():
        shutil.copyfile(config_path, out / "parameters_source.json")
    with (out / "derived_intersections.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["half_breadth_m", "x", "height_m", "kind"])
        w.writerows([a, c, d, "computed_not_original"] for a, c, d in anchors)
    (out / "OPEN_IN_CAD.txt").write_text(
        "AutoCAD: OPEN the DXF; Z then E for extents. SAVEAS for DWG.\n"
        + x_note + "\nHalf breadth and height are in metres.\n"
        "SOURCE* layers retain original offsets; DERIVED* contain calculated intersections.\n"
        "Partial longitudinal cuts; centreline/bottom/deck outlines are not supplied.\n"
        "Native AutoCAD/Rhino validation has not been performed by this script.\n", encoding="utf-8")
    if preview:
        plot_preview(writers[:3], out / "preview.png", physical)
    return report


def plot_preview(writers, filename, physical):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(3, 1, figsize=(13, 10), layout="constrained")
    for ax, (name, writer) in zip(axes, [writers[2], writers[0], writers[1]]):
        names = list(dict.fromkeys(c[0] for c in writer.curves))
        colors = {n: plt.get_cmap("tab20")(i % 20) for i, n in enumerate(names)}
        for name_layer, ts, vals, mapper, fit in writer.curves:
            vv = np.linspace(ts[0], ts[-1], 500)
            points = np.array([mapper(t, float(fit(t))) for t in vv])
            ax.plot(points[:, 0], points[:, 1], lw=1.1, label=name_layer, color=colors[name_layer])
        for entity in writer.ms.query("POINT"):
            loc = entity.dxf.location
            ax.scatter([loc.x], [loc.y], s=5, color="#6e7782")
        ax.set_title(name.removesuffix(".dxf").replace("_", " "))
        handles, labels = ax.get_legend_handles_labels()
        unique = dict(zip(labels, handles))
        if unique:
            ax.legend(unique.values(), unique.keys(), fontsize=6, ncols=min(4, len(unique)), loc="upper right")
        ax.set_ylabel("Half breadth [m]" if name == "waterline_plan.dxf" else "Height [m]")
        ax.grid(lw=0.4, alpha=0.4)
        if name != "body_plan.dxf" and not physical:
            ax.set_xlabel("Station number; no physical longitudinal scale")
        else:
            ax.set_aspect("equal", adjustable="datalim")
            ax.set_xlabel("Half breadth [m]" if name == "body_plan.dxf" else "X [m]")
    fig.savefig(filename, dpi=150)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--skeleton3d", action="store_true")
    parser.add_argument("--preview", action="store_true")
    args = parser.parse_args()
    try:
        report = generate(args.csv, args.config, args.out, args.skeleton3d, args.preview)
    except (ValueError, KeyError, AssertionError) as error:
        print(f"Hull generation stopped: {error}", file=sys.stderr)
        return 2
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
