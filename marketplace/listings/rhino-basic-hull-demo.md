**Request**

Use `$rhino-basic-hull` to inspect an existing vessel lines plan. Start from the
source curves, verify units and the ST, BP and WL mapping, then stop at an
editable Rhino curve skeleton. Do not create surfaces, a deck or closure, and do
not repair missing or ambiguous values.

**Source gate**

The workflow first separates the supplied DXF from reference dimensions and
historical notes. It requires the active Rhino document or 3DM file for a native
check; a filename or an earlier JSON report is not treated as proof that the
current geometry was opened. The report records the model units, source and
target axes, station origin, physical station spacing, and any unresolved
ambiguity before geometry changes.

**Result**

When RhinoCommon is available, the read-only audit reports source and result
counts, curve plane checks, valid intersections, stage objects, bounding boxes
and save/readback status. Curve creation is then limited to the approved
skeleton stage. A completed skeleton report separates coordinate evidence,
curve fit and segment status, object provenance, and
`native_Rhino_check: SOFTWARE_VERIFIED`. It does not claim surfaces, a
watertight hull or visual fairness.

If Rhino is unavailable, the skill returns a source inventory and coordinate
analysis only, with native modeling and visual acceptance marked `NOT_CHECKED`.
This is a deliberate stop condition rather than a simulated Rhino result. The
included 100 m case is an example; its dimensions and assumptions are never
treated as defaults for another vessel.

**Submission gate**

This response must be reproduced in an actual Rhino runtime before the listing
is submitted. Until that run is saved, the package remains staged and the
native result must not be presented as verified.

