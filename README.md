# Codex Naval Architecture Skills

[![Validate](https://github.com/soseki-cat/codex-naval-architecture-skills/actions/workflows/validate.yml/badge.svg)](https://github.com/soseki-cat/codex-naval-architecture-skills/actions/workflows/validate.yml)

**Documentation:** English | [Chinese](README.zh-CN.md)

Two source-aware Codex skills for naval-architecture geometry work. They keep source data, units, uncertainty, and software-validation status visible throughout the workflow.

This repository contains:

| Skill | Use it for | Main output |
| --- | --- | --- |
| [`hull-lines-dxf`](skills/hull-lines-dxf/SKILL.md) | Auditing, fitting, and drawing symmetric hull offsets, offset-table screenshots, mixed waterline/deck/profile data, or existing DXF annotations | Request-language DXF body, waterline, and profile views; separate bilingual editions only when requested; source and validation reports |
| [`rhino-basic-hull`](skills/rhino-basic-hull/SKILL.md) | Building or checking a staged Rhino hull from an existing lines-plan DXF, ST/BP/WL curves, or `.3dm` model | Editable Rhino geometry with stage boundaries, closure checks, coordinate evidence, and explicit `REVIEW` items |

The skills are complementary. `hull-lines-dxf` works primarily in 2D source data and CAD output. `rhino-basic-hull` continues into 3D surface fitting and hull closure when that broader scope is explicitly requested.

## Principles

- Missing offsets stay missing. A zero, a blank cell, and an unreadable character are different states.
- Units, station mappings, coordinate axes, and scale evidence are recorded before geometry is generated.
- Data is audited for spikes, missing spans, and reversed waterline order before any fit or drawing.
- Material anomalies are reported to the user before fitting; a full-table or non-crossing refit requires explicit approval.
- Source points, derived points, fitted geometry, and `ESTIMATED` geometry remain distinguishable.
- Output follows the language of the explicit request, then the request language, then the primary source language. Bilingual output is opt-in.
- Chinese and English editions are complete, independent files with identical geometry and no mixed-language annotations.
- A task stops at the requested stage. A curve skeleton does not authorize surfaces, deck creation, or end closure.
- File readback and preview checks are not presented as native Rhino or AutoCAD validation.
- Hull closure does not by itself establish structural, hydrodynamic, stability, or performance acceptance.

## Installation

The repository uses the standard Codex skill layout:

```text
skills/<skill-name>/SKILL.md
```

Copy the complete skill folder into the Codex skills directory. Keep each `agents/`, `assets/`, `references/`, and `scripts/` folder with its `SKILL.md`.

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

Then use the skill explicitly in Codex, for example:

```text
Use $hull-lines-dxf to audit my attached offset table for missing values and sudden jumps first. Show me the questionable cells and wait for my approval before fitting or drawing; then generate the DXF in English only.
```

```text
Use $rhino-basic-hull to build a Rhino 3D curve skeleton from the existing lines.dxf and stop at skeleton acceptance.
```

Install Python dependencies before running the `hull-lines-dxf` generator or tests:

```bash
python -m pip install -r skills/hull-lines-dxf/scripts/requirements.txt
```

`hull-lines-dxf` requires Python 3.10 or newer and the packages listed in its requirements file. `hull_math.py` uses only the Python standard library. `rhino_audit.py` must run inside Rhino's Python runtime with RhinoCommon; it is not a standalone desktop-Python command.

## Quick start

### Offsets to DXF

1. Attach the source table, screenshot, CSV, or existing DXF.
2. Let the skill classify waterline half-breadths, deck half-breadths, profile heights, and transom data without drawing.
3. Review the anomaly report. Confirm whether suspicious values and waterline crossings are source errors, intended geometry, or values to fit.
4. After approval, apply the authorised correction or non-crossing fit and verify the resulting table.
5. Confirm or infer the output language; generate into a new directory only after the data gate passes.
6. Review the source ledger, fit ledger, DXF readback report, previews, fonts, and unresolved `REVIEW` items.

Audit before fitting:

```bash
python skills/hull-lines-dxf/scripts/audit_offsets.py \
  --csv offsets.csv \
  --config parameters.json \
  --report source-audit.json
```

If a non-crossing refit is requested, present the proposed change count first and run it with `--approve-refit` only after user approval. Run both languages only when they were explicitly requested.

Direct generator usage:

```bash
python skills/hull-lines-dxf/scripts/generate_hull_lines.py \
  --csv offsets.csv \
  --config parameters.json \
  --out output \
  --preview
```

The bundled `assets/mixed_*` files are format and regression examples. Their ship dimensions are not defaults for a new project.

### Lines plan to Rhino

1. Provide the existing DXF, curve skeleton, or `.3dm` model.
2. State the starting stage and stopping stage.
3. Audit source curves for unit conflicts, spikes, missing spans, repeated points, and reversed waterline order.
4. Report material anomalies and wait for the user to confirm whether to fit; do not smooth first.
5. Confirm units, coordinate axes, and physical station mapping.
6. Require separate acceptance of coordinates, geometry quality, topology, and native-file roundtrip.
7. Preserve unresolved fit, continuity, or boundary issues as explicit `REVIEW` items.

See [`rhino-basic-hull/references/verification.md`](skills/rhino-basic-hull/references/verification.md) for the evidence model and audit configuration.

## Repository structure

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

## Validation

The repository validation checks skill frontmatter, folder/name consistency, required fields, YAML metadata, and local Markdown links. Existing `hull-lines-dxf` tests cover data parsing, generation, annotation, and pipeline behavior.

On 2026-10-27, the `hull-lines-dxf` suite completed on Windows with `53 passed` and `6` passing subtests. GitHub Actions repeats the checks on Python 3.12. Native Rhino execution is not part of CI because RhinoCommon requires Rhino; audit results outside an actual Rhino runtime remain `NOT_CHECKED`.

Run the checks locally:

```bash
python -m pip install -r requirements-dev.txt
python scripts/validate_skills.py
python -m pytest -q skills/hull-lines-dxf/scripts
```

## Marketplace release

The [Agensi release guide](marketplace/README.md) contains the listing copy,
runtime permissions, logos, evidence boundaries, and repeatable package builder
for the two independently addressable skills. Validate the submission metadata
and package limits without writing a ZIP:

```bash
python scripts/build_agensi_release.py --check
```

Build deterministic Agensi ZIPs and hashes with:

```bash
python scripts/build_agensi_release.py --out dist/agensi
```

The source remains MIT licensed. A marketplace listing packages a supported,
tested distribution of the public work; it does not make the public source
exclusive.

## Data and safety

Do not publish proprietary lines plans, client vessel data, or model files unless you have permission. The bundled assets are examples, not measured ship data. Keep generated geometry in a new output directory and retain source files plus the configuration used for each run.

When reporting results, distinguish these evidence levels:

| Label | Meaning |
| --- | --- |
| `SOFTWARE_VERIFIED` | Observed in the relevant native software |
| `USER_REPORTED` | Supplied by the user, not independently observed |
| `NOT_CHECKED` | No sufficient evidence yet |
| `ESTIMATED` | A declared approximation, retained as an approximation |
| `REVIEW` | A known item that still needs a decision or correction |

## Contributing

Open an issue with the task, source format, expected stage boundary, and validation evidence. Changes to geometry behavior should include a minimal reproducible input and should preserve failures as explicit report states rather than silently repairing source data.

## License

MIT. See [LICENSE](LICENSE).
