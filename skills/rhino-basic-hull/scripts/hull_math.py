"""Coordinate/provenance math only. Does not control Rhino or prove CAD validity.

Python 3, standard library. CLI: --input request.json [--output result.json].
Request: {operation: station_x|map_station|map_bp|deduplicate|residuals, args: {...}}.
"""
import argparse
import copy
import json
import math
from pathlib import Path


def _number(value):
    if isinstance(value, bool):
        raise ValueError('A numeric coordinate cannot be a boolean')
    value = float(value)
    if not math.isfinite(value):
        raise ValueError('Coordinates, scales and tolerances must be finite')
    return value


def _vector(value):
    if len(value) != 3:
        raise ValueError('Expected three coordinates')
    return [_number(v) for v in value]


def _dot(a, b):
    return sum(x*y for x, y in zip(a, b))


def _project(point, origin, axis_a, axis_b, metres_per_unit, plane_tolerance_m):
    p, o, a, b = map(_vector, [point, origin, axis_a, axis_b])
    scale, tol = _number(metres_per_unit), _number(plane_tolerance_m)
    if scale <= 0 or tol < 0:
        raise ValueError('Scale must be positive; tolerance must be nonnegative')
    if abs(_dot(a,a)-1) > 1e-9 or abs(_dot(b,b)-1) > 1e-9 or abs(_dot(a,b)) > 1e-9:
        raise ValueError('Source axes must be orthonormal unit vectors')
    normal = [a[1]*b[2]-a[2]*b[1], a[2]*b[0]-a[0]*b[2], a[0]*b[1]-a[1]*b[0]]
    delta = [p[i]-o[i] for i in range(3)]
    normal_m = _dot(delta, normal)*scale
    if abs(normal_m) > tol:
        raise ValueError('Source is not in the declared drawing plane; do not flatten it')
    return _dot(delta,a)*scale, _dot(delta,b)*scale, normal_m


def map_station_point(point, origin, width_axis, height_axis, x_m,
                      mirror=False, metres_per_unit=1.0, plane_tolerance_m=1e-7):
    width, height, normal = _project(point, origin, width_axis, height_axis,
                                     metres_per_unit, plane_tolerance_m)
    # Preserve any within-tolerance normal component instead of silently flattening.
    return [_number(x_m)+normal, -width if mirror else width, height]


def map_bp_point(point, origin, length_axis, height_axis, y_m,
                 x_reference_m=0.0, metres_per_unit=1.0, plane_tolerance_m=1e-7):
    length, height, normal = _project(point, origin, length_axis, height_axis,
                                      metres_per_unit, plane_tolerance_m)
    return [_number(x_reference_m)+length, _number(y_m)-normal, height]


def station_x(station, *, ap, fp, lbp_m, origin_station, confirmed):
    if confirmed is not True:
        raise ValueError('AP/FP station correspondence must be confirmed, not inferred')
    station, ap, fp, lbp, origin = map(_number, [station,ap,fp,lbp_m,origin_station])
    if ap == fp or lbp <= 0:
        raise ValueError('AP and FP must differ and LBP must be positive')
    return (station-origin)/(fp-ap)*lbp


def deduplicate_points(records, *, tolerance_m):
    tol = _number(tolerance_m)
    if tol < 0:
        raise ValueError('Duplicate tolerance must be nonnegative')
    raw = copy.deepcopy(records)
    representatives, groups = [], []
    for i, row in enumerate(raw):
        point = _vector(row['point'])
        match = next((j for j,p in enumerate(representatives) if math.dist(point,p) <= tol), None)
        if match is None:
            representatives.append(point)
            groups.append([i])
        else:
            groups[match].append(i)
    return {'raw':raw, 'unique':[copy.deepcopy(raw[g[0]]) for g in groups], 'groups':groups}


def residual_summary(records, *, split_x_m):
    if len(split_x_m) != 2:
        raise ValueError('Provide the two actual longitudinal region boundaries')
    lo, hi = map(_number, split_x_m)
    if lo >= hi:
        raise ValueError('Region boundaries must increase')
    values = []
    regions = {name:[] for name in ['aft','mid','fore']}
    for row in records:
        d, signed, x = map(_number, [row['distance_m'],row['signed_half_width_m'],row['x_m']])
        if d < 0:
            raise ValueError('Closest-point distances must be nonnegative')
        values.append(d)
        regions['aft' if x < lo else ('mid' if x < hi else 'fore')].append(signed)
    return {'count':len(values),
            'max_closest_distance_m':max(values) if values else None,
            'rms_closest_distance_m':math.sqrt(sum(d*d for d in values)/len(values)) if values else None,
            'regions':{k:{'count':len(v),'mean_signed_half_width_m':sum(v)/len(v) if v else None}
                       for k,v in regions.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    ns = parser.parse_args()
    operations = {'station_x':station_x, 'map_station':map_station_point,
                  'map_bp':map_bp_point, 'deduplicate':deduplicate_points, 'residuals':residual_summary}
    try:
        request = json.loads(ns.input.read_text(encoding='utf-8-sig'))
        result = operations[request['operation']](**request['args'])
        output = json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False)
        if ns.output:
            if ns.output.suffix.lower() != '.json' or ns.output.resolve() == ns.input.resolve():
                raise ValueError('Output must be a separate .json file')
            with ns.output.open('x',encoding='utf-8') as f:
                f.write(output+'\n')
        else:
            print(output)
    except (ValueError, KeyError, OSError, TypeError) as exc:
        parser.exit(2, 'hull_math: '+str(exc)+'\n')


if __name__ == '__main__':
    main()
