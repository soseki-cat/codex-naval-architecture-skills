## What this skill does

Hull Lines DXF Studio converts a classified hull-offset table into an auditable
lines-plan workflow. It is designed for the point where transcription errors,
missing offsets, unclear units, and drawing presentation can quietly change the
result. The skill keeps those risks visible instead of repairing them silently.

It audits source cells for missing values, OCR ambiguity, scale conflicts,
longitudinal spikes, and reversed waterline order before fitting. Material
findings are reported for approval; the skill does not turn an anomaly report
into an unrequested correction. A non-crossing refit and the drawing are separate
stages.

The workflow accepts waterline half-breadths plus optional deck half-breadths,
profile heights, transom data, and explicitly authorised correction batches. It
checks station ordering, unit evidence, coordinate mapping, missing cells and
correction boundaries before generating new DXF output. A 3D curve skeleton is
produced only when the request includes it and the source has a physical
longitudinal scale.

Output language follows the explicit request, then the request language, then
the primary source language. Chinese and English are complete, separate editions
only when bilingual delivery is requested; titles and annotations are never
mixed between them.

## What the buyer receives

- Separate body, waterline, and profile DXFs.
- A combined three-view DXF with source-derived grid tables.
- Chinese and English editions with identical geometry.
- Per-curve colours, station and waterline labels, and leader annotations.
- Original-point markers and retained source metadata.
- An optional monotone waterline refit with a per-cell estimate ledger and an
  all-pairs projection check that reports any remaining intersection.
- A source copy, effective table, data inventory, correction report, validation
  JSON, and a preview image when requested.

The default workflow does not create surfaces, a closed hull, Excel links,
unmeasured boundaries, or engineering certification. Those outputs require
separate source data and a different scope.

## Evidence model

The skill distinguishes supplied data, derived values, authorised estimates,
software verification, and unresolved review items. It reports DXF readback
errors and fixes, interpolation residuals, missing-cell counts, language
geometry equality, column and legend completeness, and native-application test
status. A generated file is not described as a verified AutoCAD or Rhino result
unless it was actually opened and checked there.

The source repository is public under the MIT licence. This listing packages a
repeatable marketplace workflow, not exclusive access to the underlying code.

