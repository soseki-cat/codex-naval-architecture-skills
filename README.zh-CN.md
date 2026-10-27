# Codex 船舶与海洋工程技能

[![验证](https://github.com/soseki-cat/codex-naval-architecture-skills/actions/workflows/validate.yml/badge.svg)](https://github.com/soseki-cat/codex-naval-architecture-skills/actions/workflows/validate.yml)

**文档语言：** [English](README.md) | 中文

本仓库包含两个面向船舶与海洋工程几何工作的 Codex 技能。整个流程持续保留来源数据、单位、不确定性和软件验证状态。

## 技能

本仓库包含：

| 技能 | 用途 | 主要输出 |
| --- | --- | --- |
| [`hull-lines-dxf`](skills/hull-lines-dxf/SKILL.md) | 审计、拟合并绘制对称船体半宽、型值表截图、混合水线/甲板/纵剖数据，或更新已有 DXF 标注 | 与请求语言一致的横剖、水线和纵剖 DXF；仅在明确要求时生成独立双语版本；来源和验证报告 |
| [`rhino-basic-hull`](skills/rhino-basic-hull/SKILL.md) | 基于已有型线 DXF、ST/BP/WL 曲线或 `.3dm` 模型建立或检查分阶段 Rhino 船体 | 带阶段边界、闭合检查、坐标证据和明确 `REVIEW` 项的可编辑 Rhino 几何 |

两个技能互为补充。`hull-lines-dxf` 主要负责二维源数据和 CAD 输出；`rhino-basic-hull` 在明确扩大范围后继续完成三维曲面拟合和船体闭合。

## 原则

- 缺失型值仍然保持缺失。零值、空白和无法识别的字符是不同状态。
- 生成几何前记录单位、站位映射、坐标轴和尺度证据。
- 拟合或绘图前先检查孤点突变、连续缺失段和水线顺序反转。
- 发现实质性异常时先向用户报告；全表拟合或去交叉拟合必须获得明确授权。
- 原始点、派生点、拟合曲线和 `ESTIMATED` 几何必须可区分。
- 输出语言依次取明确指定语言、当前请求语言和主要来源资料语言；双语输出必须由用户明确要求。
- 中英文各为完整、独立文件，几何一致但文字、字体和排版不混用。
- 任务在指定阶段停止。只要求曲线骨架，不等于授权曲面、甲板或端部闭合。
- 文件回读和预览检查不能等同于 Rhino 或 AutoCAD 原生验证。
- 船体闭合本身不能证明结构、水动力、稳性或性能合格。

## 安装

仓库采用标准 Codex 技能目录结构：

```text
skills/<skill-name>/SKILL.md
```

把完整技能文件夹复制到 Codex 技能目录。每个 `agents/`、`assets/`、`references/` 和 `scripts/` 文件夹都要与对应 `SKILL.md` 放在一起。

### PowerShell

```powershell
git clone https://github.com/soseki-cat/codex-naval-architecture-skills.git
New-Item -ItemType Directory -Force "$env:USERPROFILE\.codex\skills" | Out-Null
Copy-Item ".\codex-naval-architecture-skills\skills\hull-lines-dxf" "$env:USERPROFILE\.codex\skills\" -Recurse
Copy-Item ".\codex-naval-architecture-skills\skills\rhino-basic-hull" "$env:USERPROFILE\.codex\skills\" -Recurse
```

### Bash

```bash
git clone https://github.com/soseki-cat/codex-naval-architecture-skills.git
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R codex-naval-architecture-skills/skills/hull-lines-dxf "${CODEX_HOME:-$HOME/.codex}/skills/"
cp -R codex-naval-architecture-skills/skills/rhino-basic-hull "${CODEX_HOME:-$HOME/.codex}/skills/"
```

然后在 Codex 中明确调用技能，例如：

```text
使用 $hull-lines-dxf 先检查附件的型值缺失和突变，只列出可疑单元格并等待我确认；确认后才拟合，最后生成中文 DXF。
```

```text
使用 $rhino-basic-hull 基于现有 lines.dxf 建立 Rhino 三维曲线骨架，只做到骨架验收。
```

运行 `hull-lines-dxf` 生成器或测试前安装 Python 依赖：

```bash
python -m pip install -r skills/hull-lines-dxf/scripts/requirements.txt
```

`hull-lines-dxf` 需要 Python 3.10 或更高版本和其依赖文件列出的软件包。`hull_math.py` 只依赖 Python 标准库。`rhino_audit.py` 必须在带 RhinoCommon 的 Rhino Python 运行时中执行，不能作为桌面 Python 命令运行。

## 快速开始

### 型值表到 DXF

1. 附上源表、截图、CSV 或已有 DXF。
2. 让技能分类水线半宽、甲板半宽、纵剖高度和尾封板资料，不生成图形。
3. 检查异常报告，确认可疑值和水线交叉是原始错误、真实多值外形，还是需要拟合的值。
4. 获得授权后执行指定单元格修订或全表保序拟合，并验证最终表。
5. 确定或推断输出语言；只有数据门禁通过后才生成到新目录。
6. 检查来源台账、拟合台账、DXF 回读报告、预览、字体和未解决 `REVIEW` 项。

拟合前先审计：

```bash
python skills/hull-lines-dxf/scripts/audit_offsets.py \
  --csv offsets.csv \
  --config parameters.json \
  --report source-audit.json
```

若需要去交叉重拟合，先报告预计改动数量；只有用户确认后才加 `--approve-refit` 执行。只有明确要求双语时才生成两套语言版本。

直接运行生成器：

```bash
python skills/hull-lines-dxf/scripts/generate_hull_lines.py \
  --csv offsets.csv \
  --config parameters.json \
  --out output \
  --preview
```

包内 `assets/mixed_*` 只是格式和回归测试样例，其船体尺寸不是新项目的默认值。

### 型线图到 Rhino

1. 提供已有 DXF、曲线骨架或 `.3dm` 模型。
2. 说明起始阶段和结束阶段。
3. 检查源曲线的单位冲突、尖折、突变、缺失段、重复点和水线顺序反转。
4. 报告实质性异常，等待用户确认是否拟合；不能先做光顺再解释。
5. 确认单位、坐标轴和实际站位映射。
6. 分别验收坐标、几何质量、拓扑和原生文件回读。
7. 把未解决的拟合、连续性和边界问题保留为明确的 `REVIEW` 项。

验证模型见 [`rhino-basic-hull/references/verification.md`](skills/rhino-basic-hull/references/verification.md)。

## 仓库结构

```text
.
|-- .github/workflows/validate.yml
|-- scripts/validate_skills.py
|-- skills/
|   |-- hull-lines-dxf/
|   |   |-- SKILL.md
|   |   |-- agents/
|   |   |-- assets/
|   |   |-- references/
|   |   `-- scripts/
|   `-- rhino-basic-hull/
|       |-- SKILL.md
|       |-- agents/
|       |-- references/
|       `-- scripts/
|-- requirements-dev.txt
`-- LICENSE
```

## 验证

仓库验证会检查技能 frontmatter、目录与名称一致性、必填字段、YAML 元数据和本地 Markdown 链接。`hull-lines-dxf` 测试覆盖数据解析、审计门禁、水线保序拟合、生成、标注和完整流程。

2026-10-27，`hull-lines-dxf` 在 Windows 上的测试结果为 `53 passed` 和 `6` 个通过子测试。GitHub Actions 会在 Python 3.12 上重复检查。RhinoCommon 需要实际 Rhino，因此原生 Rhino 执行不在 CI 内；未在真实 Rhino 中运行的结果保持 `NOT_CHECKED`。

本地检查：

```bash
python -m pip install -r requirements-dev.txt
python scripts/validate_skills.py
python -m pytest -q skills/hull-lines-dxf/scripts
```

## Agensi 发布

[Agensi 发布指南](marketplace/README.md)包含两个独立技能的文案、运行权限、图标、证据边界和可重复打包工具。

不写 ZIP 的发布检查：

```bash
python scripts/build_agensi_release.py --check
```

生成确定性 ZIP 和哈希：

```bash
python scripts/build_agensi_release.py --out dist/agensi
```

源码继续保持 MIT 许可。市场上架只代表经过测试的发布分发，不改变开源源码已经授予的权利。

## 数据与安全

未经许可，不得发布专有型线图、客户船体数据或模型文件。包内资产只是示例，不是实测船数据。生成结果应写入新目录，并保留源文件及每次运行配置。

报告结果时区分以下证据等级：

| 标签 | 含义 |
| --- | --- |
| `SOFTWARE_VERIFIED` | 已在相关原生软件中实际观察 |
| `USER_REPORTED` | 用户提供，未独立观察 |
| `NOT_CHECKED` | 尚缺足够证据 |
| `ESTIMATED` | 明确声明的近似值，并保留其近似属性 |
| `REVIEW` | 已知但尚待决定或修正的项目 |

## 参与贡献

提交问题时请附任务、源格式、预期阶段边界和验证证据。修改几何行为时应提供最小可复现输入，并把失败保留为明确报告状态，不能静默修复源数据。

## 许可证

MIT。见 [LICENSE](LICENSE)。
