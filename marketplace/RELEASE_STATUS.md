# Release Status - 2026-10-27

## Validated

- `hull-lines-dxf`: 53 tests and 6 subtests passed.
- Repository skill/link validation passed for both skills.
- Both packages passed the local Agensi metadata, file-count, character-count,
  file-type, script-size, image-size and secret-pattern checks.
- The `hull-lines-dxf` package was extracted and run from the generated ZIP
  against its bundled example assets. Environment check exited 0, generation
  exited 0, validation JSON was produced, and the bilingual geometry signatures
  matched.
- The non-crossing refit was exercised against the regression table. All 136
  same-side waterline pairs kept a positive separation; the minimum measured
  high-minus-low gap was 11.07 mm.
- The packaged audit gate returned `user_confirmation_required` on the known
  regression anomalies, and an unapproved refit wrote no corrected table.
- The package generated a Chinese-only DXF set when configured with `["zh"]`;
  no English combined drawing or English folder was created.
- `rhino-basic-hull/scripts/hull_math.py` ran from the generated ZIP with a
  standard-library station-mapping request and returned the expected result.
- Two consecutive package builds were byte-identical.

## Release gates

| Listing | Status | Remaining gate |
| --- | --- | --- |
| `hull-lines-dxf` | Ready after commercial setup | Choose price/free status, connect payout and complete the Agensi upload review |
| `rhino-basic-hull` | Staging | Run the purchased-path skill and `rhino_audit.py` in an actual Rhino runtime before submission |

## Evidence limits

- Native AutoCAD was not available in this validation run.
- Native Rhino was not available in this validation run.
- The generated example is based on regression assets, not a measured vessel.
- No Agensi account connector, upload, security scan or human review was
  performed in this workspace.
- The public repository remains MIT licensed; the marketplace listing is a
  supported distribution and does not create exclusivity.

