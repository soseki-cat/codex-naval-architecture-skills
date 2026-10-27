# 触发提示词

## 应触发审计门禁

中文：

- “先检查型值表有没有突变、缺失或水线交叉，不要马上画图。”
- “这组数据有没有不合理的地方？列出可疑单元格，等我确认后再拟合。”
- “按我确认的清单重拟合，然后生成中文 DXF。”
- “只做数据审计，不修改原表。”

English:

- “Audit these offsets for anomalies before fitting or drawing.”
- “Show me the questionable cells and wait for my approval.”
- “Apply my authorised corrections, then generate the English DXF.”
- “Check every same-side waterline pair for intersections.”

## 语言路由

中文请求：

> 使用 `$hull-lines-dxf` 检查附件。先列可疑值和理由，我确认后才拟合；最终只出中文图。

英文请求：

> Use `$hull-lines-dxf` to audit the attached table first. Wait for approval before fitting, then generate English-only DXFs.

开源双语请求：

> Use `$hull-lines-dxf` after auditing and approved fitting. Produce separate complete Chinese and English DXF sets from the same final geometry; do not mix languages inside either file.

## 不应直接绘图的提示

- “帮我美化这条线”，但没有给出被修改的单元格或拟合约束。
- “把缺口都补上”，但没有说明插值范围、外推边界或允许的估算方法。
- “让水线不要交叉”，但没有确认真实船型是否含外飘、艉悬伸或多值横剖。
- 用户仅要求画图，但输入有明显尺度冲突或 OCR 失败；此时先报告数据门禁。

## 停止点

- “检查数据”只输出审计结果和建议。
- “拟合数据”只输出拟合表、参数、台账和拟合验证。
- “生成图”在数据和拟合均已批准后执行。
- “做双语开源文件”生成两个独立完整包并比较几何，不把翻译当成几何修订。

