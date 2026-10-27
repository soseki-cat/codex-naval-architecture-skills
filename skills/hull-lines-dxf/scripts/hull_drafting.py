"""Shared drafting from classified source data; no source-table mutations."""
from __future__ import annotations
import csv
import json
import math
from pathlib import Path
import re
import shutil
import tempfile

import ezdxf
from ezdxf import zoom
from ezdxf.enums import TextEntityAlignment
from ezdxf.math import Matrix44
import numpy as np
from scipy.interpolate import PchipInterpolator
from matplotlib import font_manager
from fontTools.ttLib import TTFont

import hull_core as core

PALETTE=[1,30,2,3,4,5,6,140,210,40,130,190,10,50,150,220]
PALETTE += [v for v in range(10,250,10) if v not in PALETTE]
PALETTE += [v for v in range(11,250,10) if v not in PALETTE]
TRANSLATE={
    "body":("BODY PLAN","横剖面图"),"waterline":("WATERLINE PLAN","水线面图"),
    "profile":("PROFILE / BUTTOCK PLAN","纵剖面与纵剖线图"),
    "half_table":("DRAWING HALF-BREADTHS","绘图水线半宽表"),
    "deck_table":("DECK HALF-BREADTHS; ELEVATIONS UNSPECIFIED","甲板半宽表（标高未给出）"),
    "profile_table":("SOURCE PROFILE HEIGHTS / LITERALS","纵剖高度与原文表"),
    "correction_table":("ESTIMATED CORRECTION RECORD","估算修正记录"),
    "transom_table":("TRANSOM SOURCE DATA; X UNSPECIFIED UNLESS SUPPLIED","尾封板原始数据（X 以已给资料为准）"),
}


def tr(language,key):return TRANSLATE[key][0 if language=="en" else 1]


def fonts(params):
    paths=[Path(p) for p in font_manager.findSystemFonts()]
    report={}
    for language,candidates in [("en",["arial.ttf","dejavusans.ttf","liberationsans-regular.ttf"]),
                                ("zh",["simhei.ttf","msyh.ttc","notosanscjk-regular.ttc","simsun.ttc"])]:
        explicit=params.get(f"font_path_{language}")
        found=Path(explicit) if explicit and Path(explicit).is_file() else None
        if found is None:
            found=next((p for n in candidates for p in paths if p.name.lower()==n),None)
        if found is None:
            found=next(iter(paths),None)
        supported=language=="en" and found is not None
        if found is not None and language=="zh":
            try:
                ft=TTFont(found,fontNumber=0)
                cmap=ft.getBestCmap() or {}
                supported=all(ord(c) in cmap for c in "横剖水线站表")
                ft.close()
            except Exception:
                supported=False
        report[language]={"path":str(found) if found else None,"dxf_font":found.name if found else "arial.ttf",
                          "glyph_coverage_checked":supported,"preview_rendered":False,
                          "visual_review":"not performed", "native_CAD_display":"not tested"}
    return report


def make_writer():return core.Writer()


def point(w,coords,layer,meta,color=8):
    w.point(tuple(float(v) for v in coords),layer,color,meta)


def curve_meta(w,e,view,kind,number=None,side=1):
    if "HULLCURVE" not in w.doc.appids:w.doc.appids.new("HULLCURVE")
    e.set_xdata("HULLCURVE",[(1000,json.dumps({"view":view,"kind":kind,"number":number,"side":side},separators=(',',':')))])


def vector_curve(w,coordinates,layer,color,view,kind,number=None,side=1):
    coords=np.asarray(coordinates,dtype=float)
    if len(coords)<2:return None
    keep=np.r_[True,np.linalg.norm(np.diff(coords,axis=0),axis=1)>1e-12]
    coords=coords[keep]
    if len(coords)<2:return None
    t=np.r_[0.,np.cumsum(np.linalg.norm(np.diff(coords,axis=0),axis=1))]
    f=PchipInterpolator(t,coords,axis=0)
    slopes=f.derivative()(t)
    controls=[coords[0]]
    for i,dt in enumerate(np.diff(t)):
        controls += [coords[i]+dt*slopes[i]/3,coords[i+1]-dt*slopes[i+1]/3,coords[i+1]]
    knots=[0.]*4
    for ti in t[1:-1]:knots += [float(ti/t[-1])]*3
    knots += [1.]*4
    w.layer(layer,color)
    e=w.ms.add_open_spline(controls,degree=3,knots=knots,dxfattribs={"layer":layer})
    if np.allclose(coords[:,2],0):e.dxf.flags=8
    w.curve_checks.append((e.dxf.handle,t/t[-1],coords,True))
    curve_meta(w,e,view,kind,number,side)
    return e


def use(bundle,source,row,field,role):
    for cell in bundle.inventory:
        if cell["source"]==source and str(cell["row"])==str(row) and cell["field"]==field:
            if role not in cell["uses"]:cell["uses"].append(role)


def imported_writer(path):
    w=make_writer()
    w.doc=ezdxf.readfile(path)
    w.ms=w.doc.modelspace()
    return w


def _remove_source_text(w):
    for e in list(w.ms.query("TEXT")):
        if e.dxf.layer=="NOTES":w.ms.delete_entity(e)


def _retag_half_estimates(w,bundle):
    targets=bundle.correction_report["targets"] if bundle.correction_report["status"]=="applied" else []
    for e in w.ms.query("POINT"):
        if not e.has_xdata("HULLSOURCE"):continue
        meta=e.get_xdata("HULLSOURCE")[0].value
        for record in targets:
            marker=f"station={record['station']:g};z_m={bundle.z[bundle.fields.index(record['column'])]:g};"
            if marker in meta:
                meta=meta.replace("raw=","drawing=")
                meta+=f";status=estimated;original={record['original_raw']};method={record['method']}"
                e.set_xdata("HULLSOURCE",[(1000,meta)])
                break


def _add_original_replacements(body,plan,bundle,model=None):
    if bundle.correction_report["status"]!="applied":return
    for record in bundle.correction_report["targets"]:
        i=int(np.flatnonzero(np.isclose(bundle.stations,record["station"],atol=1e-10,rtol=0))[0])
        j=bundle.fields.index(record["column"])
        sides=[-1,1] if abs(bundle.x[i]-bundle.split)<1e-9 else [-1] if bundle.x[i]<bundle.split else [1]
        metadata=f"original;station={record['station']:g};field={record['column']};raw={record['original_raw']};drawing={record['fitted_raw']};method={record['method']}"
        for side in sides:
            point(body,(side*record["original_value_m"],bundle.z[j],0),"SOURCE_REPLACED_POINT",metadata,8)
        for side in [-1,1]:
            point(plan,(bundle.x[i],side*record["original_value_m"],0),"SOURCE_REPLACED_POINT",metadata,8)
        if model:
            for side in ([1,-1] if bundle.params.get("mirror_3d",False) else [1]):
                point(model,(bundle.x[i]-bundle.origin_x,side*record["original_value_m"],bundle.z[j]),"SOURCE_REPLACED_POINT",metadata,8)
    for w in [body,plan]+([model] if model else []):w.doc.layers.get("SOURCE_REPLACED_POINT").off()


def _transom_values(bundle):
    anchors=[]
    # Use classified values instead of reparsing raw text or bypassing unit guards.
    for cell in bundle.inventory:
        if cell["row"]!="TRANSOM" or cell["status"]!="known":continue
        source,field,value=cell["source"],cell["field"],cell["value_m"]
        if source=="half" and field in bundle.fields:
            anchors.append((value,float(bundle.z[bundle.fields.index(field)]),source,field))
        elif source=="profile" and field in bundle.profile_fields:
            bb=bundle.profile_half_widths[bundle.profile_fields.index(field)]
            anchors.append((bb,value,source,field))
        elif source=="transom" and field in bundle.transom.get("waterline_half_breadths_mm",{}):
            m=re.fullmatch(r"(\d+(?:\.\d+)?)WL",field,re.I)
            if field in bundle.fields:zz=float(bundle.z[bundle.fields.index(field)])
            elif m:zz=float(m[1])/1000
            else:continue
            anchors.append((value,zz,source,field))
        elif source=="transom" and field in bundle.transom.get("buttock_height_mm",{}):
            m=re.fullmatch(r"(\d+(?:\.\d+)?)BL",field,re.I)
            if m:anchors.append((float(m[1])/1000,value,source,field))
        elif source=="transom" and field=="CL_raw":
            anchors.append((0.,value,source,field))
    return sorted(anchors,key=lambda p:(p[1],p[0]))


def build_geometry(bundle,csv_path,config_path,skeleton):
    config=dict(bundle.params)
    config["station_x_m"]=bundle.x.tolist()
    config["body_split_x"]=bundle.split
    if bundle.profile_values is not None:
        given_widths=[bb for j,bb in enumerate(bundle.profile_half_widths) if np.isfinite(bundle.profile_values[:,j]).any()]
        # Derive only explicitly requested planes lacking any usable source heights.
        # Interior gaps in a supplied source profile stay as gaps.
        config["buttock_half_breadths_m"]=[bb for bb in bundle.levels if not any(abs(bb-v)<1e-10 for v in given_widths)]
    with tempfile.TemporaryDirectory() as tmp:
        tmp=Path(tmp)
        with (tmp/"numeric.csv").open("w",newline="",encoding="utf-8") as stream:
            writer=csv.DictWriter(stream,fieldnames=["station"]+bundle.fields)
            writer.writeheader()
            for i,row in enumerate(bundle.rows_effective):
                normalized={field:row[field] if np.isfinite(bundle.b[i,j]) else "-" for j,field in enumerate(bundle.fields)}
                normalized["station"]=f"{bundle.stations[i]:g}"
                writer.writerow(normalized)
        (tmp/"numeric.json").write_text(json.dumps(config),encoding="utf-8")
        base_report=core.generate(tmp/"numeric.csv",tmp/"numeric.json",tmp/"generated",skeleton,False)
        body=imported_writer(tmp/"generated"/"body_plan.dxf")
        plan=imported_writer(tmp/"generated"/"waterline_plan.dxf")
        profile=imported_writer(tmp/"generated"/"longitudinal_sections.dxf")
        model=imported_writer(tmp/"generated"/"hull_skeleton_3d.dxf") if skeleton else None
    plan.doc.units=profile.doc.units=6 if bundle.physical else 0
    for w in [body,plan,profile]+([model] if model else []):_remove_source_text(w);_retag_half_estimates(w,bundle)
    for e in body.ms.query("SPLINE"):
        n=float(e.dxf.layer[3:].replace("m","-").replace("p","."))
        color=PALETTE[int(np.flatnonzero(np.isclose(bundle.stations,n))[0])%len(PALETTE)]
        body.doc.layers.get(e.dxf.layer).dxf.color=color
        curve_meta(body,e,"body","ST",n,-1 if np.mean(np.array(e.control_points)[:,0])<0 else 1)
    for e in plan.ms.query("SPLINE"):
        n=float(e.dxf.layer[3:].replace("m","-").replace("p","."))
        color=PALETTE[int(np.flatnonzero(np.isclose(bundle.z,n))[0])%len(PALETTE)]
        plan.doc.layers.get(e.dxf.layer).dxf.color=color
        curve_meta(plan,e,"waterline","WL",n,-1 if np.mean(np.array(e.control_points)[:,1])<0 else 1)
    for cell in bundle.inventory:
        if cell["source"]=="half" and cell["row"]!="TRANSOM" and cell["status"] in ["known","estimated"]:
            cell["uses"] += ["body","waterline"]+(["model"] if model else [])
    if bundle.profile_values is not None:
        for e in list(profile.ms.query("POINT")):
            if e.dxf.layer=="SOURCE_PROJECTED":profile.ms.delete_entity(e)
        for e in profile.ms.query("SPLINE"):
            number=float(e.dxf.layer.removeprefix("BP_").replace("p","."))
            curve_meta(profile,e,"profile","BP",number)
        cl_index=next((j for j,v in enumerate(bundle.profile_half_widths) if v==0),None)
        if cl_index is not None:
            for e in list(body.ms.query("SPLINE")):body.ms.delete_entity(e)
            if model:
                for e in list(model.ms.query("SPLINE")):
                    if e.dxf.layer.startswith("ST_"):model.ms.delete_entity(e)
            for i,station in enumerate(bundle.stations):
                sides=[-1,1] if abs(bundle.x[i]-bundle.split)<1e-9 else [-1] if bundle.x[i]<bundle.split else [1]
                zz=bundle.profile_values[i,cl_index]
                clraw=bundle.profile_rows[i][bundle.profile_fields[cl_index]]
                for side in sides:
                    if np.isfinite(zz):point(body,(0,zz,0),"SOURCE_CL",f"source CL;station={station:g};z_m={zz:g};raw={clraw}")
                    for group in core.runs(bundle.b[i]):
                        coordinates=[(side*bundle.b[i,j],bundle.z[j],0) for j in group]
                        first=group[0]
                        previous=bundle.z[first-1] if first>0 else -np.inf
                        if np.isfinite(zz) and previous<zz<=bundle.z[first]:coordinates.insert(0,(0,zz,0))
                        vector_curve(body,coordinates,"ST_"+core.label(station),PALETTE[i%len(PALETTE)],"body","ST",float(station),side)
                if np.isfinite(zz):use(bundle,"profile",bundle.profile_rows[i]["station"],bundle.profile_fields[cl_index],"body")
                if model:
                    model_sides=[1,-1] if bundle.params.get("mirror_3d",False) else [1]
                    for side in model_sides:
                        if np.isfinite(zz):point(model,(bundle.x[i]-bundle.origin_x,0,zz),"SOURCE_CL",f"source CL;station={station:g};z_m={zz:g};raw={clraw}")
                        for group in core.runs(bundle.b[i]):
                            coordinates=[(bundle.x[i]-bundle.origin_x,side*bundle.b[i,j],bundle.z[j]) for j in group]
                            first=group[0];previous=bundle.z[first-1] if first>0 else -np.inf
                            if np.isfinite(zz) and previous<zz<=bundle.z[first]:coordinates.insert(0,(bundle.x[i]-bundle.origin_x,0,zz))
                            vector_curve(model,coordinates,"ST_"+core.label(station),PALETTE[i%len(PALETTE)],"model","ST",float(station),side)
        for j,(field,bb) in enumerate(zip(bundle.profile_fields,bundle.profile_half_widths)):
            name="CL_SOURCE" if bb==0 else "BL_"+core.label(bb*1000)
            c=7 if bb==0 else PALETTE[(j-1)%len(PALETTE)]
            groups=core.runs(bundle.profile_values[:,j])
            isolated={g[0] for g in groups if len(g)==1}
            for group in groups:
                coords=[(bundle.x[i],bundle.profile_values[i,j],0) for i in group]
                vector_curve(profile,coords,name,c,"profile","CL" if bb==0 else "BP",bb)
                if model:
                    for side in ([1,-1] if bb!=0 and bundle.params.get("mirror_3d",False) else [1]):
                        vector_curve(model,[(bundle.x[i]-bundle.origin_x,side*bb,bundle.profile_values[i,j]) for i in group],name,c,"model","BP",bb,side)
            for i,zz in enumerate(bundle.profile_values[:,j]):
                if np.isfinite(zz):
                    meta={"view":"profile","kind":"CL" if bb==0 else "BP","number":bb,"source_point":True}
                    point(profile,(bundle.x[i],zz,0),"SOURCE_POINTS",f"source profile;station={bundle.stations[i]:g};field={field};raw={bundle.profile_rows[i][field]}",c)
                    e=list(profile.ms)[-1];curve_meta(profile,e,**{k:v for k,v in meta.items() if k!="source_point"})
                    tags=json.loads(e.get_xdata("HULLCURVE")[0].value);tags["source_point"]=i in isolated
                    e.set_xdata("HULLCURVE",[(1000,json.dumps(tags))])
                    use(bundle,"profile",bundle.profile_rows[i]["station"],field,"profile")
                    if model:
                        for side in ([1,-1] if bb!=0 and bundle.params.get("mirror_3d",False) else [1]):
                            point(model,(bundle.x[i]-bundle.origin_x,side*bb,zz),"SOURCE_PROFILE",f"source profile;station={bundle.stations[i]:g};field={field};raw={bundle.profile_rows[i][field]}",c)
                        use(bundle,"profile",bundle.profile_rows[i]["station"],field,"model")
    else:
        for e in profile.ms.query("SPLINE"):
            number=float(e.dxf.layer.removeprefix("BP_").replace("p","."))
            curve_meta(profile,e,"profile","BP",number)
    anchors=_transom_values(bundle)
    if anchors:
        vector_curve(body,[(-b,zz,0) for b,zz,_,_ in anchors],"TRANSOM_REFERENCE",8,"body","TRANSOM",None,-1)
        for bb,zz,source,field in anchors:
            raw=next(c["raw"] for c in bundle.inventory if c["row"]=="TRANSOM" and c["source"]==source and c["field"]==field)
            metadata=f"source TRANSOM;field={field};raw={raw};b_m={bb:g};z_m={zz:g};X={bundle.transom.get('longitudinal_position')}"
            point(body,(-bb,zz,0),"SOURCE_TRANSOM",metadata)
            tx=bundle.transom.get("longitudinal_position")
            if model and tx is not None:
                for side in ([1,-1] if bundle.params.get("mirror_3d",False) else [1]):
                    point(model,(float(tx)-bundle.origin_x,side*bb,zz),"SOURCE_TRANSOM",metadata)
            for cell in bundle.inventory:
                if cell["row"]=="TRANSOM" and cell["source"]==source and cell["status"]=="known" and field==cell["field"]:
                    if "body" not in cell["uses"]:cell["uses"].append("body")
        tx=bundle.transom.get("longitudinal_position")
        if model and tx is not None:
            for side in ([1,-1] if bundle.params.get("mirror_3d",False) else [1]):
                vector_curve(model,[(float(tx)-bundle.origin_x,side*b,zz) for b,zz,_,_ in anchors],"TRANSOM_REFERENCE",8,"model","TRANSOM",side=side)
    if bundle.deck_values is not None:
        for j,field in enumerate(bundle.deck_fields):
            name="DECK_PROJECTION_"+field
            for side in [-1,1]:
                for group in core.runs(bundle.deck_values[:,j]):
                    vector_curve(plan,[(bundle.x[i],side*bundle.deck_values[i,j],0) for i in group],name,8,"waterline","DECK",j,side)
                for i,bb in enumerate(bundle.deck_values[:,j]):
                    if np.isfinite(bb):point(plan,(bundle.x[i],side*bb,0),name,f"deck projection;station={bundle.stations[i]:g};field={field};Z_unknown")
            plan.layer(name,8);plan.doc.layers.get(name).off()
            for i,bb in enumerate(bundle.deck_values[:,j]):
                if np.isfinite(bb):use(bundle,"deck",bundle.deck_rows[i]["station"],field,"hidden_plan_projection")
    _add_original_replacements(body,plan,bundle,model)
    return {"body":body,"waterline":plan,"profile":profile},model,base_report

from hull_output import geometry_signature, render, table


def produce(*args, **kwargs):
    """Lazily dispatch to the isolated deliverable assembly module."""
    from hull_produce import produce as implementation

    return implementation(*args, **kwargs)
