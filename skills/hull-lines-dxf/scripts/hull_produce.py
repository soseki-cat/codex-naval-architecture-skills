"""Assemble bilingual DXF deliverables and auditable reports."""

from __future__ import annotations

import csv
import json
from pathlib import Path
import shutil
import tempfile

import ezdxf
from ezdxf import zoom
from ezdxf.math import Matrix44
import numpy as np

from hull_drafting import (
    _transom_values,
    build_geometry,
    fonts,
    imported_writer,
    make_writer,
    tr,
)
from hull_output import geometry_signature, render, table


def produce(
    bundle,
    csv_path,
    config_path,
    out,
    skeleton=False,
    preview=False,
    extra_sources=None,
):
    from hull_annotations import annotate

    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    base, model, base_report = build_geometry(
        bundle, csv_path, config_path, skeleton
    )
    supplemental = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, writer in list(base.items()) + (
            [("model", model)] if model else []
        ):
            supplemental.append(
                writer.save_checked(Path(tmp) / (name + ".dxf"))
            )
    font_report = fonts(bundle.params)
    languages = bundle.params.get("languages")
    if languages is None:
        raise ValueError(
            "languages must be set explicitly to the language of the user's "
            "request, or to both only when a bilingual deliverable was requested"
        )
    if (
        not languages
        or len(set(languages)) != len(languages)
        or any(language not in ["zh", "en"] for language in languages)
    ):
        raise ValueError("languages must be a nonempty subset of ['zh','en']")
    files = {}
    annotation_reports = {}
    signatures = []
    max_b = float(np.nanmax(bundle.b)) if np.isfinite(bundle.b).any() else 1.0
    body_span = max(1.0, 2 * max_b, float(bundle.z[-1] - bundle.z[0]))
    body_y = max_b * 1.4 + body_span * 0.8
    profile_y = body_y + (bundle.z[-1] - bundle.z[0]) + body_span * 0.8
    x0 = float(bundle.x[0])
    xspan = float(bundle.x[-1] - bundle.x[0])
    config = dict(bundle.params)
    for language, info in font_report.items():
        if info["path"]:
            config[f"font_path_{language}"] = info["path"]
    for language in languages:
        dirname = "Chinese" if language == "zh" else "English"
        folder = out / dirname if len(languages) > 1 else out
        folder.mkdir(exist_ok=True)
        views = {}
        annotation_reports[language] = {}
        for kind, source in base.items():
            with tempfile.TemporaryDirectory() as tmp:
                source.doc.saveas(Path(tmp) / "base.dxf")
                writer = imported_writer(Path(tmp) / "base.dxf")
            writer.doc.styles.get("HULL_FONT").dxf.font = font_report[language][
                "dxf_font"
            ]
            ytop = bundle.z[-1] if kind != "waterline" else max_b * 1.15
            textsize = (
                body_span / 55 if kind == "body" else max(0.05, xspan / 220)
            )
            start_x = -max_b if kind == "body" else x0
            other_notes = []

            def shared_note(texts, position, height):
                for candidate in ["zh", "en"]:
                    writer.text(texts[candidate], position, height)
                    if candidate != language:
                        other_notes.append(list(writer.ms)[-1])

            shared_note(
                {lang: tr(lang, kind) for lang in ["zh", "en"]},
                (start_x, ytop + textsize * 4),
                textsize * 1.7,
            )
            captions = {
                "zh": (
                    "半宽与高度按米；X为实际给定站位。"
                    if bundle.physical
                    else "半宽与高度按米；X为站号展示坐标，非实际距离。"
                ),
                "en": (
                    "Breadth/height in m; X uses supplied physical positions."
                    if bundle.physical
                    else "Breadth/height in m; X is a station display coordinate, "
                    "not a measured distance."
                ),
            }
            if kind == "body":
                captions = {
                    "zh": "半宽与高度按米；基线原点不是强制的型线端点。",
                    "en": "Breadth/height in m; baseline origin is not a forced hull endpoint.",
                }
            shared_note(
                captions, (start_x, ytop + textsize * 2), textsize
            )
            writer.layer("GRID_LABELS", 7)
            if kind == "body":
                for zz in bundle.z:
                    writer.ms.add_text(
                        f"WL{zz:g}",
                        dxfattribs={
                            "layer": "GRID_LABELS",
                            "style": "HULL_FONT",
                            "height": textsize * 0.75,
                            "insert": (
                                max_b * 1.1 + body_span * 0.15,
                                zz,
                                0,
                            ),
                        },
                    )
            else:
                bottom = -max_b * 1.1 if kind == "waterline" else float(
                    bundle.z[0]
                )
                for xx, station in zip(bundle.x, bundle.stations):
                    writer.ms.add_text(
                        f"{station:g}",
                        dxfattribs={
                            "layer": "GRID_LABELS",
                            "style": "HULL_FONT",
                            "height": textsize * 0.75,
                            "insert": (xx, bottom - textsize * 2, 0),
                        },
                    )
            if (
                kind == "profile"
                and bundle.profile_values is None
                and base_report["buttock_status"] != "generated"
            ):
                shared_note(
                    {
                        "zh": "纵剖线未生成：" + base_report["buttock_status"],
                        "en": "No derived buttocks: "
                        + base_report["buttock_status"],
                    },
                    (start_x, bundle.z[0] - textsize * 4),
                    textsize,
                )
            if bundle.params.get("annotations", True):
                annotation_reports[language][kind] = annotate(
                    writer.doc, language=language, config=config
                )
            for note in other_notes:
                writer.ms.delete_entity(note)
            filename = {
                "body": "body_plan.dxf",
                "waterline": "waterline_plan.dxf",
                "profile": "longitudinal_sections.dxf",
            }[kind]
            zoom.extents(writer.ms)
            writer.doc.saveas(folder / filename)
            document = ezdxf.readfile(folder / filename)
            audit = document.audit()
            if audit.errors or audit.fixes:
                raise AssertionError(f"DXF audit: {filename}")
            files[str((folder / filename).relative_to(out))] = {
                "audit_errors": 0,
                "audit_fixes": 0,
                "splines": len(document.modelspace().query("SPLINE")),
                "points": len(document.modelspace().query("POINT")),
            }
            views[kind] = writer
        combined = make_writer()
        combined.doc.units = 6 if bundle.physical else 0
        combined.doc.styles.get("HULL_FONT").dxf.font = font_report[language][
            "dxf_font"
        ]
        for kind, delta, prefix in [
            ("body", (x0 + max_b * 1.2, body_y, 0), "BODY_"),
            ("waterline", (0, 0, 0), "PLAN_"),
            ("profile", (0, profile_y, 0), "PROFILE_"),
        ]:
            source = views[kind]
            handles = {}
            copied_entities = []
            for layer in source.doc.layers:
                combined.layer(prefix + layer.dxf.name, abs(layer.dxf.color))
                if layer.is_off():
                    combined.doc.layers.get(prefix + layer.dxf.name).off()
            for app in source.doc.appids:
                if app.dxf.name not in combined.doc.appids:
                    combined.doc.appids.new(app.dxf.name)
            for entity in source.ms:
                copied = entity.copy()
                copied.dxf.layer = prefix + entity.dxf.layer
                copied.transform(Matrix44.translate(*delta))
                combined.ms.add_entity(copied)
                handles[entity.dxf.handle] = copied.dxf.handle
                copied_entities.append(copied)
            for copied in copied_entities:
                if copied.has_xdata("HULLANNOT"):
                    metadata = json.loads(
                        "".join(
                            item.value
                            for item in copied.get_xdata("HULLANNOT")
                            if item.code == 1000
                        )
                    )
                    if (
                        metadata.get("generated_by") == "hull-lines-dxf"
                        and metadata.get("kind") == "curve_label"
                    ):
                        metadata["source_layer"] = (
                            prefix + metadata["source_layer"]
                        )
                        if "source_handle" in metadata:
                            metadata["source_handle"] = handles[
                                metadata["source_handle"]
                            ]
                        value = json.dumps(metadata, separators=(",", ":"))
                        copied.set_xdata(
                            "HULLANNOT",
                            [
                                (1000, value[index : index + 240])
                                for index in range(0, len(value), 240)
                            ],
                        )
        if bundle.params.get("embedded_tables", True):
            table_font = max(0.02, body_span * 0.013)
            table_x = float(bundle.x[-1]) + body_span * 1.6
            profile_top = (
                float(np.nanmax(bundle.profile_values))
                if bundle.profile_values is not None
                and np.isfinite(bundle.profile_values).any()
                else 0
            )
            table_top = (
                profile_y
                + max(float(bundle.z[-1]), profile_top)
                + body_span * 0.7
            )
            half_rows = [
                [row["station"]] + [row[field] for field in bundle.fields]
                for row in bundle.rows_effective
            ]
            if bundle.transom:
                values = bundle.transom.get(
                    "waterline_half_breadths_raw",
                    bundle.transom.get("waterline_half_breadths_mm", {}),
                )
                half_rows.insert(
                    0,
                    ["TRANSOM"]
                    + [str(values.get(field, "-")) for field in bundle.fields],
                )
            station_header = "站号" if language == "zh" else "station"
            table_top = table(
                combined,
                tr(language, "half_table")
                + ("（原表单位）" if language == "zh" else " (source units)"),
                [station_header] + bundle.fields,
                half_rows,
                (table_x, table_top),
                table_font,
                ["station"] + bundle.fields,
            )
            if bundle.deck_rows:
                table_top = table(
                    combined,
                    tr(language, "deck_table"),
                    ["station"] + bundle.deck_fields,
                    [
                        [row["station"]]
                        + [row[field] for field in bundle.deck_fields]
                        for row in bundle.deck_rows
                    ],
                    (table_x, table_top),
                    table_font,
                )
            if bundle.profile_rows:
                table_top = table(
                    combined,
                    tr(language, "profile_table"),
                    ["station"] + bundle.profile_fields,
                    [
                        [row["station"]]
                        + [row[field] for field in bundle.profile_fields]
                        for row in bundle.profile_rows
                    ],
                    (table_x, table_top),
                    table_font,
                )
            transom_cells = [
                cell for cell in bundle.inventory if cell["row"] == "TRANSOM"
            ]
            if transom_cells:
                headers = (
                    ["来源", "字段", "原文", "米制解释", "状态"]
                    if language == "zh"
                    else ["source", "field", "raw", "interpreted m", "status"]
                )
                rows = [
                    [
                        cell["source"],
                        cell["field"],
                        cell["raw"],
                        str(cell["value_m"])
                        if cell["value_m"] is not None
                        else "-",
                        cell["status"],
                    ]
                    for cell in transom_cells
                ]
                table_top = table(
                    combined,
                    tr(language, "transom_table"),
                    headers,
                    rows,
                    (table_x, table_top),
                    table_font,
                    ["source", "field", "raw", "interpreted m", "status"],
                )
            if bundle.correction_report["targets"]:
                rows = [
                    [
                        f"{record['station']:g}",
                        record["column"],
                        record["original_raw"],
                        record["fitted_raw"],
                        "estimate" if record.get("applied") else "not applied",
                    ]
                    for record in bundle.correction_report["targets"]
                ]
                table(
                    combined,
                    tr(language, "correction_table"),
                    ["station", "field", "original", "drawing", "status"],
                    rows,
                    (table_x, table_top),
                    table_font,
                )
            for cell in bundle.inventory:
                if "table" not in cell["uses"]:
                    cell["uses"].append("table")
        if bundle.correction_report["status"] == "not_applied":
            combined.text(
                (
                    "修正批次未应用："
                    if language == "zh"
                    else "Correction batch not applied: "
                )
                + "; ".join(bundle.correction_report["failures"]),
                (x0, profile_y + body_span * 1.1),
                body_span * 0.02,
            )
        combined_name = (
            f"hull_lines_{dirname}.dxf"
            if len(languages) > 1
            else "three_views_combined.dxf"
        )
        zoom.extents(combined.ms)
        combined.doc.saveas(out / combined_name)
        document = ezdxf.readfile(out / combined_name)
        audit = document.audit()
        if audit.errors or audit.fixes:
            raise AssertionError(f"DXF audit {combined_name}")
        files[combined_name] = {
            "audit_errors": 0,
            "audit_fixes": 0,
            "splines": len(document.modelspace().query("SPLINE")),
            "points": len(document.modelspace().query("POINT")),
        }
        signatures.append(geometry_signature(document))
        if preview:
            render(document, out / f"preview_{dirname}.png")
            font_report[language]["preview_rendered"] = True
    identical = all(signature == signatures[0] for signature in signatures)
    if not identical:
        raise AssertionError(
            "Language versions differ in geometry/layout"
        )
    if model:
        model.doc.saveas(out / "hull_skeleton_3d.dxf")
        reread = ezdxf.readfile(out / "hull_skeleton_3d.dxf")
        audit = reread.audit()
        if audit.errors or audit.fixes:
            raise AssertionError("3D DXF audit")
        files["hull_skeleton_3d.dxf"] = {
            "audit_errors": 0,
            "audit_fixes": 0,
            "splines": len(reread.modelspace().query("SPLINE")),
            "points": len(reread.modelspace().query("POINT")),
        }
    if csv_path.resolve() != (out / "offsets_source.csv").resolve():
        shutil.copyfile(csv_path, out / "offsets_source.csv")
    if config_path.resolve() != (out / "parameters_source.json").resolve():
        shutil.copyfile(config_path, out / "parameters_source.json")
    with (out / "offsets_effective.csv").open(
        "w", newline="", encoding="utf-8"
    ) as stream:
        writer = csv.DictWriter(
            stream, fieldnames=["station"] + bundle.fields
        )
        writer.writeheader()
        writer.writerows(bundle.rows_effective)
    for name, path in (extra_sources or {}).items():
        if path:
            shutil.copyfile(path, out / name)
    report = dict(base_report)
    report.update(
        files=files,
        languages=languages,
        language_geometry_identical=identical,
        profile_source="given" if bundle.profile_values is not None else "derived",
        station_x=bundle.x.tolist(),
        x_mode="physical_m" if bundle.physical else "station_display",
        x_mapping=bundle.x_note,
        correction_report=bundle.correction_report,
        annotations=annotation_reports,
        fonts=font_report,
        supplementary_interpolation_error=max(
            result["all_interpolation_error"] for result in supplemental
        ),
        source_unit_evidence=bundle.params.get(
            "unit_evidence", bundle.params.get("unit_status", "not supplied")
        ),
        estimated_cell_count=sum(
            bool(record.get("applied"))
            for record in bundle.correction_report["targets"]
        ),
        source_profile_point_count=(
            int(np.isfinite(bundle.profile_values).sum())
            if bundle.profile_values is not None
            else 0
        ),
        source_profile_planes_m=(
            [
                half_breadth
                for index, half_breadth in enumerate(bundle.profile_half_widths)
                if np.isfinite(bundle.profile_values[:, index]).any()
            ]
            if bundle.profile_values is not None
            else []
        ),
        transom_anchor_count=len(_transom_values(bundle)),
        native_AutoCAD_check="not performed",
        native_Rhino_check="not performed",
    )
    (out / "validation.json").write_text(
        json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    (out / "data_inventory.json").write_text(
        json.dumps(bundle.inventory, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    (out / "correction_report.json").write_text(
        json.dumps(
            bundle.correction_report, indent=2, ensure_ascii=False
        ),
        encoding="utf-8",
    )
    (out / "OPEN_IN_CAD.txt").write_text(
        "AutoCAD: OPEN; Z then E for extents; SAVEAS for DWG.\n"
        + bundle.x_note
        + "\nTables use DXF lines/text, not an Excel link or native ACAD_TABLE.\n"
        + "Estimated corrections are not original measured offsets.\n"
        + "Native AutoCAD/Rhino testing has not been performed.\n",
        encoding="utf-8",
    )
    return report
