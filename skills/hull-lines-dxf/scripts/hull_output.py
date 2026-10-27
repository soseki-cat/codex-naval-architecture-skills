"""DXF table, signature and preview rendering helpers."""

from __future__ import annotations

from ezdxf.enums import TextEntityAlignment
import numpy as np


def table(w, title, headers, rows, xy, font, width_headers=None):
    layout_headers = width_headers or headers
    widths = [
        max(
            8,
            len(str(h)) * 0.8 + 3,
            max((len(str(r[i])) * 0.75 + 3 for r in rows), default=8),
        )
        * font
        for i, h in enumerate(layout_headers)
    ]
    edge = np.r_[xy[0], xy[0] + np.cumsum(widths)]
    rh = font * 3
    w.layer("DATA_TABLE_GRID", 8)
    w.layer("DATA_TABLE_TEXT", 7)
    for xx in edge:
        w.ms.add_line(
            (xx, xy[1], 0),
            (xx, xy[1] - (len(rows) + 1) * rh, 0),
            dxfattribs={"layer": "DATA_TABLE_GRID"},
        )
    for i in range(len(rows) + 2):
        w.ms.add_line(
            (edge[0], xy[1] - i * rh, 0),
            (edge[-1], xy[1] - i * rh, 0),
            dxfattribs={"layer": "DATA_TABLE_GRID"},
        )
    w.text(title, (xy[0], xy[1] + font * 3.5), font * 1.8)
    for i, row in enumerate([headers] + rows):
        for j, value in enumerate(row):
            entity = w.ms.add_text(
                str(value),
                dxfattribs={
                    "layer": "DATA_TABLE_TEXT",
                    "style": "HULL_FONT",
                    "height": font,
                },
            )
            entity.set_placement(
                ((edge[j] + edge[j + 1]) / 2, xy[1] - (i + 0.5) * rh, 0),
                align=TextEntityAlignment.MIDDLE_CENTER,
            )
    return xy[1] - (len(rows) + 1) * rh - font * 6


def geometry_signature(document):
    data = []
    for entity in document.modelspace():
        kind = entity.dxftype()
        if kind == "SPLINE":
            value = (np.array(entity.control_points).tolist(), list(entity.knots))
        elif kind == "POINT":
            value = tuple(entity.dxf.location)
        elif kind == "LINE":
            value = (tuple(entity.dxf.start), tuple(entity.dxf.end))
        elif kind == "LWPOLYLINE":
            value = list(entity.get_points())
        elif kind == "SOLID":
            value = tuple(tuple(entity.dxf.get(f"vtx{i}")) for i in range(4))
        elif kind == "CIRCLE":
            value = (tuple(entity.dxf.center), entity.dxf.radius)
        else:
            continue
        data.append((kind, entity.dxf.layer, str(value), entity.dxf.get("color", 256)))
    return data


def render(document, path):
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend, RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend

    fig = plt.figure(figsize=(17, 10), facecolor="black")
    ax = fig.add_axes([0.02, 0.02, 0.96, 0.96])
    Frontend(RenderContext(document), MatplotlibBackend(ax)).draw_layout(
        document.modelspace(), finalize=True
    )
    fig.savefig(path, dpi=150, facecolor="black")
    plt.close(fig)
