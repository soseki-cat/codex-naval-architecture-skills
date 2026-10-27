## What this skill does

Rhino Hull Stage Audit turns a broad “make the hull” request into a controlled
sequence of source checks, curve fitting, surface construction, closure and
evidence review. It is intended for staged naval-architecture modeling where the
original lines, coordinate system, assumptions and native-file status must stay
traceable.

The skill first records the starting stage, requested stopping stage, units,
station and length mapping, coordinate axes, and every authorised estimate. It
then follows the relevant reference for source/skeleton work, waterlines and
mother surfaces, mirror/closure/deck work, or verification. A request to stop at
a curve skeleton does not permit surfaces, a deck or a closed hull.

Before fitting, it audits source curves for unit conflicts, abrupt spikes,
missing spans, repeated points, reversed waterline order, and ambiguous
multi-valued geometry. Material findings are reported for confirmation instead
of being smoothed away.

## What the buyer receives

- A stage plan with explicit inputs, assumptions and stopping conditions.
- Source-to-target coordinate and station mapping guidance.
- Fairness, neighbour-curve, seam and residual review criteria.
- Separate coordinate, geometry-quality, topology, and save/readback evidence.
- Guidance for a read-only RhinoCommon audit of an actual 3DM file.
- Explicit `REVIEW`, `ESTIMATED`, `USER_REPORTED`, `NOT_CHECKED`, and
  `SOFTWARE_VERIFIED` status where applicable.

The skill does not install Rhino, invent missing geometry, or turn closure into a
claim of hydrodynamic, structural or regulatory acceptance. When native Rhino is
unavailable, the result remains limited to source inspection, calculations and
document review.

The source repository is public under the MIT licence. This listing packages a
repeatable technical workflow, not exclusive access to the underlying
instructions or scripts.

