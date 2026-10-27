"""Source-preserving parsing and explicit, atomic estimate batches.

Profile magnitude filtering is an interpretation guard, not a hull boundary.
Only a separately supplied corrections manifest activates correction; historical
corrections in config are descriptive. Source files and raw literals stay intact.
"""
from __future__ import annotations

import copy
import csv
from dataclasses import dataclass
from decimal import Decimal, ROUND_HALF_UP
import json
from pathlib import Path
import re

import numpy as np
from scipy.interpolate import PchipInterpolator

_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$")
_STATION = re.compile(r"^([+-]?(?:\d+(?:\.\d*)?|\.\d+))\s*\((AP|FP)\)$", re.I)


@dataclass
class Bundle:
    params: dict
    fields: list
    rows_original: list
    rows_effective: list
    stations: np.ndarray
    x: np.ndarray
    z: np.ndarray
    b: np.ndarray
    physical: bool
    x_note: str
    split: float
    origin_x: float
    levels: list
    profile_fields: list
    profile_rows: list
    profile_values: np.ndarray | None
    profile_half_widths: list
    deck_fields: list
    deck_rows: list
    deck_values: np.ndarray | None
    transom: dict
    correction_report: dict
    inventory: list


def _read_csv(path):
    with Path(path).open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        if not reader.fieldnames or reader.fieldnames[0] != "station":
            raise ValueError(f"{path}: CSV first column must be station")
        if len(set(reader.fieldnames)) != len(reader.fieldnames):
            raise ValueError(f"{path}: duplicate CSV field names")
        rows = list(reader)
        if any(None in row or any(value is None for value in row.values()) for row in rows):
            raise ValueError(f"{path}: CSV row widths must match the header")
    return reader.fieldnames[1:], rows


def _positive(value, name):
    number = float(value)
    if not np.isfinite(number) or number <= 0:
        raise ValueError(f"{name} must be finite and positive")
    return number


def _station(raw, params):
    literal = str(raw).strip()
    if literal.upper() == "TRANSOM":
        return None
    tagged = _STATION.fullmatch(literal)
    if tagged:
        value, tag = float(tagged[1]), tagged[2].upper()
        if "station_AP" not in params or "station_FP" not in params:
            raise ValueError("Tagged AP/FP station requires explicit station_AP and station_FP mapping")
        if params[f"station_{tag}"] is None or not np.isclose(value, float(params[f"station_{tag}"]), rtol=0, atol=1e-10):
            raise ValueError(f"Tagged station {literal} conflicts with explicit {tag} mapping")
    elif _NUMBER.fullmatch(literal):
        value = float(literal)
    else:
        raise ValueError(f"Unknown station {literal!r}; supply a numeric station or consistent AP/FP mapping")
    if not np.isfinite(value):
        raise ValueError("Station numbers must be finite")
    return value


def _scalar(raw, scale, limit=None, breadth=False):
    literal = str(raw).strip()
    if literal in ("", "-", "?"):
        return np.nan, "missing"
    if not _NUMBER.fullmatch(literal):
        return np.nan, "text"
    value = float(literal) * scale
    if not np.isfinite(value) or (limit is not None and abs(value) > limit):
        return np.nan, "needs_interpretation"
    if breadth and value < 0:
        raise ValueError(f"Half breadths must be nonnegative; found {literal!r}")
    return value, "known"


def _matrix(rows, fields, scale, source, inventory, limit=None, breadth=False):
    matrix = np.full((len(rows), len(fields)), np.nan)
    for i, row in enumerate(rows):
        for j, field in enumerate(fields):
            value, status = _scalar(row[field], scale, limit, breadth)
            matrix[i, j] = value
            inventory.append({"source": source, "row": row["station"], "row_index": i,
                              "field": field, "raw": row[field],
                              "source_unit": "mm" if scale == .001 else "m" if scale == 1 else "source units",
                              "conversion_to_m": scale, "value_unit": "m",
                              "value_m": float(value) if np.isfinite(value) else None,
                              "status": status, "uses": []})
    return matrix


def _supplement(path, params, stations, source):
    if path is None:
        return [], [], []
    fields, raw_rows = _read_csv(path)
    mapped, transom = {}, []
    for row in raw_rows:
        value = _station(row["station"], params)
        if value is None:
            transom.append(row)
            continue
        match = np.flatnonzero(np.isclose(stations, value, rtol=0, atol=1e-10))
        if len(match) != 1:
            raise ValueError(f"{source}: station {row['station']!r} does not map to a half-breadth station")
        index = int(match[0])
        if index in mapped:
            raise ValueError(f"{source}: duplicate station mapping for {row['station']!r}")
        mapped[index] = row
    if len(transom) > 1:
        raise ValueError(f"{source}: duplicate TRANSOM rows")
    if len(mapped) != len(stations):
        absent = [float(stations[i]) for i in range(len(stations)) if i not in mapped]
        raise ValueError(f"{source}: station rows missing {absent}; supply explicit blank cells rather than positional alignment")
    return fields, [mapped[i] for i in range(len(stations))], transom


def _coordinates(params, stations, skeleton):
    physical = True
    if "station_x_m" in params:
        x = np.asarray(params["station_x_m"], dtype=float)
        note = "explicit station positions [m]"
    elif params.get("LBP_m") is not None:
        if params.get("station_AP") is None or params.get("station_FP") is None:
            raise ValueError("LBP requires explicit station_AP and station_FP mapping")
        ap, fp = float(params["station_AP"]), float(params["station_FP"])
        lbp = _positive(params["LBP_m"], "LBP_m")
        if not np.isfinite([ap, fp]).all() or fp <= ap:
            raise ValueError("Invalid AP/FP mapping")
        x = (stations - ap) / (fp - ap) * lbp
        note = f"x=(station-{ap:g})/({fp:g}-{ap:g})*{lbp:g} m"
    elif params.get("station_spacing_m") is not None:
        gap = _positive(params["station_spacing_m"], "station_spacing_m")
        origin = float(params.get("station_AP", stations[0]))
        x = (stations - origin) * gap
        note = f"x=(station-{origin:g})*{gap:g} m; supplied station spacing"
    else:
        factor = _positive(params.get("longitudinal_display_units_per_station", 1), "longitudinal_display_units_per_station")
        x = stations * factor
        physical = False
        note = f"x=station number*{factor:g}; display factor only; no physical longitudinal scale"
    if x.ndim != 1 or len(x) != len(stations) or not np.isfinite(x).all() or np.any(np.diff(x) <= 0):
        raise ValueError("Station coordinates must match rows and increase strictly")
    if skeleton and not physical:
        raise ValueError("3D export needs physical station positions, LBP mapping or explicit station spacing")
    default_split = float(params["LBP_m"]) / 2 if params.get("LBP_m") is not None and "station_x_m" not in params else (x[0] + x[-1]) / 2
    if "body_split_x" in params:
        split = float(params["body_split_x"])
    elif "body_plan_split_station" in params:
        split_station = float(params["body_plan_split_station"])
        if not stations[0] <= split_station <= stations[-1]:
            raise ValueError("body_plan_split_station must lie within supplied stations")
        split = float(np.interp(split_station, stations, x))
    else:
        split = default_split
    origin_x = float(x[0])
    if "origin_station" in params:
        where = np.flatnonzero(np.isclose(stations, float(params["origin_station"]), rtol=0, atol=1e-10))
        if len(where) != 1:
            raise ValueError("origin_station must be a station present in the CSV")
        origin_x = float(x[where[0]])
    # A partial table can lie wholly aft/forward of the documented split.
    if not np.isfinite(split):
        raise ValueError("body_split_x must be finite")
    return x, physical, note, float(split), origin_x


def _interval_support(original, masked, target_index):
    """Exclude targets while ordinary missing source cells bound support."""
    missing = np.flatnonzero(~np.isfinite(original))
    before, after = missing[missing < target_index], missing[missing > target_index]
    lower = int(before[-1]) + 1 if len(before) else 0
    upper = int(after[0]) if len(after) else len(original)
    indices = np.flatnonzero(np.isfinite(masked))
    return indices[(indices >= lower) & (indices < upper)]


def _corrections(path, rows, fields, stations, z, b, scale, params):
    effective = copy.deepcopy(rows)
    report = {"status": "not_requested", "targets": [], "failures": []}
    if path is None:
        return effective, b.copy(), report
    report["status"] = "not_applied"
    try:
        payload = json.loads(Path(path).read_text(encoding="utf-8-sig"))
        targets = payload.get("targets") if isinstance(payload, dict) else payload
        if not isinstance(targets, list):
            raise ValueError("Correction manifest must be a list or an object containing targets list")
        report["requested_targets"] = copy.deepcopy(targets)
        decimals = params.get("correction_decimals", 0)
        if isinstance(decimals, bool) or int(decimals) != decimals or not 0 <= int(decimals) <= 12:
            raise ValueError("correction_decimals must be an integer from 0 to 12")
        decimals = int(decimals)
    except (ValueError, TypeError, OSError) as error:
        report["failures"].append(str(error))
        return effective, b.copy(), report
    mapped, seen = [], set()
    for target in targets:
        try:
            if not isinstance(target, dict):
                raise ValueError("Each correction target must be an object")
            station = _station(target["station"], params)
            index = np.flatnonzero(np.isclose(stations, station, rtol=0, atol=1e-10)) if station is not None else []
            if len(index) != 1 or target["column"] not in fields:
                raise ValueError(f"Correction target does not identify an existing cell: {target}")
            i, j = int(index[0]), fields.index(target["column"])
            if (i, j) in seen:
                raise ValueError(f"Duplicate correction target: {target}")
            seen.add((i, j))
            if not np.isfinite(b[i, j]):
                raise ValueError(f"Correction target is missing or has no scalar value: {target}")
            mapped.append((target, i, j))
        except (ValueError, TypeError, KeyError) as error:
            report["failures"].append(str(error))
    # Mask the whole authorized batch before fitting either direction.
    support = b.copy() / scale
    for _, i, j in mapped:
        support[i, j] = np.nan
    proposals = []
    for target, i, j in mapped:
        try:
            method = target.get("method", "pchip_station")
            indices = _interval_support(b[:, j], support[:, j], i)
            neighbors = [[float(stations[k]), float(support[k, j])] for k in indices]
            if method == "pchip_station":
                if not np.any(indices < i) or not np.any(indices > i):
                    raise ValueError(f"Correction at station {stations[i]:g}/{fields[j]} requires known support on both sides")
                estimate = float(PchipInterpolator(stations[indices], support[indices, j], extrapolate=False)(stations[i]))
            elif method == "value":
                estimate = float(target["value"])
            else:
                raise ValueError(f"Unknown correction method {method!r}")
            if not np.isfinite(estimate) or estimate < 0:
                raise ValueError(f"Correction estimate must be finite and nonnegative: {target}")
            if estimate * scale > float(params.get("half_breadth_limit_m", 1e6)):
                raise ValueError(f"Correction exceeds the configured interpretation guard: {target}")
            raw = format(Decimal(str(estimate)).quantize(Decimal(1).scaleb(-decimals), rounding=ROUND_HALF_UP), f".{decimals}f")
            fitted = float(raw)
            section_indices = _interval_support(b[i], support[i], j)
            section = None
            if np.any(section_indices < j) and np.any(section_indices > j):
                section = float(PchipInterpolator(z[section_indices], support[i, section_indices], extrapolate=False)(z[j]))
            record = {"station": float(stations[i]), "column": fields[j], "method": method,
                      "original_raw": rows[i][fields[j]], "original_value": float(b[i, j] / scale),
                      "original_value_m": float(b[i, j]), "fitted_raw": raw, "fitted_value": fitted,
                      "fitted_value_m": fitted * scale, "unrounded_estimate": estimate,
                      "section_crosscheck": section, "section_crosscheck_status": "available" if section is not None else "unavailable: no support on both sides",
                      "section_crosscheck_difference": estimate-section if section is not None else None,
                      "section_neighbor_evidence": [[float(z[k]), float(support[i,k])] for k in section_indices],
                      "neighbor_evidence": neighbors, "status": "estimated"}
            proposals.append((i, j, record))
        except (ValueError, TypeError, KeyError) as error:
            report["failures"].append(str(error))
    report["targets"] = [record for _, _, record in proposals]
    if report["failures"]:
        for record in report["targets"]:
            record["applied"] = False
        return effective, b.copy(), report
    corrected = b.copy()
    for i, j, record in proposals:
        effective[i][fields[j]] = record["fitted_raw"]
        corrected[i, j] = record["fitted_value_m"]
        record["applied"] = True
    report["status"] = "applied"
    return effective, corrected, report


def load_bundle(csv_path, config_path, profile_csv=None, deck_csv=None,
                transom_json=None, corrections_json=None, skeleton=False):
    """Load immutable source tables and optional authorized drawing estimates."""
    params = json.loads(Path(config_path).read_text(encoding="utf-8-sig"))
    params.setdefault("languages", ["zh", "en"])
    params.setdefault("embedded_tables", True)
    params.setdefault("annotations", True)
    fields, raw_rows = _read_csv(csv_path)
    rows, stations, transom_rows = [], [], []
    for row in raw_rows:
        station = _station(row["station"], params)
        if station is None:
            transom_rows.append(row)
        else:
            rows.append(row)
            stations.append(station)
    if len(transom_rows) > 1:
        raise ValueError("Duplicate TRANSOM station rows")
    stations = np.asarray(stations, dtype=float)
    z = np.asarray(params["waterline_heights_m"], dtype=float)
    if len(stations) < 2 or z.ndim != 1 or len(z) < 2 or len(z) != len(fields):
        raise ValueError("Need at least two stations and two waterlines; heights must match CSV columns")
    if not np.isfinite(z).all() or np.any(np.diff(stations) <= 1e-10) or np.any(np.diff(z) <= 0):
        raise ValueError("Station numbers and heights must be finite and strictly increasing; duplicate mapping is not allowed")
    scale = _positive(params["half_breadth_to_m"], "half_breadth_to_m")
    height_scale = _positive(params.get("height_to_m", scale), "height_to_m")
    profile_limit = _positive(params.get("profile_height_limit_m", max(1., max(abs(z))) * 10), "profile_height_limit_m")
    breadth_limit = _positive(params.get("half_breadth_limit_m", 1e6), "half_breadth_limit_m")
    inventory = []
    original_b = _matrix(rows, fields, scale, "half", inventory, limit=breadth_limit, breadth=True)
    x, physical, note, split, origin_x = _coordinates(params, stations, skeleton)
    levels = [float(v) for v in params.get("buttock_half_breadths_m", [])]
    if any(not np.isfinite(v) or v <= 0 for v in levels) or len(set(levels)) != len(levels):
        raise ValueError("Buttock half breadths must be distinct positive values")
    profile_fields, profile_rows, profile_transom = _supplement(profile_csv, params, stations, "profile")
    profile_values = _matrix(profile_rows, profile_fields, height_scale, "profile", inventory, limit=profile_limit) if profile_csv is not None else None
    widths = []
    if profile_fields:
        if params.get("profile_half_breadths_m") is not None:
            widths = [float(v) for v in params["profile_half_breadths_m"]]
            if len(widths) != len(profile_fields):
                raise ValueError("profile_half_breadths_m must match profile CSV fields")
        else:
            for field in profile_fields:
                if field.upper().replace(".", "") == "CL":
                    widths.append(0.)
                else:
                    match = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*BL", field, re.I)
                    if not match:
                        raise ValueError(f"Cannot infer profile half breadth from {field!r}; supply profile_half_breadths_m")
                    widths.append(float(match[1]) * scale)
        if any(not np.isfinite(v) or v < 0 for v in widths) or len(set(widths)) != len(widths):
            raise ValueError("Profile half breadths must be distinct finite nonnegative values")
        for field, width in zip(profile_fields, widths):
            if field.upper().replace(".", "") == "CL" and width != 0:
                raise ValueError("Centreline CL profile half breadth must be zero")
    deck_fields, deck_rows, deck_transom = _supplement(deck_csv, params, stations, "deck")
    deck_values = _matrix(deck_rows, deck_fields, scale, "deck", inventory, limit=breadth_limit, breadth=True) if deck_csv is not None else None
    transom = json.loads(Path(transom_json).read_text(encoding="utf-8-sig")) if transom_json is not None else {}
    if not isinstance(transom, dict):
        raise ValueError("Transom JSON must be an object")
    if transom or transom_rows or profile_transom or deck_transom:
        transom.setdefault("station_label", "TRANSOM")
        transom.setdefault("longitudinal_position", None)
    for source, source_rows, source_fields, source_scale, limit, breadth, key in (
        ("half", transom_rows, fields, scale, breadth_limit, True, "waterline_half_breadths_raw"),
        ("profile", profile_transom, profile_fields, height_scale, profile_limit, False, "profile_heights_raw"),
        ("deck", deck_transom, deck_fields, scale, breadth_limit, True, "deck_half_breadths_raw")):
        if source_rows:
            transom[key] = {field: source_rows[0][field] for field in source_fields}
            _matrix(source_rows, source_fields, source_scale, source, inventory, limit, breadth)
    # JSON has explicit mm keys; keep those literal objects while indexing cells.
    for key, values in list(transom.items()):
        if isinstance(values, dict) and key in ("waterline_half_breadths_mm", "buttock_height_mm"):
            factor = .001
            row = {"station": "TRANSOM", **{field: str(value) for field, value in values.items()}}
            _matrix([row], list(values), factor, "transom", inventory,
                    profile_limit if key == "buttock_height_mm" else breadth_limit, key == "waterline_half_breadths_mm")
        elif key in ("upper_deck_half_breadth_mm", "poop_deck_half_breadth_mm", "CL_raw"):
            row = {"station": "TRANSOM", key: str(values)}
            _matrix([row], [key], .001 if key.endswith("_mm") else height_scale, "transom", inventory, profile_limit if key == "CL_raw" else breadth_limit, key.endswith("_mm"))
    effective, b, report = _corrections(corrections_json, rows, fields, stations, z, original_b, scale, params)
    if report["status"] == "applied":
        for target in report["targets"]:
            for cell in inventory:
                if cell["source"] == "half" and cell["row"] != "TRANSOM" and _station(cell["row"], params) == target["station"] and cell["field"] == target["column"]:
                    cell["status"] = "estimated"
                    cell["original_value_m"] = cell["value_m"]
                    cell["value_m"] = target["fitted_value_m"]
                    cell["effective_raw"] = target["fitted_raw"]
                    break
    return Bundle(params, fields, copy.deepcopy(rows), effective, stations, x, z, b,
                  physical, note, split, origin_x, sorted(levels), profile_fields,
                  profile_rows, profile_values, widths, deck_fields, deck_rows,
                  deck_values, transom, report, inventory)
