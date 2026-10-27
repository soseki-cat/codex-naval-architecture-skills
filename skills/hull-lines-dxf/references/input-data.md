# 输入数据与参数

## 先分类，再转录

先在实际截图中划分水线半宽表、甲板半宽、纵剖 BL 高度与 TRANSOM 区域，再逐项核对站号、单位、列名、小数点和边缘字符。记录附件来源及原文。检测资料是否属于同一船型、站位体系、单位和版本；不兼容参考资料只能借用制图风格，不能借用主尺度、AP/FP 映射或曲线形状。

数值 `0` 是已知值；空白、`-`、`?` 等未知值不能填零。`a/b`、部分数字、不可辨字符和科学计数法字符串保留原文及解释状态。有限、合理尺度的科学计数法可以解析；不能仅因含 E/e 而丢弃。非有限值不能作几何数值；尺度可疑时等待解释或显式参数覆盖，不能猜测指数、分支或单位。源数据与解析后的绘图数据分别留存。

## 数据文件

主 `--csv` 为 UTF-8 水线半宽宽表，首列 `station`，后列按水线高度递增，对应 `waterline_heights_m`。站号严格递增，四分之一站、半站按数值比例保留。列名来自源表，不以列序号猜高度。

```csv
station,WL0,WL0.5,WL1
0,0,100,200
0.5,50,,250
1,150,200,350
```

新可选输入 `--profile-csv` 为各站 BL 高度，`--deck-csv` 为甲板半宽，`--transom-json` 为 TRANSOM 半宽/高度资料，`--corrections` 为授权修订清单。按对应脚本支持的列名/字段写入，不靠文件名推断单位；调用前可用 `--help` 核对格式。原有 `--csv --config --out --skeleton3d --preview` 不变。

## 核心参数

```json
{
  "waterline_heights_m": [0, 0.5, 1],
  "half_breadth_to_m": 0.001,
  "height_to_m": 0.001,
  "unit_evidence": "用户确认源表半宽和高度为毫米",
  "longitudinal_display_units_per_station": 1,
  "languages": ["zh"],
  "embedded_tables": true,
  "annotations": true
}
```

`half_breadth_to_m` 必须明确；`height_to_m` 默认与它相同。`waterline_heights_m` 已是米，不能再按源单位换算。字体名称及配置从当前环境发现，不固定本机 Windows 字体路径。其他绘图可选参数按当前脚本配置使用。

`languages` 必须明确设置，不能由生成器猜测。中文请求用 `["zh"]`，英文请求用
`["en"]`；只有用户明确要求双语，或开源发布流程要求独立中英文资料时才使用
`["zh", "en"]`。无法从请求和主输入资料判断语言时先询问用户。双语输出规则见
[输出语言与双语交付](output-language.md)。

纵向尺度优先使用 `station_x_m`，其次使用 `LBP_m`、`station_AP`、`station_FP` 的明确映射，再其次为已知 `station_spacing_m`。使用垂线映射时 `x=(s-s_AP)/(s_FP-s_AP)*LBP`；表首尾站不自动等于 AP/FP。未知实际尺度时默认采用原始站号坐标，`longitudinal_display_units_per_station` 默认 1，仅为显示倍数。混合站号 X 与米制 Y/Z 的图不能标为物理米制距离，也不能作为真实 3D 骨架。

`buttock_half_breadths_m` 指定推导 BP 平面；可选 `profile_half_breadths_m` 显式映射源 BL 列到半宽平面，不能由缩写擅猜。`profile_height_limit_m` 是原始数值尺度防护，默认 `10*max(1, abs(水线高度最大绝对值))` 米；可显式覆盖并记录依据。它不是船体边界，不能据此裁造龙骨、甲板或船壳。`half_breadth_limit_m` 默认 1e6 米，是半宽原始尺度的保守解释防护；超限值保持原文及可疑状态，需解释或显式覆盖。这个阈值同样不是船壳边界或合法型宽判据。

## 原始纵剖与受限推导

源 BL 高度优先。缺失 BL 只在明确配置平面与连续、可求解的数据域内推导，计算交点与实测点分开。未知空段不连接，不外推底面或甲板。非单调、交叉、恒定半宽重合段、缺失或拟合失败需报告原因；仍交付已有源横剖、水线、纵剖点与可用曲线。

脚本仅对已明确指定且没有任何可用源高度的 BP 平面启用推导；有部分源高度的 BL 保留其空段，不以计算值自动填满。

CL 是基准平面，原点不能强迫成为端点。仅明确且可解析的 CL 原始单标量可以作为有数据支持的局部锚点；原文仍保留。斜杠、多分支或不可辨 CL 保持未解析，不能将单个标量当作完整 CL 外形。

甲板高度缺失时不生成甲板纵剖；可选平面投影层应默认关闭并说明其含义。TRANSOM 半宽与 BL 高度足够时可单独生成横剖面，即使 X 未知；X 未知不能放入水线/纵剖或真实 3D 位置。

非对称、多值半宽、隧道、倒扣和复杂折角需要相适应的几何格式；普通对称半宽矩阵不保证可靠表示。示例 `assets/` 不提供新任务的默认站数、船长或验收计数。

## 补充 CSV 与 TRANSOM JSON 格式

纵剖 CSV 同样以 `station` 开头，其余列可用 `CL`、`1000BL`、`2000BL` 等源标记；数字 BL 标记按半宽源单位映射，非标准列名需提供 `profile_half_breadths_m` 列表。甲板 CSV 用 `station` 加各甲板源列名。补充 CSV 必须显式列出全部主表站位，缺失数据写空白单元格；不能依赖行顺序对齐。可另有一行 `TRANSOM`，不强行转为普通站号。

```csv
station,CL,1000BL
0,120,180
0.5,,200
1,140,220
```

TRANSOM JSON 可保存以下明确毫米字段；未知纵向位置保留 `null`，不以示例数字替代实船资料。

```json
{
  "station_label": "TRANSOM",
  "longitudinal_position": null,
  "waterline_half_breadths_mm": {"WL0": 600, "WL1": 900},
  "buttock_height_mm": {"1000BL": 800},
  "CL_raw": "120/180"
}
```

`waterline_half_breadths_mm`、`buttock_height_mm`、`upper_deck_half_breadth_mm`、`poop_deck_half_breadth_mm` 的 `_mm` 表示明确毫米，与通用 CSV 换算参数分开；`CL_raw` 保留原始标量或斜杠原文，非明确单值不能作为锚点。JSON 原始字段需留存，即使某项不能生成几何。

已知 `longitudinal_position` 以米表示，使用与 `station_x_m` 相同的未作骨架原点平移的纵向坐标；未知保持 `null`。不得从另一套参考图赋值。

## 打包混合数据示例

`assets/mixed_*` 是回归与格式示例；不作为新船的默认尺寸、站位、显示倍率或自动修订授权。该示例配置含历史展示倍率 10，仍无物理纵向尺度。

```text
python <skill>/scripts/generate_hull_lines.py --csv <skill>/assets/mixed_half_breadths_original_mm.csv --profile-csv <skill>/assets/mixed_profile_heights_mm.csv --deck-csv <skill>/assets/mixed_deck_half_breadths_mm.csv --transom-json <skill>/assets/mixed_transom_mm.json --config <skill>/assets/mixed_parameters.json --corrections <skill>/assets/mixed_corrections.json --out <new-example-output> --preview
```

只有重现这个已授权示例时才使用其 `mixed_corrections.json`。实际任务另存源数据、参数和用户授权清单；不修改打包源资产。
