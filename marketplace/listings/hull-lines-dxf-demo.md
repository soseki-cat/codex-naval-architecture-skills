**Request**

Use `$hull-lines-dxf` with the bundled regression fixture. Treat every dimension
as illustrative, preserve missing and unreadable cells, use the supplied
profile, deck and transom data, and apply only the authorised local correction
manifest. Generate separate and combined Chinese and English views with a
preview and validation report. Stop at supplied offsets; do not infer a bottom,
centreline closure, deck surface or solid.

**Run**

The environment check found Python 3.14.7 with compatible ezdxf, NumPy, SciPy,
Matplotlib, fontTools and Pillow versions. The generator read a 33-station by
17-waterline table plus profile, deck and transom sources. It retained 43 empty
or unusable cells instead of converting them to zero, preserved 518 supplied
points, and separated supplied profile data from derived measurements.

It then applied four authorised local estimates: station 0.5 at 12000WL,
station 2.5 at 6000WL, and station 18 at both 5000WL and 6000WL. Each target was
excluded from the fitting input before a station-direction PCHIP estimate was
calculated. Independent cross-section comparisons and their millimetre
differences were written to the correction ledger; no correction was used to
estimate another cell in the same batch.

Because the first refit still produced waterline crossings, a second constrained
pass enforced nondecreasing half-breadth across each station's known waterlines
and wrote every fitted value to a separate ledger. Two hundred and fifty-three
cells differ from the source table after the combined source-outlier and
non-crossing fit. These changes are explicitly marked as estimates, not recovered
measurements.

**Result**

The output contained Chinese and English body, waterline and profile DXFs; two
combined three-view DXFs; copied source tables; the corrected effective table; a
data inventory; validation reports; and two preview images. The combined Chinese
drawing contained 84 splines and 1,889 source/detail points.
Both language editions had identical geometry. DXF readback returned zero audit
errors and zero audit fixes. The maximum source interpolation check was
9.83e-9 drawing units, and supplementary geometry interpolation was 1.01e-8.
All 136 same-side waterline pairs were checked across their common x ranges and
none intersected; the minimum high-minus-low separation was 11.07 mm. The report
retained the supplied scope: no inferred bottom, centreline closure or deck. It
also recorded `native_AutoCAD_check: not performed` and
`native_Rhino_check: not performed`, so the preview and file checks are not
presented as native CAD validation. The sample is a regression fixture, not a
measured vessel.

