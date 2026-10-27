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
from scipy.spatial import cKDTree
from ezdxf.enums import TextEntityAlignment

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


@lru_cache(maxsize=512)
def _has_glyphs(path, characters):
    try:
        from matplotlib.ft2font import FT2Font
        glyphs = FT2Font(path).get_charmap()
        return all(ord(c) in glyphs for c in characters)
    except Exception:
        return False


class _Metrics:
    """Discover fonts without changing DXF styles; retain honest render status."""
    def __init__(self, doc, config):
        self.fonts = {}
        self.paths = {}
        self.styles = {}
        self.notes = []
        styles = [(s.dxf.name, s.dxf.get("font", "")) for s in doc.styles]
        files = _system_fonts()
        style_files = {}
        for name, reference in styles:
            if not reference:
                continue
            candidate = Path(reference).expanduser()
            if candidate.is_file():
                style_files[name] = candidate.resolve()
            else:
                matches = [p for p in files if p.name.casefold() == candidate.name.casefold()]
                if matches:
                    style_files[name] = matches[0]
        for language, characters in (("en", "STWLBP0123456789"), ("zh", "站艉封板分段孤立型值点")):
            requested = config.get("font_path_" + language)
            preferred = [Path(requested).expanduser()] if requested else []
            # System font selection is deterministic across bilingual DXFs whose
            # existing styles differ. Explicit configuration overrides it; style
            # fonts remain a fallback when unavailable through system discovery.
            favored_names = (("arial", "dejavusans", "liberationsans") if language == "en" else
                             ("simhei", "notosanscjk", "msyh", "wenquanyi"))
            ordered_files = sorted(files, key=lambda p: (
                next((i for i, name in enumerate(favored_names) if p.stem.casefold().startswith(name)),
                     len(favored_names)), str(p).casefold()))
            candidates = preferred + ordered_files + list(style_files.values())
            path = next((p for p in candidates if p.is_file() and _has_glyphs(str(p), characters)), None)
            self.paths[language] = str(path) if path else None
            self.styles[language] = next((name for name, p in style_files.items()
                                         if _has_glyphs(str(p), characters)), "Standard")
            if path:
                try:
                    from PIL import ImageFont
                    self.fonts[language] = ImageFont.truetype(str(path), 1000)
                except Exception:
                    self.fonts[language] = None
            else:
                self.fonts[language] = None
            render_path = style_files.get(self.styles[language])
            verified = bool(render_path and _has_glyphs(str(render_path), characters))
            self.notes.append({"language": language, "metric_font": self.paths[language],
                               "style": self.styles[language], "glyph_metrics_verified": bool(self.fonts[language]),
                               "dxf_style_glyphs_verified": verified,
                               "render_status": "native application rendering not tested" if verified else
                               "unverified: existing DXF style may substitute or omit glyphs"})
            if requested and (not path or str(Path(requested).expanduser()) != str(path)):
                self.notes[-1]["configured_font_note"] = "configured font unusable; discovered font or conservative fallback used"

    def width(self, text, language, height):
        font = self.fonts[language]
        if font:
            box = font.getbbox("H")
            return float(font.getlength(text)) * height / max(box[3] - box[1], 1)
        # Deliberately generous bounds when CJK metrics cannot be verified.
        return sum(1.4 if ord(c) > 127 else .95 for c in text) * height

    def envelope(self, texts, height):
        return max(self.width(texts[lang], lang, height) for lang in ("zh", "en"))


def _texts(curve):
    kind = curve["meta"]["kind"]
    value = curve["meta"].get("number")
    number = f"{value:g}" if value is not None else ""
    en = {"ST": "ST" + number, "WL": "WL" + number, "BP": "BP" + number,
          "CL": "C.L", "TRANSOM": "TRANSOM"}[kind]
    zh = {"ST": "站" + number, "WL": "WL" + number, "BP": "BP" + number,
          "CL": "C.L", "TRANSOM": "艉封板"}[kind]
    if curve["entity"].dxftype() == "POINT":
        en += " (isolated point)"
        zh += "（孤立型值点）"
    elif curve.get("segment_count", 1) > 1:
        fraction = f"{curve['segment_index']}/{curve['segment_count']}"
        en += " (segment " + fraction + ")"
        zh += "（分段" + fraction + "）"
    return {"en": en, "zh": zh}


def _box(center, angle, width, height):
    theta = math.radians(angle)
    along = np.array([math.cos(theta), math.sin(theta)])
    across = np.array([-along[1], along[0]])
    corners = np.array([center + along*x*width/2 + across*y*height/2 for x in (-1, 1) for y in (-1, 1)])
    return np.r_[corners.min(axis=0), corners.max(axis=0)]


def _overlap(a, b):
    return a[0] < b[2] and a[2] > b[0] and a[1] < b[3] and a[3] > b[1]


def _crosses_box(start, end, box):
    """Liang-Barsky segment/rectangle test, including touching the rectangle."""
    delta = end - start
    lo, hi = 0.0, 1.0
    for axis in (0, 1):
        if abs(delta[axis]) < 1e-12:
            if start[axis] < box[axis] or start[axis] > box[axis+2]:
                return False
        else:
            a, b = (box[axis]-start[axis])/delta[axis], (box[axis+2]-start[axis])/delta[axis]
            lo, hi = max(lo, min(a, b)), min(hi, max(a, b))
            if lo > hi:
                return False
    return True


def _effective_color(doc, entity):
    color = entity.dxf.get("color", 256)
    layer = doc.layers.get(entity.dxf.layer)
    # BYBLOCK remains BYBLOCK: a top-level BYBLOCK entity uses the default ACI,
    # whereas BYLAYER must be resolved before moving to an annotation layer.
    attrs = {"color": abs(layer.dxf.color) if color == 256 else color}
    true_color = entity.dxf.get("true_color")
    if true_color is None and color == 256:
        true_color = layer.dxf.get("true_color")
    if true_color is not None:
        attrs["true_color"] = true_color
    return attrs


def _user_text_boxes(doc, metrics):
    boxes = []
    for entity in doc.modelspace():
        kind = entity.dxftype()
        if kind not in {"TEXT", "MTEXT"}:
            continue
        text = entity.dxf.text if kind == "TEXT" else entity.plain_text()
        height = entity.dxf.get("height", .1) if kind == "TEXT" else entity.dxf.get("char_height", .1)
        if height <= 0:
            continue
        length = max(metrics.width(text, lang, height) for lang in ("en", "zh"))
        center = np.array(tuple(entity.dxf.insert)[:2], dtype=float)
        angle = entity.dxf.get("rotation", 0)
        if kind == "TEXT":
            # Include insertion and alignment points conservatively for all justifications.
            points = [center]
            if entity.dxf.hasattr("align_point"):
                points.append(np.array(tuple(entity.dxf.align_point)[:2]))
            boxes.extend(_box(p, angle, length*2, height*3) for p in points)
        else:
            width = max(entity.dxf.get("width", 0), length)
            line_count = max(1, text.count("\n") + 1)
            boxes.append(np.r_[center-[width, height*line_count*2], center+[width, height*line_count*2]])
    return boxes


class _Layout:
    def __init__(self, doc, metrics, all_points, language, config):
        self.doc, self.metrics, self.language, self.config = doc, metrics, language, config
        self.boxes = _user_text_boxes(doc, metrics)
        self.leaders = []
        self.tree = cKDTree(all_points) if len(all_points) else None
        self.points = all_points
        self.records = []

    def clear(self, center, angle, width, height):
        box = _box(center, angle, width, height*1.45)
        if any(_overlap(box, other) for other in self.boxes):
            return None
        if any(_crosses_box(a, b, box) for a, b in self.leaders):
            return None
        if self.tree:
            ids = self.tree.query_ball_point(center, math.hypot(width, height*1.45)/2)
            if ids:
                delta = self.points[ids] - center
                theta = math.radians(angle)
                along = np.array([math.cos(theta), math.sin(theta)])
                across = np.array([-along[1], along[0]])
                inside = (np.abs(delta @ along) <= width/2) & (np.abs(delta @ across) <= height*.725)
                if inside.any():
                    return None
        return box

    def tag(self, entity, curve, role):
        data = {"generated_by": GENERATOR, "kind": "curve_label", "label_id": curve["id"],
                "role": role, "source_layer": curve["entity"].dxf.layer,
                "source_handle":curve["entity"].dxf.handle, "curve_number":curve["meta"].get("number"),
                "view": curve["meta"]["view"], "curve_kind": curve["meta"]["kind"]}
        value = json.dumps(data, ensure_ascii=True, separators=(",", ":"))
        entity.set_xdata(APPID, [(1000, value[i:i+240]) for i in range(0, len(value), 240)])

    def emit(self, curve, center, angle, height, box, leader=None, placement="inline"):
        view = curve["meta"]["view"]
        layer = "ANN_HULL_" + view.upper()
        if layer not in self.doc.layers:
            self.doc.layers.new(layer, dxfattribs={"color": 7})
        attrs = _effective_color(self.doc, curve["entity"])
        attrs["layer"] = layer
        text = self.doc.modelspace().add_text(_texts(curve)[self.language], dxfattribs={
            **attrs, "height": height, "rotation": angle, "style": self.metrics.styles[self.language]})
        text.set_placement((*center, 0), align=TextEntityAlignment.MIDDLE_CENTER)
        self.tag(text, curve, "text")
        if leader is not None:
            tip, knee, end = leader
            line = self.doc.modelspace().add_lwpolyline([tip, knee, end], dxfattribs=attrs)
            self.tag(line, curve, "leader")
            vector = tip - knee
            magnitude = float(np.linalg.norm(vector))
            vector = vector / magnitude if magnitude else np.array([-1.0, 0.0])
            normal = np.array([-vector[1], vector[0]])
            base = tip - vector*height*.8
            vertices = [(*tip, 0), (*(base+normal*height*.26), 0),
                        (*(base-normal*height*.26), 0), (*(base-normal*height*.26), 0)]
            arrow = self.doc.modelspace().add_solid(vertices, dxfattribs=attrs)
            self.tag(arrow, curve, "arrow")
            self.leaders.extend([(tip, knee), (knee, end)])
        self.boxes.append(box)
        self.records.append({"label_id": curve["id"], "view": view, "kind": curve["meta"]["kind"],
                             "source_layer": curve["entity"].dxf.layer, "source_handle": curve["entity"].dxf.handle,
                             "position": center.tolist(), "rotation": angle, "height": height,
                             "bounds": box.tolist(), "placement": placement})

    def station(self, curve, bounds, height, rank, count):
        points = curve["points"]
        if len(points) < 2:
            return False
        width = self.metrics.envelope(_texts(curve), height) + height*.45
        # Quantiles stagger coincident stations; geometry rather than station numbers sets scale.
        target = curve.get("target_fraction", (rank + .5) / max(count, 1))
        y_range = np.ptp(points[:, 1])
        fraction = (points[:, 1]-points[:, 1].min())/y_range if y_range else np.linspace(0, 1, len(points))
        indices = sorted(range(1, len(points)-1), key=lambda i: (abs(fraction[i]-target), i))
        side = curve["side"] or 1
        candidates = []
        for index in indices:
            tangent = points[index+1] - points[index-1]
            if np.linalg.norm(tangent) < 1e-12:
                continue
            angle = math.degrees(math.atan2(tangent[1], tangent[0]))
            if angle > 90:
                angle -= 180
            if angle < -90:
                angle += 180
            theta = math.radians(angle)
            normal = np.array([-math.sin(theta), math.cos(theta)])
            if normal[0]*side < 0:
                normal = -normal
            for distance in (1.05, 1.8, 2.8):
                center = points[index]+normal*height*distance
                box = self.clear(center, angle, width, height)
                if box is None:
                    continue
                margin = max(bounds[2]-bounds[0], bounds[3]-bounds[1])*.12
                if (box[:2] < bounds[:2]-margin).any() or (box[2:] > bounds[2:]+margin).any():
                    continue
                clearance = self.tree.query(center)[0] if self.tree else height
                score = min(clearance/height, 2.5) - abs(fraction[index]-target)*3 - distance*.08
                candidates.append((score, -index, center, angle, box))
            if len(candidates) > 24:
                break
        if not candidates:
            return False
        _, _, center, angle, box = max(candidates, key=lambda item: item[:2])
        self.emit(curve, center, angle, height, box)
        return True

    def leader(self, curve, bounds, height, direction, slot, placement="leader"):
        points = curve["points"]
        if len(points) == 1:
            tips = [points[0]]
        else:
            endpoint = 0 if points[0, 0]*direction > points[-1, 0]*direction else -1
            # Attach near the actual end, rather than at an assumed longitudinal station.
            near = max(1, int(len(points)*.035))
            tips = [points[near if endpoint == 0 else -near-1],
                    points[-near-1 if endpoint == 0 else near]]
            if placement == "station_leader_fallback":
                tips.extend(points[int((len(points)-1)*fraction)] for fraction in (.15, .85, .35, .65))
        width = self.metrics.envelope(_texts(curve), height) + height*.5
        span = max(bounds[2]-bounds[0], bounds[3]-bounds[1], height)
        edge = bounds[2] if direction > 0 else bounds[0]
        attempts = int(self.config.get("max_label_attempts", 160))
        for attempt in range(attempts):
            step = (attempt+1)//2 * (1 if attempt % 2 else -1)
            y = slot + step*height*1.85
            column = attempt // 32
            knee = np.array([edge+direction*(span*.04+column*(width+height*4)), y])
            end = knee+np.array([direction*max(span*.025, height*2), 0])
            center = end+np.array([direction*(width/2+height*.65), 0])
            box = self.clear(center, 0, width, height)
            if box is None:
                continue
            for tip in tips:
                if any(_crosses_box(a, b, other) for a, b in ((tip, knee), (knee, end)) for other in self.boxes):
                    continue
                self.emit(curve, center, 0, height, box, (tip, knee, end), placement)
                return True
        return False


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
    metrics = _Metrics(doc, config)
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
