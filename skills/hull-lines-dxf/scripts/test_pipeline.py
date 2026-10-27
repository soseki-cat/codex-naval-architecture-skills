import csv
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

import ezdxf
import numpy as np

SCRIPT = Path(__file__).with_name("generate_hull_lines.py")


class PipelineTests(unittest.TestCase):
    def build(self, params=None, profile=None, deck=None, transom=None, corrections=None, skeleton=False):
        temp=tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        root=Path(temp.name)
        (root/"half.csv").write_text("station,WL0,WL1,WL2\n0,0,500,1000\n1,1000,1500,2000\n2,0,500,1000\n",encoding="utf-8")
        config={
            "waterline_heights_m":[0,1,2],
            "half_breadth_to_m":.001,
            "LBP_m":20,
            "station_AP":0,
            "station_FP":2,
            "languages":["zh","en"],
        }
        config.update(params or {})
        (root/"params.json").write_text(json.dumps(config),encoding="utf-8")
        cmd=[sys.executable,str(SCRIPT),"--csv",str(root/"half.csv"),"--config",str(root/"params.json"),"--out",str(root/"out")]
        if skeleton:cmd.append("--skeleton3d")
        for flag,value,name in [("--profile-csv",profile,"profile.csv"),("--deck-csv",deck,"deck.csv"),
                                ("--transom-json",transom,"transom.json"),("--corrections",corrections,"corrections.json")]:
            if value is not None:
                (root/name).write_text(json.dumps(value) if isinstance(value,(dict,list)) else value,encoding="utf-8")
                cmd += [flag,str(root/name)]
        result=subprocess.run(cmd,capture_output=True,text=True,encoding="utf-8")
        return result,root/"out"

    def test_explicit_two_languages_include_tables_and_curve_labels(self):
        result,out=self.build()
        self.assertEqual(result.returncode,0,result.stderr)
        for language in ["Chinese","English"]:
            self.assertTrue((out/f"hull_lines_{language}.dxf").exists())
            d=ezdxf.readfile(out/f"hull_lines_{language}.dxf")
            self.assertTrue(any("TABLE" in e.dxf.layer for e in d.modelspace().query("LINE")))
            self.assertTrue(any("ANN_" in e.dxf.layer for e in d.modelspace().query("TEXT")))
            for entity in d.modelspace():
                if entity.has_xdata("HULLANNOT"):
                    meta=json.loads("".join(t.value for t in entity.get_xdata("HULLANNOT") if t.code==1000))
                    self.assertEqual(d.entitydb[meta["source_handle"]].dxf.layer,meta["source_layer"])
            self.assertTrue((out/language/"body_plan.dxf").exists())
        report=json.loads((out/"validation.json").read_text())
        self.assertEqual(report["languages"],["zh","en"])
        self.assertTrue(report["language_geometry_identical"])

    def test_language_must_be_explicit(self):
        result,out=self.build(params={"languages":None})
        self.assertNotEqual(result.returncode,0)
        self.assertIn("languages must be set explicitly",result.stderr)
        self.assertFalse(list(out.glob("*.dxf")) if out.exists() else [])

    def test_bilingual_files_keep_title_languages_independent(self):
        result,out=self.build()
        self.assertEqual(result.returncode,0,result.stderr)
        zh=ezdxf.readfile(out/"hull_lines_Chinese.dxf")
        en=ezdxf.readfile(out/"hull_lines_English.dxf")
        zh_text={e.dxf.text for e in zh.modelspace().query("TEXT")}
        en_text={e.dxf.text for e in en.modelspace().query("TEXT")}
        self.assertIn("横剖面图",zh_text)
        self.assertIn("WATERLINE PLAN",en_text)
        self.assertNotIn("BODY PLAN",zh_text)
        self.assertNotIn("水线面图",en_text)

    def test_direct_profile_and_deck_and_transom_are_used_without_invented_x(self):
        result,out=self.build(profile="station,CL,500BL\n0,0,500\n1,0,0\n2,0,600\n",
                              deck="station,UPPER_DECK\n0,1100\n1,2100\n2,1100\n",
                              transom={"waterline_half_breadths_mm":{"WL1":750,"WL2":900},"buttock_height_mm":{"500BL":500},"longitudinal_position":None})
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads((out/"validation.json").read_text())
        self.assertEqual(report["profile_source"],"given")
        profile=ezdxf.readfile(out/"Chinese"/"longitudinal_sections.dxf")
        spline=list(profile.modelspace().query('SPLINE[layer=="BL_500"]'))[0]
        pts=np.array(spline.control_points)
        self.assertAlmostEqual(pts[0,1],.5)
        self.assertAlmostEqual(pts[-1,1],.6)
        body=ezdxf.readfile(out/"Chinese"/"body_plan.dxf")
        tc=list(body.modelspace().query('SPLINE[layer=="TRANSOM_REFERENCE"]'))[0]
        self.assertAlmostEqual(tc.control_points[0][1],.5)
        self.assertAlmostEqual(abs(tc.control_points[0][0]),.5)
        plan=ezdxf.readfile(out/"Chinese"/"waterline_plan.dxf")
        self.assertTrue(plan.layers.get("DECK_PROJECTION_UPPER_DECK").is_off())
        inventory=json.loads((out/"data_inventory.json").read_text())
        self.assertTrue(any(c["source"]=="transom" and "body" in c["uses"] for c in inventory))
        ann=report["annotations"]["zh"]["profile"]
        self.assertEqual(ann["label_counts"]["profile"],2)  # CL/BP curves; connected nodes are not isolated labels

    def test_transom_deck_literals_are_visible_in_table_without_deck_body_claim(self):
        result,out=self.build(transom={"waterline_half_breadths_mm":{"WL1":750,"WL2":900},
                                      "upper_deck_half_breadth_mm":950,"CL_raw":"300/450"})
        self.assertEqual(result.returncode,0,result.stderr)
        d=ezdxf.readfile(out/"hull_lines_Chinese.dxf")
        texts=[e.dxf.text for e in d.modelspace().query("TEXT")]
        self.assertIn("300/450",texts)
        self.assertIn("950",texts)
        inventory=json.loads((out/"data_inventory.json").read_text())
        deck=next(c for c in inventory if c["field"]=="upper_deck_half_breadth_mm")
        self.assertEqual(deck["uses"],["table"])

    def test_atomic_failed_correction_keeps_original_visible_data_and_reports_failure(self):
        result,out=self.build(corrections={"targets":[{"station":1,"column":"WL1"},{"station":0,"column":"WL2"}]})
        self.assertEqual(result.returncode,0,result.stderr)
        report=json.loads((out/"validation.json").read_text())
        self.assertEqual(report["correction_report"]["status"],"not_applied")
        with (out/"offsets_effective.csv").open() as f: rows=list(csv.DictReader(f))
        self.assertEqual(rows[1]["WL1"],"1500")

    def test_uninterpreted_profile_text_remains_in_embedded_table_and_inventory(self):
        result,out=self.build(profile="station,CL,500BL\n0,0,500\n1,0,500/800\n2,0,2.0E+12\n")
        self.assertEqual(result.returncode,0,result.stderr)
        d=ezdxf.readfile(out/"hull_lines_Chinese.dxf")
        text=[e.dxf.text for e in d.modelspace().query("TEXT")]
        self.assertIn("500/800",text)
        self.assertIn("2.0E+12",text)
        cells=json.loads((out/"data_inventory.json").read_text())
        self.assertTrue(any(c["raw"]=="2.0E+12" and c["status"]=="needs_interpretation" for c in cells))

    def test_given_profile_wins_and_only_absent_requested_plane_is_derived(self):
        result,out=self.build(params={"buttock_half_breadths_m":[.5,.75]},
                              profile="station,CL,500BL\n0,0,500\n1,0,0\n2,0,600\n")
        self.assertEqual(result.returncode,0,result.stderr)
        d=ezdxf.readfile(out/"Chinese"/"longitudinal_sections.dxf")
        self.assertEqual(len(d.modelspace().query('SPLINE[layer=="BP_0p5"]')),0)
        self.assertTrue(len(d.modelspace().query('SPLINE[layer=="BP_0p75"]'))>0)
        self.assertEqual(len(d.modelspace().query('SPLINE[layer=="BL_500"]')),1)
        report=json.loads((out/"validation.json").read_text())
        self.assertEqual(report["source_profile_planes_m"],[0,.5])

    def test_physical_model_retains_direct_profile_points_and_unknown_transom_stays_2d(self):
        result,out=self.build(params={"mirror_3d":True},skeleton=True,
                              profile="station,CL,500BL\n0,0,500\n1,0,0\n2,0,600\n",
                              transom={"waterline_half_breadths_mm":{"WL1":750,"WL2":900},"longitudinal_position":None})
        self.assertEqual(result.returncode,0,result.stderr)
        d=ezdxf.readfile(out/"hull_skeleton_3d.dxf")
        self.assertEqual(len(d.modelspace().query('SPLINE[layer=="BL_500"]')),2)
        self.assertEqual(len(d.modelspace().query('SPLINE[layer=="CL_SOURCE"]')),1)
        self.assertEqual(len(d.modelspace().query('POINT[layer=="SOURCE_PROFILE"]')),9)
        self.assertEqual(len(d.modelspace().query('POINT[layer=="SOURCE_TRANSOM"]')),0)


if __name__=="__main__":
    unittest.main()
