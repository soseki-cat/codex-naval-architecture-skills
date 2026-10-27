# -*- coding: utf-8 -*-
"""Read-only RhinoCommon File3dm audit; run in Rhino Python, not ordinary Python.

No document/model mutation, surface generation, save, or tolerance changes.
Does not certify visual fairness or emit a BASIC_HULL_COMPLETE stage marker.
"""
import Rhino
import os
import json
import math
import io


def _point(values):
    if len(values) != 3:
        raise ValueError('Expected three coordinates')
    values = [float(v) for v in values]
    if any(math.isnan(v) or math.isinf(v) for v in values):
        raise ValueError('Coordinates must be finite')
    return Rhino.Geometry.Point3d(*values)


def _xyz(p):
    return [float(p.X), float(p.Y), float(p.Z)]


def _path(path):
    return os.path.normcase(os.path.abspath(path))


def _read(path):
    path = os.path.abspath(path)
    if not os.path.isfile(path) or os.path.splitext(path)[1].lower() != '.3dm':
        raise ValueError('Expected an existing real .3dm file: '+path)
    file = Rhino.FileIO.File3dm.Read(path)
    if file is None:
        raise ValueError('Rhino could not read '+path)
    return file


def curve_plane_points(curve, origin, normal, tolerance):
    vector = Rhino.Geometry.Vector3d(*_xyz(_point(normal)))
    if not vector.Unitize():
        raise ValueError('Plane normal must be nonzero')
    plane = Rhino.Geometry.Plane(_point(origin), vector)
    events = Rhino.Geometry.Intersect.Intersection.CurvePlane(curve, plane, tolerance)
    points, overlaps = [], []
    for event in events or []:
        if event.IsPoint:
            points.append({'point':_xyz(event.PointA), 'curve_parameter':float(event.ParameterA)})
        elif event.IsOverlap:
            overlaps.append({'parameter_interval':[float(event.OverlapA.T0),float(event.OverlapA.T1)]})
    return {'points':points, 'overlaps':overlaps}


def audit_files(config):
    file = _read(config['model_file'])
    expected_units = config.get('expected_units')
    if not isinstance(expected_units, (str, type(u''))) or not expected_units:
        raise ValueError('Declare expected_units from the confirmed coordinate contract')
    tol = float(config.get('tolerance', file.Settings.ModelAbsoluteTolerance))
    if tol <= 0 or math.isnan(tol) or math.isinf(tol):
        raise ValueError('Audit tolerance must be positive and finite, in model units')
    obs = {str(o.Attributes.ObjectId).lower():o for o in file.Objects}
    target_ids = config.get('target_ids')
    if target_ids is None:
        target_ids = [i for i,o in obs.items() if isinstance(o.Geometry,Rhino.Geometry.Brep)]
    targets = []
    for ident in target_ids:
        ident = str(ident).strip('{}').lower()
        o = obs.get(ident)
        if o is None or not isinstance(o.Geometry,Rhino.Geometry.Brep):
            targets.append({'id':ident,'passed':False,'reason':'Missing target or not a Brep'})
            continue
        b = o.Geometry
        naked = [e for e in b.Edges if e.Valence==Rhino.Geometry.EdgeAdjacency.Naked]
        loops = list(Rhino.Geometry.Curve.JoinCurves([e.DuplicateCurve() for e in naked],tol) or []) if naked else []
        non_manifold = sum(1 for e in b.Edges if e.Valence==Rhino.Geometry.EdgeAdjacency.NonManifold)
        bb = b.GetBoundingBox(True)
        passed = b.IsValid and b.IsManifold and non_manifold==0
        if b.IsSolid:
            passed = passed and b.SolidOrientation==Rhino.Geometry.BrepSolidOrientation.Outward
        if config.get('require_closed',False):
            passed = passed and b.IsSolid and len(naked)==0
        targets.append({'id':ident,'name':o.Attributes.Name,'valid':b.IsValid,'closed':b.IsSolid,
                        'orientation':str(b.SolidOrientation),'faces':b.Faces.Count,
                        'edges':b.Edges.Count,'vertices':b.Vertices.Count,
                        'naked_edges':len(naked),'non_manifold_edges':non_manifold,
                        'bbox':[_xyz(bb.Min),_xyz(bb.Max)],
                        'naked_loops':[{'closed':c.IsClosed,'start':_xyz(c.PointAtStart),'end':_xyz(c.PointAtEnd)} for c in loops],
                        'naked_edge_bboxes':[[_xyz(e.GetBoundingBox(True).Min),_xyz(e.GetBoundingBox(True).Max)] for e in naked],
                        'passed':bool(passed)})
    roles = []
    for role in config.get('curve_roles',[]):
        ident = str(role['id']).strip('{}').lower()
        kind = role['kind']
        if kind not in ('ST','BP','WL'):
            raise ValueError('Curve role must be ST, BP or WL')
        o = obs.get(ident)
        if o is None or not isinstance(o.Geometry,Rhino.Geometry.Curve):
            roles.append({'id':ident,'kind':kind,'passed':False,'reason':'Missing source curve'})
            continue
        value = float(role['plane_value'])
        if math.isnan(value) or math.isinf(value):
            raise ValueError('Fixed plane value must be finite')
        bb = o.Geometry.GetBoundingBox(True)
        axis = {'ST':'X','BP':'Y','WL':'Z'}[kind]
        error = max(abs(float(getattr(bb.Min,axis))-value),abs(float(getattr(bb.Max,axis))-value))
        roles.append({'id':ident,'kind':kind,'name':o.Attributes.Name,'axis':axis,
                      'plane_value':value,'max_plane_deviation':error,
                      'start':_xyz(o.Geometry.PointAtStart),'end':_xyz(o.Geometry.PointAtEnd),
                      'passed':bool(o.Geometry.IsValid and error<=tol)})
    cuts = []
    for cut in config.get('cuts',[]):
        row={'name':cut['name'],'points':[],'overlaps':[], 'point_count_by_object':{},'missing_objects':[]}
        for ident in cut['object_ids']:
            ident=str(ident).strip('{}').lower();o=obs.get(ident)
            if o is None or not isinstance(o.Geometry,Rhino.Geometry.Curve):
                row['missing_objects'].append(ident);continue
            events=curve_plane_points(o.Geometry,cut['origin'],cut['normal'],tol)
            row['point_count_by_object'][ident]=len(events['points'])
            for point in events['points']:
                point.update({'source_object':ident,'source_name':o.Attributes.Name});row['points'].append(point)
            for overlap in events['overlaps']:
                overlap['source_object']=ident;row['overlaps'].append(overlap)
        row['status']='REVIEW_OVERLAP' if row['overlaps'] else ('VALID_POINTS' if row['points'] else 'NO_EFFECTIVE_POINT')
        cuts.append(row)
    baseline={'status':'NOT_REQUESTED','unchanged':None}
    if config.get('baseline_file'):
        previous=_read(config['baseline_file'])
        original={str(o.Attributes.ObjectId).lower():int(o.Geometry.DataCRC(0)) for o in previous.Objects}
        missing=[i for i in original if i not in obs]
        changed=[i for i,crc in original.items() if i in obs and int(obs[i].Geometry.DataCRC(0))!=crc]
        baseline={'status':'SOFTWARE_VERIFIED','compared_count':len(original),'missing':missing,
                  'changed':changed,'added_count':sum(i not in original for i in obs),
                  'unchanged':not missing and not changed}
    unit_match=str(file.Settings.ModelUnitSystem)==expected_units
    checked=bool(targets or roles or cuts)
    passed=checked and unit_match and all(t['passed'] for t in targets) and all(t['passed'] for t in roles)
    passed=passed and all(not c['overlaps'] and not c['missing_objects'] for c in cuts)
    if baseline['status']=='SOFTWARE_VERIFIED':passed=passed and baseline['unchanged']
    return {'backend':'RhinoCommon.File3dm.Read','evidence':'SOFTWARE_VERIFIED',
            'inputs':{k:os.path.abspath(config[k]) for k in ['model_file','baseline_file','config_file'] if config.get(k)},
            'units':{'actual':str(file.Settings.ModelUnitSystem),'expected':expected_units,'matches':unit_match},
            'model_absolute_tolerance':float(file.Settings.ModelAbsoluteTolerance),'audit_tolerance':tol,
            'object_count':file.Objects.Count,'targets':targets,'curve_roles':roles,'cuts':cuts,'baseline':baseline,
            'visual_review':'NOT_PERFORMED_BY_SCRIPT','residual_acceptance':'NOT_PERFORMED_BY_SCRIPT',
            'numeric_audit_passed':bool(passed)}


def write_report(report, path):
    path=os.path.abspath(path)
    if os.path.splitext(path)[1].lower()!='.json' or _path(path) in [_path(p) for p in report['inputs'].values()]:
        raise ValueError('Audit output must be a separate new JSON file')
    fd=os.open(path,os.O_CREAT|os.O_EXCL|os.O_WRONLY)
    with os.fdopen(fd,'w') as f:
        f.write(json.dumps(report,ensure_ascii=True,indent=2,allow_nan=False)+'\n')


if __name__ == '__main__':
    import rhinoscriptsyntax as rs
    config_path=rs.OpenFileName('Choose read-only hull audit JSON', 'JSON (*.json)|*.json||')
    if config_path:
        with io.open(config_path,'r',encoding='utf-8-sig') as f:
            config=json.load(f)
        config['config_file']=config_path
        result=audit_files(config)
        report_path=config.get('report_file')
        if report_path:
            write_report(result,report_path)
        print('Read-only native audit: numeric checks passed='+str(result['numeric_audit_passed'])+
              '; visual/residual acceptance remains separate.')
