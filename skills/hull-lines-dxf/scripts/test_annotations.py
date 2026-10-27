"""Annotation contracts: original geometry, ownership and variable layouts."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import ezdxf
from ezdxf.lldxf.tagwriter import TagCollector

from hull_annotations import annotate


def tags(entity):
    writer = TagCollector(dxfversion="AC1032")
    entity.export_dxf(writer)
    return tuple((tag.code, str(tag.value)) for tag in writer.tags)


def owned(doc):
    result = []
    for entity in doc.modelspace():
        if entity.has_xdata("HULLANNOT"):
            meta = json.loads("".join(t.value for t in entity.get_xdata("HULLANNOT") if t.code == 1000))
            if meta.get("generated_by") == "hull-lines-dxf" and meta.get("kind") == "curve_label":
                result.append((entity, meta))
    return result


def fixture(scale=1, shift=(0, 0), count=7, prefix=""):
    doc = ezdxf.new("R2018")
    ms = doc.modelspace()
    def transform(points):
        return [(shift[0] + scale*x, shift[1] + scale*y, 0) for x, y in points]
    for i in range(count):
        layer = prefix + "ST_" + str(i*0.5).replace(".", "p")
        doc.layers.new(layer, dxfattribs={"color": 1 + i % 6})
        x = (i + 1) / count * 8
        entity = ms.add_spline(fit_points=transform([(x*.3, 0), (x*.7, 4), (x, 8)]),
                               dxfattribs={"layer": layer})
        if i == 1:
            entity.dxf.true_color = 0x125A94
    return doc


class AnnotationTests(unittest.TestCase):
    def test_reference_grid_does_not_force_station_labels_to_outside_leaders(self):
        doc=ezdxf.new("R2018");ms=doc.modelspace()
        doc.layers.new("ST_10");doc.layers.new("GRID")
        ms.add_spline(fit_points=[(1,0,0),(1,1,0),(1,2,0),(1,3,0)],dxfattribs={"layer":"ST_10"})
        grid=[ms.add_line((0,k*.1,0),(2,k*.1,0),dxfattribs={"layer":"GRID"}) for k in range(31)]
        originals=[tags(e) for e in grid]
        report=annotate(doc,"en",{"text_height":.2})
        self.assertEqual(report["labels"][0]["placement"],"inline")
        self.assertEqual([tags(e) for e in grid],originals)

    def test_new_labels_variable_station_count_scale_and_translation(self):
        for scale, shift, count, prefix in [(1, (0, 0), 7, ""), (.012, (-6, 3), 4, "BODY_"),
                                             (450, (9000, -2200), 11, "BODY_")]:
            with self.subTest(scale=scale, count=count):
                doc = fixture(scale, shift, count, prefix)
                report = annotate(doc, "en")
                self.assertEqual(report["label_counts"]["body"], count)
                self.assertEqual(report["unplaced"], [])
                self.assertEqual(len([e for e, _ in owned(doc) if e.dxftype() == "TEXT"]), count)
                self.assertTrue(all(-90 <= e.dxf.rotation <= 90 for e, _ in owned(doc) if e.dxftype() == "TEXT"))

    def test_preserves_every_original_entity_layer_and_style(self):
        doc = fixture()
        doc.layers.new("ANN_ST_INLINE", dxfattribs={"color": 2, "true_color": 0x123456})
        user_text = doc.modelspace().add_text("User annotation", dxfattribs={"layer": "ANN_ST_INLINE", "height": .2})
        doc.appids.new("HULLANNOT")
        user_text.set_xdata("HULLANNOT", [(1000, json.dumps({"generated_by": "another-tool", "kind": "curve_label"}))])
        originals = [(e, tags(e)) for e in doc.modelspace()]
        layers = [(e, tags(e)) for e in doc.layers]
        styles = [(e, tags(e)) for e in doc.styles]
        report = annotate(doc)
        self.assertEqual(report["unplaced"], [])
        for entity, before in originals + layers + styles:
            self.assertTrue(entity.is_alive)
            self.assertEqual(tags(entity), before)
        curve_colors = {e.dxf.layer: (e.dxf.get("true_color"), abs(doc.layers.get(e.dxf.layer).dxf.color))
                        for e in doc.modelspace().query("SPLINE")}
        for entity, meta in owned(doc):
            true_color, aci = curve_colors[meta["source_layer"]]
            self.assertEqual(entity.dxf.get("true_color"), true_color)
            self.assertEqual(entity.dxf.color, aci)

    def test_repeat_replaces_only_owned_entities_and_positions_are_stable(self):
        doc = fixture()
        doc.layers.new("ANN_USER")
        user = doc.modelspace().add_text("Keep me", dxfattribs={"layer": "ANN_USER", "insert": (40, 20), "height": .3})
        original = tags(user)
        first = annotate(doc, "en")
        positions = [(m["label_id"], e.dxftype(), tuple(e.dxf.insert) if e.dxftype() == "TEXT" else tags(e)[2:])
                     for e, m in owned(doc)]
        before_count = len(list(doc.modelspace()))
        second = annotate(doc, "en")
        self.assertEqual(first["label_counts"], second["label_counts"])
        self.assertEqual(before_count, len(list(doc.modelspace())))
        # Handles are intentionally replaced; the actual placements and stable label IDs agree.
        self.assertEqual([(m["label_id"], tuple(e.dxf.insert)) for e, m in owned(doc) if e.dxftype() == "TEXT"],
                         [(key, pos) for key, kind, pos in positions if kind == "TEXT"])
        self.assertEqual(tags(user), original)

    def test_mirrored_waterlines_split_profiles_and_explicit_source_points(self):
        doc = ezdxf.new("R2018")
        doc.appids.new("HULLCURVE")
        for side in [-1, 1]:
            doc.layers.new("PLAN_WL_2" + ("" if side == -1 else "_custom"))
            e = doc.modelspace().add_spline(fit_points=[(0, 0), (35, side*3), (80, side*1)],
                                            dxfattribs={"layer": "PLAN_WL_2" + ("" if side == -1 else "_custom")})
            e.set_xdata("HULLCURVE", [(1000, json.dumps({"view": "waterline", "kind": "WL", "number": 2, "side": side}))])
        doc.layers.new("PROFILE_BP_0p4")
        for points in [[(0, 18), (9, 20)], [(60, 19), (80, 21)]]:
            e = doc.modelspace().add_spline(fit_points=points, dxfattribs={"layer": "PROFILE_BP_0p4"})
            e.set_xdata("HULLCURVE", [(1000, json.dumps({"view": "profile", "kind": "BP", "number": .4, "side": 1}))])
        doc.layers.new("SOURCE_POINTS")
        point = doc.modelspace().add_point((45, 20), dxfattribs={"layer": "SOURCE_POINTS"})
        point.set_xdata("HULLCURVE", [(1000, json.dumps({"view": "profile", "kind": "BP", "number": .7,
                                                       "side": 1, "source_point": True}))])
        report = annotate(doc, "en")
        self.assertEqual(report["label_counts"], {"body": 0, "waterline": 2, "profile": 3})
        self.assertEqual(report["unplaced"], [])
        text = [e.dxf.text for e, _ in owned(doc) if e.dxftype() == "TEXT"]
        self.assertTrue(any("segment 1/2" in t for t in text))
        self.assertTrue(any("segment 2/2" in t for t in text))
        self.assertTrue(any("isolated point" in t for t in text))

    def test_unknown_layers_skip_until_explicitly_mapped(self):
        doc = ezdxf.new()
        doc.layers.new("mystery")
        doc.modelspace().add_line((1, 0), (3, 4), dxfattribs={"layer": "mystery"})
        report = annotate(doc)
        self.assertEqual(sum(report["label_counts"].values()), 0)
        self.assertTrue(any(item["layer"] == "mystery" for item in report["skipped"]))
        report = annotate(doc, config={"layer_mapping": {"mystery": {"view": "body", "kind": "ST", "number": 5}}})
        self.assertEqual(report["label_counts"]["body"], 1)

    def test_source_bl_mm_split_segments_and_midship_coincident_labels(self):
        doc = ezdxf.new()
        doc.layers.new("LONG_BL_700")
        for points in [[(0, 20), (12, 23)], [(60, 26), (84, 27)]]:
            doc.modelspace().add_spline(fit_points=points, dxfattribs={"layer": "LONG_BL_700"})
        doc.layers.new("BODY_ST_4p5")
        doc.modelspace().add_lwpolyline([(8, 40), (9, 43), (9, 46)], dxfattribs={"layer": "BODY_ST_4p5"})
        doc.modelspace().add_lwpolyline([(8, 40), (9, 43), (9, 46)], dxfattribs={"layer": "BODY_ST_4p5"})
        report = annotate(doc, "en")
        self.assertEqual(report["label_counts"], {"body": 2, "waterline": 0, "profile": 2})
        self.assertEqual(report["unplaced"], [])
        texts = [e.dxf.text for e, _ in owned(doc) if e.dxftype() == "TEXT"]
        self.assertIn("BP0.7 (segment 1/2)", texts)
        self.assertIn("BP0.7 (segment 2/2)", texts)
        body = [label for label in report["labels"] if label["view"] == "body"]
        self.assertNotEqual(body[0]["position"][1], body[1]["position"][1])

    def test_leader_and_arrow_repeat_preserves_unowned_xdata(self):
        doc = ezdxf.new()
        doc.layers.new("WL_1")
        doc.modelspace().add_spline(fit_points=[(0, 0), (20, 2), (45, 1)], dxfattribs={"layer": "WL_1"})
        doc.appids.new("HULLANNOT")
        user = doc.modelspace().add_text("Keep", dxfattribs={"insert": (20, 10)})
        user.set_xdata("HULLANNOT", [(1000, json.dumps({"generated_by": "hull-lines-dxf", "kind": "title"}))])
        annotate(doc, "en")
        def placement(doc):
            values = []
            for e, meta in owned(doc):
                attributes = e.dxfattribs()
                attributes.pop("handle", None)
                attributes.pop("owner", None)
                values.append((meta, attributes, list(e.get_points()) if e.dxftype() == "LWPOLYLINE" else None))
            return values
        first, before = placement(doc), tags(user)
        annotate(doc, "zh")
        # Language changes the text and its selected font style only.
        second = placement(doc)
        for rows in (first, second):
            for _, attrs, _ in rows:
                attrs.pop("text", None)
                attrs.pop("style", None)
        self.assertEqual(first, second)
        self.assertEqual(tags(user), before)

    def test_too_crowded_labels_are_reported(self):
        doc = fixture(count=2)
        doc.modelspace().add_text("occupied", dxfattribs={"insert": (0, 0), "height": 100000})
        report = annotate(doc, config={"max_label_attempts": 1})
        self.assertEqual(report["label_counts"]["body"], 0)
        self.assertEqual(len(report["unplaced"]), 2)

    def test_coincident_midship_opposite_sides_receive_different_heights(self):
        doc = ezdxf.new()
        doc.layers.new("ST_5")
        doc.appids.new("HULLCURVE")
        for side in [-1, 1]:
            entity = doc.modelspace().add_spline(fit_points=[(0, 0), (0, 4), (0, 8)], dxfattribs={"layer": "ST_5"})
            entity.set_xdata("HULLCURVE", [(1000, json.dumps({"view": "body", "kind": "ST", "number": 5, "side": side}))])
        report = annotate(doc, "en")
        self.assertEqual(report["label_counts"]["body"], 2)
        self.assertNotEqual(report["labels"][0]["position"][1], report["labels"][1]["position"][1])

    def test_missing_font_reports_unverified_and_never_changes_styles(self):
        doc = fixture(count=3)
        before = [(e, tags(e)) for e in doc.styles]
        with patch("hull_annotations._system_fonts", return_value=()):
            report = annotate(doc, "zh")
        font = next(item for item in report["fonts"] if item["language"] == "zh")
        self.assertFalse(font["glyph_metrics_verified"])
        self.assertFalse(font["dxf_style_glyphs_verified"])
        self.assertIn("unverified", font["render_status"])
        for entity, snapshot in before:
            self.assertEqual(tags(entity), snapshot)

    def test_layer_truecolor_and_byblock_are_retained(self):
        doc = fixture(count=2)
        curves = list(doc.modelspace().query("SPLINE"))
        doc.layers.get(curves[0].dxf.layer).dxf.true_color = 0x22AABB
        curves[1].dxf.color = 0
        curves[1].dxf.discard("true_color")
        annotate(doc, "en")
        for entity, meta in owned(doc):
            if meta["source_layer"] == curves[0].dxf.layer:
                self.assertEqual(entity.dxf.true_color, 0x22AABB)
            else:
                self.assertEqual(entity.dxf.color, 0)
                self.assertIsNone(entity.dxf.get("true_color"))

    def test_known_curve_layers_do_not_label_legend_lines(self):
        doc = fixture(count=2)
        layer = list(doc.modelspace().query("SPLINE"))[0].dxf.layer
        doc.modelspace().add_line((0, -3), (1, -3), dxfattribs={"layer": layer})
        report = annotate(doc, "en")
        self.assertEqual(report["label_counts"]["body"], 2)
        self.assertTrue(any("legend" in item["reason"] for item in report["skipped"]))

    def test_languages_share_text_and_leader_geometry(self):
        left, right = fixture(), fixture()
        zh, en = annotate(left, "zh"), annotate(right, "en")
        self.assertEqual(zh["label_counts"], en["label_counts"])
        def layout(doc):
            return [(m["label_id"], e.dxftype(), tuple(e.dxf.insert), e.dxf.rotation, e.dxf.height)
                    if e.dxftype() == "TEXT" else (m["label_id"], e.dxftype(), tuple(e.get_points()))
                    if e.dxftype() == "LWPOLYLINE" else (m["label_id"], e.dxftype()) for e, m in owned(doc)]
        self.assertEqual(layout(left), layout(right))

    def test_cli_refuses_input_equals_output_and_writes_auditable_copy(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.dxf"
            output = Path(directory) / "annotated.dxf"
            fixture(count=3).saveas(source)
            source_doc = ezdxf.readfile(source)
            source_records = [(e.dxf.handle, tags(e)) for e in list(source_doc.modelspace())+
                              list(source_doc.layers)+list(source_doc.styles)]
            command = [sys.executable, str(Path(__file__).with_name("annotate_hull_lines.py")),
                       "--input", str(source), "--out"]
            refusal = subprocess.run(command + [str(source)], capture_output=True, text=True, encoding="utf-8")
            self.assertNotEqual(refusal.returncode, 0)
            result = subprocess.run(command + [str(output), "--language", "en"], capture_output=True, text=True, encoding="utf-8")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(json.loads(result.stdout)["label_counts"]["body"], 3)
            output_doc = ezdxf.readfile(output)
            for handle, before in source_records:
                self.assertEqual(tags(output_doc.entitydb[handle]), before)
            audit = output_doc.audit()
            self.assertFalse(audit.errors)
            self.assertFalse(audit.fixes)
            self.assertFalse(owned(ezdxf.readfile(source)))


if __name__ == "__main__":
    unittest.main()
