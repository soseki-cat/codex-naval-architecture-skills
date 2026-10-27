---
name: hull-lines-dxf
description: Use when a user provides or requests inspection, fitting, correction, or DXF drawing of symmetric hull offsets, 型值表截图, waterline/deck half-breadths, profile heights, or an existing hull-lines DXF. Audits anomalies before fitting, preserves source evidence, follows the request language, and stops before unapproved reconstruction.
---

# 船舶型值表 → CAD 型线图

从可核对的截图、型值表或测量数据生成 DXF 型线图，保存来源、原始点、计算值及假设。用户当前指定的单位、比例、语言、格式与授权范围优先；示例资产仅供示范，不能借用其船长、站位或形状。

## 执行门禁

先审计数据，再拟合，最后绘图：

1. 读取实际输入，确认表类型、单位、站号/高度方向、坐标轴、缺失值和文字语言。
2. 运行或等效执行 `scripts/audit_offsets.py`，检查不可解析值、尺度异常、同水线邻站突变、同站水线顺序反转和缺失段。审计阶段只报告，不修数据、不生成 DXF。
3. 发现实质性疑点时，停止绘图，向用户列出可疑站号/水线、原值、异常表现、可用的拟合方法和影响范围，并询问是原始数据有误、要求按拟合修复，还是用户将提供更正值。用户没有明确授权拟合或替换值时，不得自行修改。
4. 用户授权后才运行 `scripts/refit_waterlines.py`。局部异常使用授权清单；全表保序或去交叉修正是另一项需要明示的高影响拟合，必须先报告预计改动单元格数。
5. 拟合后核对未取整值、残差、横剖顺序、水线顺序和缺失段，再运行 `generate_hull_lines.py`。数据门禁未通过时，不得用“先画出来看看”代替确认；只有用户明确只要诊断草图时可以例外，并在图中标 `UNVERIFIED SOURCE`。

“审计完成”“拟合授权”和“绘图完成”是三个独立状态，不能合并成一次静默操作。完整判定方法见 [拟合与数据门禁](references/fitting-standards.md)。

## 语言规则

输出语言按以下优先级确定：

1. 用户明确指定的语言。
2. 用户当前请求的主要语言。
3. 主型值表、图纸或附录文字的主要语言。

单语请求默认只生成该语言，不额外输出另一语言。若仍无法判断，先询问用户。中文输入默认使用中文标题、表格、说明、报告和文件名；英文输入同理，不能把中文说明混入英文图纸或反向混入。

只有在用户明确要求双语，或产物是仓库/Agensi 等开源发布材料时，才提供完整中文、英文各一份。两套文件必须使用独立目录和独立命名，文字、字体和排版各自完成，不要在同一 DXF 中混排；几何、尺寸和源数据必须一致。详细规则见 [输出语言与双语交付](references/output-language.md)。

## 运行环境与依赖

本技能的生成器和标注器需要 Python 3.10 或更高版本，以及 `scripts/requirements.txt` 中列出的依赖。首次执行前运行 `python <skill>/scripts/check_environment.py`；若检查失败，说明缺少或被锁定的包，从同一依赖文件安装后重试，不得跳过检查并把导入错误当作几何失败。

脚本只应在用户有权读取输入、写入输出目录的环境中运行。生成器和标注器不需要联网；依赖安装可能需要用户授权网络访问。保留脚本原文运行，不把依赖目录、缓存或用户数据写回技能目录。

## 先核对来源

读取实际附件，先区分水线半宽、甲板半宽、纵剖高度和 TRANSOM 数据。附件无法读取时请求补充；模糊单元格保留未知，不靠参考图猜数。真实零值与缺失值分开，斜杠、残缺字符和科学计数法原文均保留。有限、尺度合理的科学计数法可解析；可疑尺度需解释。输入格式、纵向比例和缺失数据边界见 [输入数据](references/input-data.md)。

坐标原点不等于曲线端点；CL 不能强制补零或封口。纵向物理尺度未知时保留站号坐标，展示倍数不代表米或真实站距。源 BL 高度优先；缺失 BL 仅在配置平面与数据支持域内推导。甲板只有半宽时只可生成可选的默认关闭平面投影；TRANSOM 无 X 时可单独画横剖面。失败的推导不妨碍交付可用源视图。

## 根据授权生成

按语言规则交付用户请求语言的独立三视图及合并图、图内网格数据表、逐曲线颜色、随线站号和 WL/BP 引线。用户未要求双语时不自动追加另一语言；不自动生成 Excel、完整中纵剖外形、曲面或封闭实体。

原始点保留，已知连续段使用保形 PCHIP（C1）并保存为原生 SPLINE；不得跨未知空段连线，也不能将插值称作工程光顺。局部修订必须有明确单元格授权，批次排除全部目标后估算，独立横剖检核与修订台账见 [局部拟合](references/local-fitting.md)。

若用户明确要求水线不得相交，不能只修孤立异常点。先保留原表，再运行 `scripts/refit_waterlines.py` 对每站已知半宽做单调保序拟合并保留最小间距，生成新 CSV 和逐格台账；随后从新表生成 DXFs，并运行 `scripts/check_waterline_intersections.py` 检查同舷水线。相交数不为 0 时不得将该版标为完成。约束间距是绘图假设，不是实测误差或施工公差；多值外形应回到原始分段拓扑。详细方法和边界见 [水线保序重拟合](references/waterline-fairing.md)。

```text
python <skill>/scripts/generate_hull_lines.py --csv <offsets.csv> --config <parameters.json> --out <output-dir> --preview
```

原有 `--csv --config --out --skeleton3d --preview` 保持兼容；新可选 `--profile-csv --deck-csv --transom-json --corrections` 见输入参考。有物理纵向坐标且请求骨架时才使用 `--skeleton3d`。图层、表格、字体、输出和仅标注更新流程见 [CAD 制图与交付](references/cad-drafting.md)。

## 检查与交付

回读本次 DXF，检查结构审查、曲线/原始点、单位、站位、镜像、插值误差、计算域、颜色、表格及标注；检查预览的缺字、重叠和截断。报告输出清单、修订台账、文件审查及字体状态。只按真实证据报告 AutoCAD/Rhino 验证；[Rhino 核对](references/rhino-verification.md) 规定物理坐标与交点分类。

使用 UTF-8 保存中文配置、CSV、说明和报告。附输入副本、参数、验证报告及必要预览，并说明尺度依据、估算状态和缺失数据。AutoCAD 可用 `OPEN` 打开，`Z` → `E` 显示全图，`SAVEAS` 保存 DWG。文件存在不等于全部曲线已完成；原生软件未实测时明确报告仅完成文件/数值检查。

## 触发提示词

以下请求应进入本技能的“先审计、后绘图”流程：

- “看看这组型值表有没有突变，先不要画图。”
- “这张水线图不对，检查数据后告诉我哪些单元格要修，等我确认再拟合。”
- “按我确认的清单修正型值，然后生成中文型线图。”
- “Audit these offsets for spikes and crossings before fitting or drawing.”
- “Use my authorised correction table, then produce separate Chinese and English DXFs.”

“只检查”“只拟合”“只生成 DXF”分别到此阶段停止。更多正例、反例和应询问用户的写法见 [触发提示词](references/trigger-prompts.md)。
