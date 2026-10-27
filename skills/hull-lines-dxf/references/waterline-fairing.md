# 水线保序重拟合

普通单值船体外壳在平面投影中的同舷水线通常不应互相穿过。交叉可能来自异常
型值、缺失数据、不同来源混表、真实多值外形，或绘图插值造成的局部反超。先
定位原因，不能仅凭“看起来顺”改动型值。

进入本节前必须完成数据审计并将交叉区间、涉及站号与预计修订范围提交用户确认。
全表保序修正是高影响拟合，不应在用户只要求“检查”或尚未授权时执行。

## 修订流程

1. 保留原 CSV，并在需要时先执行有明确目标清单的局部修订。
2. 对每个站位的已知半宽，从低水线到高水线执行单调保序拟合。缺失值保持缺失，
   不跨空段补齐。
3. 对保序结果设置统一的最小表内间距；仅当用户提供依据时，才对特定站段使用
   更大的局部间距。
4. 从最终矩阵生成 DXF，再检查同舷所有水线在共同 x 范围内的投影关系。
5. 只有检查结果无相交时，才可把该版称为“水线不相交重拟合版”。

示例：

```text
python <skill>/scripts/refit_waterlines.py \
  --csv <offsets.csv> \
  --config <parameters.json> \
  --corrections <authorized-corrections.json> \
  --approve-refit \
  --out <offsets-refit.csv> \
  --ledger <waterline-fit-ledger.csv> \
  --summary <waterline-fit-summary.json>

python <skill>/scripts/generate_hull_lines.py \
  --csv <offsets-refit.csv> \
  --config <parameters.json> \
  --out <drawing-output> \
  --preview

python <skill>/scripts/check_waterline_intersections.py \
  --input <drawing-output>/Chinese/waterline_plan.dxf \
  --report <drawing-output>/waterline_intersection_check.json
```

## 默认约束及其含义

- `--min-gap-mm 20`：表内相邻水线最小间距，用于抵消独立 PCHIP 曲线的轻微
  站间反超。它是拟合参数，不是船体允许误差。
- `--local-gap-mm 200 --local-from-station 0.75 --local-to-station 2`：
  针对艉部近站曲线的局部约束。只有在当前数据和图面验证支持时才可使用，不能
  当作所有船型的默认值。
- 所有被修改单元格均写为 `ESTIMATED`，并保留原始值、最终值和修改依据。

## 验收边界

水线相交检查是文件内样条的二维数值检查。它可以发现投影顺序反转，但不能证明
船体表面光顺、横剖不相交、制造可加工或工程性能合格。原生 CAD 视觉验收仍需
在目标软件中完成。

