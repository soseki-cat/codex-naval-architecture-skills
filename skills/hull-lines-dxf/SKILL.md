---
name: hull-lines-dxf
description: Use when a user provides symmetric hull offsets, 型值表截图, mixed waterline/deck half-breadths or profile heights and requests 型线图, bilingual DXF body/waterline/profile views, a Rhino curve skeleton, or annotation-only updates of existing hull-lines DXF. Includes source-data and coordinate verification. Does not reconstruct unmeasured boundaries or build/fair hull surfaces by default.
---

# 船舶型值表 → CAD 型线图

从可核对的截图、型值表或测量数据生成 DXF 型线图，保存来源、原始点、计算值及假设。用户当前指定的单位、比例、语言、格式与授权范围优先；示例资产仅供示范，不能借用其船长、站位或形状。

## 先核对来源

读取实际附件，先区分水线半宽、甲板半宽、纵剖高度和 TRANSOM 数据。附件无法读取时请求补充；模糊单元格保留未知，不靠参考图猜数。真实零值与缺失值分开，斜杠、残缺字符和科学计数法原文均保留。有限、尺度合理的科学计数法可解析；可疑尺度需解释。输入格式、纵向比例和缺失数据边界见 [输入数据](references/input-data.md)。

坐标原点不等于曲线端点；CL 不能强制补零或封口。纵向物理尺度未知时保留站号坐标，展示倍数不代表米或真实站距。源 BL 高度优先；缺失 BL 仅在配置平面与数据支持域内推导。甲板只有半宽时只可生成可选的默认关闭平面投影；TRANSOM 无 X 时可单独画横剖面。失败的推导不妨碍交付可用源视图。

## 根据授权生成

默认交付完整中文、英文各一套：独立三视图及合并图、图内网格数据表、逐曲线颜色、随线站号和 WL/BP 引线。显式用户选择覆盖默认；不自动生成 Excel、完整中纵剖外形、曲面或封闭实体。

原始点保留，已知连续段使用保形 PCHIP（C1）并保存为原生 SPLINE；不得跨未知空段连线，也不能将插值称作工程光顺。局部修订必须有明确单元格授权，批次排除全部目标后估算，独立横剖检核与修订台账见 [局部拟合](references/local-fitting.md)。

```text
python <skill>/scripts/generate_hull_lines.py --csv <offsets.csv> --config <parameters.json> --out <output-dir> --preview
```

原有 `--csv --config --out --skeleton3d --preview` 保持兼容；新可选 `--profile-csv --deck-csv --transom-json --corrections` 见输入参考。有物理纵向坐标且请求骨架时才使用 `--skeleton3d`。图层、表格、字体、输出和仅标注更新流程见 [CAD 制图与交付](references/cad-drafting.md)。

## 检查与交付

回读本次 DXF，检查结构审查、曲线/原始点、单位、站位、镜像、插值误差、计算域、颜色、表格及标注；检查预览的缺字、重叠和截断。报告输出清单、修订台账、文件审查及字体状态。只按真实证据报告 AutoCAD/Rhino 验证；[Rhino 核对](references/rhino-verification.md) 规定物理坐标与交点分类。

使用 UTF-8 保存中文配置、CSV、说明和报告。附输入副本、参数、验证报告及必要预览，并说明尺度依据、估算状态和缺失数据。AutoCAD 可用 `OPEN` 打开，`Z` → `E` 显示全图，`SAVEAS` 保存 DWG。文件存在不等于全部曲线已完成；原生软件未实测时明确报告仅完成文件/数值检查。
