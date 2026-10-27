"""Geometry-preserving, repeatable labels for existing 2D hull drawings.

Only HULLANNOT JSON with generated_by='hull-lines-dxf' and kind='curve_label'
belongs to this module. Layer names alone never confer ownership. HULLCURVE
metadata takes precedence over conventional layers; unknown geometry is reported.

Config keys: layer_mapping (exact layer -> metadata), font_path_zh/en,
text_height (positive drawing units), sample_count (>=32), max_label_attempts.
LINE entities need explicit metadata/mapping: conventional curve layers can also
contain legend swatches or construction lines. Spline/polyline layers are detected.
Optional metadata: view, kind, number, side; POINT also requires source_point=true
or role='source_point'. BL_<number> is the source halfwidth in millimetres and
is labelled in metres; BP_<number> is already expressed in metres.

Text widths use the conservative envelope of both languages, so language alone
never changes placement. A crowded station label falls back to an outside leader.
Leader columns can expand beyond the view extents; text avoids other labels,
existing text, sampled curves and prior leaders. Leaders may cross hull geometry
on their way from an attachment point. Sampling is a layout check, not an exact
CAD intersection proof; native font substitution remains an application check.
"""
from collections import defaultdict
from functools import lru_cache
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np

APPID = "HULLANNOT"
GENERATOR = "hull-lines-dxf"
VIEWS = ("body", "waterline", "profile")
KINDS = {"body": {"ST", "TRANSOM"}, "waterline": {"WL"}, "profile": {"BP", "CL"}}
GEOMETRY = {"SPLINE", "LWPOLYLINE", "POLYLINE", "LINE", "POINT"}
NUMBER = r"(?:[-+]?\d+(?:\.\d+)?|m?\d+(?:p\d+)?)"


def _json_xdata(entity, appid):
    try:
        return json.loads("".join(t.value for t in entity.get_xdata(appid) if t.code == 1000))
    except Exception:
        # DXFValueError differs between ezdxf releases; invalid metadata is never ownership.
        return None


def _owned(entity):
    data = _json_xdata(entity, APPID)
    return isinstance(data, dict) and data.get("generated_by") == GENERATOR and data.get("kind") == "curve_label"


def _number(value):
    result = float(str(value).replace("m", "-").replace("p", "."))
    if not math.isfinite(result):
        raise ValueError("nonfinite curve number")
    return result


def _layer_metadata(layer):
    local = layer
    for prefix in ("BODY_", "PLAN_", "PROFILE_", "LONG_"):
        if local.startswith(prefix):
            local = local[len(prefix):]
            break
    special = {"TRANSOM_REFERENCE": {"view": "body", "kind": "TRANSOM", "number": None},
               "CL_SOURCE": {"view": "profile", "kind": "CL", "number": None}}
    if local in special:
        return dict(special[local])
    match = re.fullmatch(r"(ST|WL|BP|BL)_(" + NUMBER + r")", local)
    if not match:
        return None
    kind, number = match.groups()
    value = _number(number)
    if kind == "BL":
        kind, value = "BP", value / 1000.0
    return {"view": {"ST": "body", "WL": "waterline", "BP": "profile"}[kind], "kind": kind, "number": value}


def _metadata(entity, config):
    explicit = _json_xdata(entity, "HULLCURVE")
    if entity.has_xdata("HULLCURVE") and not isinstance(explicit, dict):
        return None, "invalid HULLCURVE JSON"
    mapped = config.get("layer_mapping", {}).get(entity.dxf.layer)
    if entity.dxftype() == "LINE" and explicit is None and mapped is None:
        return None, "LINE requires explicit metadata/mapping; curve layers can contain legend or construction lines"
    data = explicit if explicit is not None else mapped
    if data is None:
        data = _layer_metadata(entity.dxf.layer)
    if not isinstance(data, dict):
        return None, "unknown layer; provide HULLCURVE metadata or layer_mapping"
    data = dict(data)
    view, kind = data.get("view"), str(data.get("kind", "")).upper()
    if view not in KINDS or kind not in KINDS[view]:
        return None, "unsupported view/kind metadata"
    data["kind"] = kind
    try:
        if kind not in {"CL", "TRANSOM"}:
            data["number"] = _number(data["number"])
        if "side" in data and data["side"] not in {-1, 0, 1}:
            raise ValueError("side must be -1, 0 or 1")
    except (KeyError, TypeError, ValueError):
        return None, "invalid number/side metadata"
    if entity.dxftype() == "POINT" and not (view == "profile" and
             (data.get("source_point") is True or data.get("role") == "source_point")):
        return None, "POINT is not explicitly identified as a profile source point"
    return data, None


def _points(entity, samples):
    kind = entity.dxftype()
    if kind == "SPLINE":
        points = list(entity.construction_tool().approximate(samples))
    elif kind in {"LWPOLYLINE", "POLYLINE"}:
        # flatten bulged segments instead of treating arcs as straight chords.
        from ezdxf.path import make_path
        path = make_path(entity)
        points = list(path.flattening(max(path.bbox().size.magnitude / samples, 1e-9)))
    elif kind == "LINE":
        points = [entity.dxf.start, entity.dxf.end]
    else:
        points = [entity.dxf.location]
    xyz = np.array([tuple(point) for point in points], dtype=float)
    if not len(xyz) or not np.isfinite(xyz).all():
        raise ValueError("empty or nonfinite geometry")
    if np.ptp(xyz[:, 2]) > max(np.ptp(xyz[:, :2]), 1.0) * 1e-9:
        raise ValueError("nonplanar geometry; annotation supports 2D drawings")
    xy = xyz[:, :2]
    # Densify straight segments too; narrow collision probes must not miss a LINE.
    if len(xy) > 1:
        lengths = np.linalg.norm(np.diff(xy, axis=0), axis=1)
        distance = np.r_[0.0, np.cumsum(lengths)]
        if distance[-1] > 0:
            target = np.linspace(0, distance[-1], max(samples + 1, len(xy)))
            xy = np.column_stack([np.interp(target, distance, xy[:, axis]) for axis in (0, 1)])
    return xy


@lru_cache(maxsize=1)
def _system_fonts():
    try:
        from matplotlib import font_manager
        fonts = {Path(item.fname).resolve() for item in font_manager.fontManager.ttflist}
        fonts.update(Path(item).resolve() for item in font_manager.findSystemFonts())
        return tuple(sorted((p for p in fonts if p.is_file()), key=lambda p: str(p).casefold()))
    except Exception:
        return ()


from hull_label_layout import _Layout, _Metrics

def annotate(doc, language="zh", config=None):
    """Add labels in-place and return a JSON-serializable placement/audit report.

    Curves, source points, existing styles, colors and user annotations are never
    edited. Annotations previously owned by this generator are replaced. Empty or
    unknown drawings return explicit skipped/unplaced records rather than guesses.
    """
    if language not in {"zh", "en"}:
        raise ValueError("language must be zh or en")
    config = dict(config or {})
    if not isinstance(config.get("layer_mapping", {}), dict):
        raise ValueError("layer_mapping must be an object mapping exact layer names to metadata")
    samples = int(config.get("sample_count", 180))
    if samples < 32:
        raise ValueError("sample_count must be at least 32")
    if "text_height" in config and (not math.isfinite(float(config["text_height"])) or float(config["text_height"]) <= 0):
        raise ValueError("text_height must be finite and positive")
    if int(config.get("max_label_attempts", 160)) < 1:
        raise ValueError("max_label_attempts must be positive")
    report = {"language": language, "label_counts": dict.fromkeys(VIEWS, 0), "labels": [], "unplaced": [],
              "skipped": [], "removed_owned_entities": 0,
              "render_notes": ["Native CAD rendering not tested; text/curve clearance uses sampled geometry.",
                               "Leaders may cross hull curves while connecting to their attachment point.",
                               "Placement respects existing user text; documents with different original text can have different obstacle layouts."]}
    ms = doc.modelspace()
    for entity in list(ms):
        if _owned(entity):
            ms.delete_entity(entity)
            report["removed_owned_entities"] += 1
    metrics = _Metrics(doc, config, _system_fonts)
    report["fonts"] = metrics.notes
    groups = defaultdict(list)
    obstacles = []
    for entity in list(ms):
        if entity.dxftype() not in GEOMETRY:
            continue
        try:
            points = _points(entity, samples)
        except Exception as error:
            report["skipped"].append({"layer": entity.dxf.layer, "handle": entity.dxf.handle,
                                       "reason": "unsupported geometry: " + str(error)})
            continue
        metadata, error = _metadata(entity, config)
        # Reference grids may pass under a curve label; hull curves may not.
        # An explicitly mapped curve on a grid-named layer remains an obstacle.
        reference_grid=entity.dxf.layer in {"GRID","BODY_GRID","PLAN_GRID","PROFILE_GRID","LONG_GRID"}
        if not reference_grid or not error:obstacles.append(points)
        if error:
            report["skipped"].append({"layer": entity.dxf.layer, "handle": entity.dxf.handle, "reason": error})
            continue
        groups[metadata["view"]].append({"entity": entity, "meta": metadata, "points": points})
    if not groups:
        return report
    if APPID not in doc.appids:
        doc.appids.new(APPID)
    layout = _Layout(doc, metrics, np.concatenate(obstacles) if obstacles else np.empty((0, 2)), language, config)
    duplicate_ids = defaultdict(int)
    for view in VIEWS:
        curves = groups[view]
        if not curves:
            continue
        points = np.concatenate([c["points"] for c in curves])
        bounds = np.r_[points.min(axis=0), points.max(axis=0)]
        extent = bounds[2:] - bounds[:2]
        scale = max(min(extent), max(extent)*.07, 1e-12)
        height = float(config.get("text_height", scale*min(.025, .135/math.sqrt(len(curves)+10))))
        center = (bounds[:2]+bounds[2:])/2
        for curve in curves:
            axis = 0 if view == "body" else 1
            curve["side"] = curve["meta"].get("side")
            if curve["side"] is None:
                if view == "profile":
                    # Height does not identify port/starboard; all untagged profile
                    # pieces of the same buttock belong to the same segment group.
                    curve["side"] = 0
                else:
                    signed = float(np.mean(curve["points"][:, axis])-center[axis])
                    curve["side"] = -1 if signed < 0 else 1
            identity = {"layer": curve["entity"].dxf.layer, "type": curve["entity"].dxftype(),
                        "meta": curve["meta"], "points": curve["points"].round(12).tolist()}
            digest = hashlib.sha256(json.dumps(identity, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:20]
            duplicate_ids[digest] += 1
            curve["id"] = "label-" + digest + "-" + str(duplicate_ids[digest])
        curves.sort(key=lambda c: (c["meta"]["kind"], c["meta"].get("number") or 0, c["side"],
                                   float(c["points"][0, 0]), float(c["points"][0, 1]), c["id"]))
        if view == "body":
            repeated_stations = defaultdict(list)
            for curve in curves:
                repeated_stations[(curve["meta"]["kind"], curve["meta"].get("number"))].append(curve)
            for members in repeated_stations.values():
                if len(members) > 1:
                    # Mirrored/coincident midship labels get different heights,
                    # even when opposite sides each contain only one station.
                    for index, curve in enumerate(members, 1):
                        curve["target_fraction"] = index/(len(members)+1)
        pieces = defaultdict(list)
        for curve in curves:
            if view == "profile" and curve["entity"].dxftype() != "POINT":
                pieces[(curve["meta"]["kind"], curve["meta"].get("number"), curve["side"])].append(curve)
        for members in pieces.values():
            for index, curve in enumerate(members, 1):
                curve["segment_index"], curve["segment_count"] = index, len(members)
        by_side = defaultdict(list)
        for curve in curves:
            if view == "body":
                by_side[curve["side"] or 1].append(curve)
            elif view == "waterline":
                by_side[curve["side"] or 1].append(curve)
            else:
                direction = -1 if np.mean(curve["points"][:, 0]) < center[0] else 1
                by_side[direction].append(curve)
        for side, members in sorted(by_side.items()):
            if view != "body":
                members.sort(key=lambda c: (float(c["points"][-1, 1]), c["id"]))
            for rank, curve in enumerate(members):
                placed = False
                if view == "body":
                    placed = layout.station(curve, bounds, height, rank, len(members))
                    slot = bounds[1]+(rank+.5)/len(members)*(bounds[3]-bounds[1])
                    if not placed:
                        placed = layout.leader(curve, bounds, height, side, slot, "station_leader_fallback")
                else:
                    ycenter = center[1]
                    if view == "waterline" and side:
                        # Keep symmetric callout ranges on the corresponding side.
                        slot = ycenter+side*(height*2+rank*height*1.85)
                    else:
                        pitch = max(height*1.85, (bounds[3]-bounds[1])/max(len(members), 1))
                        slot = ycenter+(rank-(len(members)-1)/2)*pitch
                    placed = layout.leader(curve, bounds, height, 1 if view == "waterline" else side, slot)
                if placed:
                    report["label_counts"][view] += 1
                else:
                    report["unplaced"].append({"label_id": curve["id"], "view": view, "kind": curve["meta"]["kind"],
                                               "layer": curve["entity"].dxf.layer, "handle": curve["entity"].dxf.handle,
                                               "reason": "no collision-free text/leader placement within configured attempts"})
    report["labels"] = layout.records
    return report
