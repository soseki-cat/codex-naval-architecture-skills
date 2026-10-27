"""Source-preserving input normalization and checked DXF writer."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import ezdxf
from ezdxf import zoom
import numpy as np
from scipy.interpolate import PchipInterpolator


def control_points(t, v, mapper):
    fit = PchipInterpolator(t, v)
    slopes = fit.derivative()(t)
    cp = [mapper(t[0], v[0])]
    for i in range(len(t) - 1):
        h = t[i + 1] - t[i]
        cp += [
            mapper(t[i] + h / 3, v[i] + h * slopes[i] / 3),
            mapper(t[i + 1] - h / 3, v[i + 1] - h * slopes[i + 1] / 3),
            mapper(t[i + 1], v[i + 1]),
        ]
    knots = [0.0] * 4
    for ti in t[1:-1]:
        knots += [float((ti - t[0]) / (t[-1] - t[0]))] * 3
    knots += [1.0] * 4
    return np.asarray(cp, dtype=float), knots, fit


def load_data(csv_path, config_path, skeleton):
    p = json.loads(config_path.read_text(encoding="utf-8"))
    with csv_path.open(encoding="utf-8-sig", newline="") as f:
        rd = csv.DictReader(f)
        if not rd.fieldnames or rd.fieldnames[0] != "station":
            raise ValueError("CSV first column must be station")
        fields = rd.fieldnames[1:]
        rows = list(rd)
    st = np.array([float(r["station"]) for r in rows])
    z = np.array(p["waterline_heights_m"], dtype=float)
    b = np.array(
        [
            [
                np.nan
                if r.get(k, "").strip() in ("", "-", "?")
                else float(r[k])
                for k in fields
            ]
            for r in rows
        ]
    )
    scale = float(p["half_breadth_to_m"])
    if len(st) < 2 or len(z) < 2 or len(z) != len(fields):
        raise ValueError(
            "Need at least two stations and two waterlines; heights must match CSV columns"
        )
    if not (
        np.isfinite(st).all()
        and np.isfinite(z).all()
        and np.all(np.diff(st) > 0)
        and np.all(np.diff(z) > 0)
    ):
        raise ValueError(
            "Station numbers and heights must be finite and strictly increasing"
        )
    if (
        not np.isfinite(scale)
        or scale <= 0
        or np.any(b[np.isfinite(b)] < 0)
        or np.isinf(b).any()
    ):
        raise ValueError(
            "Half breadths must be nonnegative; conversion factor must be positive"
        )
    b *= scale
    physical = True
    if "station_x_m" in p:
        x = np.array(p["station_x_m"], dtype=float)
        x_note = "explicit station positions [m]"
    elif p.get("LBP_m") is not None:
        if "station_AP" not in p or "station_FP" not in p:
            raise ValueError("LBP requires explicit station_AP and station_FP mapping")
        ap, fp, lbp = (
            float(p["station_AP"]),
            float(p["station_FP"]),
            float(p["LBP_m"]),
        )
        if not np.isfinite([ap, fp, lbp]).all() or fp <= ap or lbp <= 0:
            raise ValueError("Invalid AP/FP mapping or LBP")
        x = (st - ap) / (fp - ap) * lbp
        x_note = f"x=(station-{ap:g})/({fp:g}-{ap:g})*{lbp:g} m"
    elif p.get("station_spacing_m") is not None:
        gap = float(p["station_spacing_m"])
        origin = float(p.get("station_AP", st[0]))
        if not np.isfinite(gap) or gap <= 0:
            raise ValueError("station_spacing_m must be positive")
        x = (st - origin) * gap
        x_note = (
            f"x=(station-{origin:g})*{gap:g} m; "
            "spacing supplied/assumed as recorded in config"
        )
    else:
        x = st.copy()
        physical = False
        x_note = "x=station number; no physical longitudinal scale"
    if len(x) != len(st) or not np.isfinite(x).all() or np.any(np.diff(x) <= 0):
        raise ValueError("Station coordinates must match rows and increase strictly")
    if skeleton and not physical:
        raise ValueError(
            "3D export needs physical station positions, LBP mapping or explicit station spacing"
        )
    default_split = (
        float(p["LBP_m"]) / 2
        if p.get("LBP_m") is not None and "station_x_m" not in p
        else (x[0] + x[-1]) / 2
    )
    split = float(p.get("body_split_x", default_split))
    origin_x = x[0]
    if "origin_station" in p:
        where = np.flatnonzero(
            np.isclose(st, float(p["origin_station"]), rtol=0, atol=1e-10)
        )
        if len(where) != 1:
            raise ValueError("origin_station must be a station present in the CSV")
        origin_x = x[where[0]]
    levels = [float(v) for v in p.get("buttock_half_breadths_m", [])]
    if any(not np.isfinite(v) or v <= 0 for v in levels) or len(set(levels)) != len(
        levels
    ):
        raise ValueError(
            "Buttock half breadths must be distinct positive values; "
            "centreline profile is not inferable"
        )
    return (
        p,
        rows,
        fields,
        st,
        x,
        z,
        b,
        physical,
        x_note,
        split,
        origin_x,
        sorted(levels),
    )


class Writer:
    def __init__(self, physical=True):
        self.doc = ezdxf.new("R2010")
        self.doc.units = 6 if physical else 0
        self.doc.header["$PDMODE"] = 35
        self.doc.header["$PDSIZE"] = 0.04
        self.doc.styles.new("HULL_FONT", dxfattribs={"font": "arial.ttf"})
        self.doc.appids.new("HULLSOURCE")
        self.ms = self.doc.modelspace()
        self.curve_checks = []
        self.point_checks = []
        self.curves = []

    def layer(self, name, color=7):
        if name not in self.doc.layers:
            self.doc.layers.new(name, dxfattribs={"color": color})
        return name

    def point(self, xyz, name, color, metadata):
        self.layer(name, color)
        pt = self.ms.add_point(xyz, dxfattribs={"layer": name})
        pt.set_xdata("HULLSOURCE", [(1000, metadata)])
        self.point_checks.append((pt.dxf.handle, np.array(xyz), metadata))

    def text(self, content, xyz, height):
        self.layer("NOTES", 7)
        self.ms.add_text(
            content,
            dxfattribs={
                "insert": xyz,
                "height": height,
                "style": "HULL_FONT",
                "layer": "NOTES",
            },
        )

    def line(self, a, c):
        self.layer("GRID", 8)
        self.ms.add_line(a, c, dxfattribs={"layer": "GRID"})

    def curve(self, t, values, mapper, name, color, source=True):
        self.layer(name, color)
        cp, knots, fit = control_points(t, values, mapper)
        e = self.ms.add_open_spline(
            cp, degree=3, knots=knots, dxfattribs={"layer": name}
        )
        if np.allclose(cp[:, 2], 0):
            e.dxf.flags = 8
        params = (np.asarray(t) - t[0]) / (t[-1] - t[0])
        expected = np.array([mapper(a, v) for a, v in zip(t, values)])
        self.curve_checks.append((e.dxf.handle, params, expected, source))
        self.curves.append((name, np.array(t), np.array(values), mapper, fit))
        return e, fit

    def save_checked(self, path):
        zoom.extents(self.ms)
        self.doc.saveas(path)
        d = ezdxf.readfile(path)
        audit = d.audit()
        if audit.errors or audit.fixes:
            raise AssertionError(f"DXF audit error/fix: {path}")
        source_error, all_error = 0.0, 0.0
        for handle, params, expected, source in self.curve_checks:
            bs = d.entitydb[handle].construction_tool()
            actual = np.array([tuple(bs.point(float(t))) for t in params])
            error = float(np.max(np.abs(actual - expected)))
            all_error = max(all_error, error)
            if source:
                source_error = max(source_error, error)
            if error > 1e-7:
                raise AssertionError(f"Lost interpolation node in {path}: {error}")
        for handle, xyz, meta in self.point_checks:
            e = d.entitydb[handle]
            if not np.allclose(e.dxf.location, xyz, atol=1e-10, rtol=0):
                raise AssertionError("Lost original point coordinates")
            if e.get_xdata("HULLSOURCE")[0].value != meta:
                raise AssertionError("Lost source metadata")
        return {
            "audit_errors": 0,
            "audit_fixes": 0,
            "splines": len(d.modelspace().query("SPLINE")),
            "points": len(d.modelspace().query("POINT")),
            "source_interpolation_error": source_error,
            "all_interpolation_error": all_error,
        }
