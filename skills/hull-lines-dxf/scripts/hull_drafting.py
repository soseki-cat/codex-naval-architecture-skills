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


def table(w,title,headers,rows,xy,font,width_headers=None):
    layout_headers=width_headers or headers
    widths=[max(8,len(str(h))*.8+3,max((len(str(r[i]))*.75+3 for r in rows),default=8))*font for i,h in enumerate(layout_headers)]
    edge=np.r_[xy[0],xy[0]+np.cumsum(widths)];rh=font*3
    w.layer("DATA_TABLE_GRID",8);w.layer("DATA_TABLE_TEXT",7)
    for xx in edge:w.ms.add_line((xx,xy[1],0),(xx,xy[1]-(len(rows)+1)*rh,0),dxfattribs={"layer":"DATA_TABLE_GRID"})
    for i in range(len(rows)+2):w.ms.add_line((edge[0],xy[1]-i*rh,0),(edge[-1],xy[1]-i*rh,0),dxfattribs={"layer":"DATA_TABLE_GRID"})
    w.text(title,(xy[0],xy[1]+font*3.5),font*1.8)
    for i,row in enumerate([headers]+rows):
        for j,v in enumerate(row):
            e=w.ms.add_text(str(v),dxfattribs={"layer":"DATA_TABLE_TEXT","style":"HULL_FONT","height":font})
            e.set_placement(((edge[j]+edge[j+1])/2,xy[1]-(i+.5)*rh,0),align=TextEntityAlignment.MIDDLE_CENTER)
    return xy[1]-(len(rows)+1)*rh-font*6


def geometry_signature(d):
    data=[]
    for e in d.modelspace():
        kind=e.dxftype()
        if kind=="SPLINE":value=(np.array(e.control_points).tolist(),list(e.knots))
        elif kind=="POINT":value=tuple(e.dxf.location)
        elif kind=="LINE":value=(tuple(e.dxf.start),tuple(e.dxf.end))
        elif kind=="LWPOLYLINE":value=list(e.get_points())
        elif kind=="SOLID":value=tuple(tuple(e.dxf.get(f"vtx{i}")) for i in range(4))
        elif kind=="CIRCLE":value=(tuple(e.dxf.center),e.dxf.radius)
        else:continue
        data.append((kind,e.dxf.layer,str(value),e.dxf.get("color",256)))
    return data


def render(d,path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from ezdxf.addons.drawing import Frontend,RenderContext
    from ezdxf.addons.drawing.matplotlib import MatplotlibBackend
    fig=plt.figure(figsize=(17,10),facecolor="black")
    ax=fig.add_axes([.02,.02,.96,.96])
    Frontend(RenderContext(d),MatplotlibBackend(ax)).draw_layout(d.modelspace(),finalize=True)
    fig.savefig(path,dpi=150,facecolor="black")
    plt.close(fig)


def produce(bundle,csv_path,config_path,out,skeleton=False,preview=False,extra_sources=None):
    from hull_annotations import annotate
    out=Path(out);out.mkdir(parents=True,exist_ok=True)
    base,model,base_report=build_geometry(bundle,csv_path,config_path,skeleton)
    # Verify new anchors/splines/metadata on disk, in addition to legacy core checks.
    supplemental=[]
    with tempfile.TemporaryDirectory() as tmp:
        for name,w in list(base.items())+([("model",model)] if model else []):
            supplemental.append(w.save_checked(Path(tmp)/(name+".dxf")))
    font_report=fonts(bundle.params)
    languages=bundle.params.get("languages",["zh","en"])
    if not languages or len(set(languages))!=len(languages) or any(l not in ["zh","en"] for l in languages):raise ValueError("languages must be a nonempty subset of ['zh','en']")
    files={};annotation_reports={};signatures=[]
    max_b=float(np.nanmax(bundle.b)) if np.isfinite(bundle.b).any() else 1.
    body_span=max(1.,2*max_b,float(bundle.z[-1]-bundle.z[0]))
    body_y=max_b*1.4+body_span*.8
    profile_y=body_y+(bundle.z[-1]-bundle.z[0])+body_span*.8
    x0=float(bundle.x[0]);xspan=float(bundle.x[-1]-bundle.x[0])
    config=dict(bundle.params)
    for l,info in font_report.items():
        if info["path"]:config[f"font_path_{l}"]=info["path"]
    for language in languages:
        dirname="Chinese" if language=="zh" else "English"
        folder=out/dirname if len(languages)>1 else out
        folder.mkdir(exist_ok=True)
        views={};annotation_reports[language]={}
        for kind,source in base.items():
            with tempfile.TemporaryDirectory() as tmp:
                source.doc.saveas(Path(tmp)/"base.dxf")
                w=imported_writer(Path(tmp)/"base.dxf")
            w.doc.styles.get("HULL_FONT").dxf.font=font_report[language]["dxf_font"]
            ytop=bundle.z[-1] if kind!="waterline" else max_b*1.15
            textsize=body_span/55 if kind=="body" else max(.05,xspan/220)
            start_x=-max_b if kind=="body" else x0
            other_notes=[]
            def shared_note(texts,position,height):
                # Both language envelopes reserve space, then only the chosen text remains.
                # Caption/title lengths cannot alter label geometry between editions.
                for lang in ["zh","en"]:
                    w.text(texts[lang],position,height)
                    if lang!=language:other_notes.append(list(w.ms)[-1])
            shared_note({l:tr(l,kind) for l in ["zh","en"]},(start_x,ytop+textsize*4),textsize*1.7)
            captions={"zh":"半宽与高度按米；X为实际给定站位。" if bundle.physical else "半宽与高度按米；X为站号展示坐标，非实际距离。",
                      "en":"Breadth/height in m; X uses supplied physical positions." if bundle.physical else "Breadth/height in m; X is a station display coordinate, not a measured distance."}
            if kind=="body":captions={"zh":"半宽与高度按米；基线原点不是强制的型线端点。","en":"Breadth/height in m; baseline origin is not a forced hull endpoint."}
            shared_note(captions,(start_x,ytop+textsize*2),textsize)
            w.layer("GRID_LABELS",7)
            if kind=="body":
                for zz in bundle.z:
                    w.ms.add_text(f"WL{zz:g}",dxfattribs={"layer":"GRID_LABELS","style":"HULL_FONT","height":textsize*.75,"insert":(max_b*1.1+body_span*.15,zz,0)})
            else:
                bottom=-max_b*1.1 if kind=="waterline" else float(bundle.z[0])
                for xx,station in zip(bundle.x,bundle.stations):
                    w.ms.add_text(f"{station:g}",dxfattribs={"layer":"GRID_LABELS","style":"HULL_FONT","height":textsize*.75,"insert":(xx,bottom-textsize*2,0)})
            if kind=="profile" and bundle.profile_values is None and base_report["buttock_status"]!="generated":
                shared_note({"zh":"纵剖线未生成："+base_report["buttock_status"],"en":"No derived buttocks: "+base_report["buttock_status"]},(start_x,bundle.z[0]-textsize*4),textsize)
            if bundle.params.get("annotations",True):annotation_reports[language][kind]=annotate(w.doc,language=language,config=config)
            for note in other_notes:w.ms.delete_entity(note)
            filename={"body":"body_plan.dxf","waterline":"waterline_plan.dxf","profile":"longitudinal_sections.dxf"}[kind]
            zoom.extents(w.ms);w.doc.saveas(folder/filename)
            read=ezdxf.readfile(folder/filename);audit=read.audit()
            if audit.errors or audit.fixes:raise AssertionError(f"DXF audit: {filename}")
            files[str((folder/filename).relative_to(out))]={"audit_errors":0,"audit_fixes":0,"splines":len(read.modelspace().query("SPLINE")),"points":len(read.modelspace().query("POINT"))}
            views[kind]=w
        combined=make_writer();combined.doc.units=6 if bundle.physical else 0
        combined.doc.styles.get("HULL_FONT").dxf.font=font_report[language]["dxf_font"]
        for kind,delta,prefix in [("body",(x0+max_b*1.2,body_y,0),"BODY_"),("waterline",(0,0,0),"PLAN_"),("profile",(0,profile_y,0),"PROFILE_")]:
            source=views[kind]
            handles={};copied_entities=[]
            for layer in source.doc.layers:
                combined.layer(prefix+layer.dxf.name,abs(layer.dxf.color))
                if layer.is_off():combined.doc.layers.get(prefix+layer.dxf.name).off()
            for app in source.doc.appids:
                if app.dxf.name not in combined.doc.appids:combined.doc.appids.new(app.dxf.name)
            for e in source.ms:
                copied=e.copy();copied.dxf.layer=prefix+e.dxf.layer
                copied.transform(Matrix44.translate(*delta));combined.ms.add_entity(copied)
                handles[e.dxf.handle]=copied.dxf.handle;copied_entities.append(copied)
            for copied in copied_entities:
                if copied.has_xdata("HULLANNOT"):
                    meta=json.loads("".join(t.value for t in copied.get_xdata("HULLANNOT") if t.code==1000))
                    if meta.get("generated_by")=="hull-lines-dxf" and meta.get("kind")=="curve_label":
                        meta["source_layer"]=prefix+meta["source_layer"]
                        if "source_handle" in meta:meta["source_handle"]=handles[meta["source_handle"]]
                        value=json.dumps(meta,separators=(',',':'))
                        copied.set_xdata("HULLANNOT",[(1000,value[i:i+240]) for i in range(0,len(value),240)])
        if bundle.params.get("embedded_tables",True):
            tf=max(.02,body_span*.013)
            tx=float(bundle.x[-1])+body_span*1.6
            top=profile_y+max(float(bundle.z[-1]),float(np.nanmax(bundle.profile_values)) if bundle.profile_values is not None and np.isfinite(bundle.profile_values).any() else 0)+body_span*.7
            half_rows=[[r["station"]]+[r[f] for f in bundle.fields] for r in bundle.rows_effective]
            if bundle.transom:
                vals=bundle.transom.get("waterline_half_breadths_raw",bundle.transom.get("waterline_half_breadths_mm",{}))
                half_rows.insert(0,["TRANSOM"]+[str(vals.get(f,"-")) for f in bundle.fields])
            station_header="站号" if language=="zh" else "station"
            top=table(combined,tr(language,"half_table")+("（原表单位）" if language=="zh" else " (source units)"),[station_header]+bundle.fields,half_rows,(tx,top),tf,["station"]+bundle.fields)
            if bundle.deck_rows:top=table(combined,tr(language,"deck_table"),["station"]+bundle.deck_fields,[[r["station"]]+[r[f] for f in bundle.deck_fields] for r in bundle.deck_rows],(tx,top),tf)
            if bundle.profile_rows:top=table(combined,tr(language,"profile_table"),["station"]+bundle.profile_fields,[[r["station"]]+[r[f] for f in bundle.profile_fields] for r in bundle.profile_rows],(tx,top),tf)
            transom_cells=[c for c in bundle.inventory if c["row"]=="TRANSOM"]
            if transom_cells:
                headers=["来源","字段","原文","米制解释","状态"] if language=="zh" else ["source","field","raw","interpreted m","status"]
                # Reserve the same widths for both languages through common headers.
                rows=[[c['source'],c['field'],c['raw'],str(c['value_m']) if c['value_m'] is not None else "-",c['status']] for c in transom_cells]
                top=table(combined,tr(language,"transom_table"),headers,rows,(tx,top),tf,["source","field","raw","interpreted m","status"])
            if bundle.correction_report["targets"]:
                rows=[[f"{r['station']:g}",r["column"],r["original_raw"],r["fitted_raw"],"estimate" if r.get("applied") else "not applied"] for r in bundle.correction_report["targets"]]
                table(combined,tr(language,"correction_table"),["station","field","original","drawing","status"],rows,(tx,top),tf)
            for cell in bundle.inventory:
                if "table" not in cell["uses"]:cell["uses"].append("table")
        if bundle.correction_report["status"]=="not_applied":combined.text(("修正批次未应用：" if language=="zh" else "Correction batch not applied: ")+"; ".join(bundle.correction_report["failures"]),(x0,profile_y+body_span*1.1),body_span*.02)
        cname=f"hull_lines_{dirname}.dxf" if len(languages)>1 else "three_views_combined.dxf"
        zoom.extents(combined.ms);combined.doc.saveas(out/cname)
        read=ezdxf.readfile(out/cname);audit=read.audit()
        if audit.errors or audit.fixes:raise AssertionError(f"DXF audit {cname}")
        files[cname]={"audit_errors":0,"audit_fixes":0,"splines":len(read.modelspace().query("SPLINE")),"points":len(read.modelspace().query("POINT"))}
        signatures.append(geometry_signature(read))
        if preview:
            render(read,out/f"preview_{dirname}.png")
            font_report[language]["preview_rendered"]=True
    identical=all(s==signatures[0] for s in signatures)
    if not identical:raise AssertionError("Language versions differ in geometry/layout")
    if model:
        model.doc.saveas(out/"hull_skeleton_3d.dxf")
        reread=ezdxf.readfile(out/"hull_skeleton_3d.dxf");audit=reread.audit()
        if audit.errors or audit.fixes:raise AssertionError("3D DXF audit")
        files["hull_skeleton_3d.dxf"]={"audit_errors":0,"audit_fixes":0,"splines":len(reread.modelspace().query("SPLINE")),"points":len(reread.modelspace().query("POINT"))}
    if csv_path.resolve()!=(out/"offsets_source.csv").resolve():shutil.copyfile(csv_path,out/"offsets_source.csv")
    if config_path.resolve()!=(out/"parameters_source.json").resolve():shutil.copyfile(config_path,out/"parameters_source.json")
    with (out/"offsets_effective.csv").open("w",newline="",encoding="utf-8") as f:
        writer=csv.DictWriter(f,fieldnames=["station"]+bundle.fields);writer.writeheader();writer.writerows(bundle.rows_effective)
    for name,path in (extra_sources or {}).items():
        if path:shutil.copyfile(path,out/name)
    report=dict(base_report)
    report.update(files=files,languages=languages,language_geometry_identical=identical,
                  profile_source="given" if bundle.profile_values is not None else "derived",
                  station_x=bundle.x.tolist(),x_mode="physical_m" if bundle.physical else "station_display",
                  x_mapping=bundle.x_note,correction_report=bundle.correction_report,
                  annotations=annotation_reports,fonts=font_report,
                  supplementary_interpolation_error=max(r["all_interpolation_error"] for r in supplemental),
                  source_unit_evidence=bundle.params.get("unit_evidence",bundle.params.get("unit_status","not supplied")),
                  estimated_cell_count=sum(bool(r.get("applied")) for r in bundle.correction_report["targets"]),
                  source_profile_point_count=int(np.isfinite(bundle.profile_values).sum()) if bundle.profile_values is not None else 0,
                  source_profile_planes_m=[bb for j,bb in enumerate(bundle.profile_half_widths) if np.isfinite(bundle.profile_values[:,j]).any()] if bundle.profile_values is not None else [],
                  transom_anchor_count=len(_transom_values(bundle)),
                  native_AutoCAD_check="not performed",native_Rhino_check="not performed")
    (out/"validation.json").write_text(json.dumps(report,indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"data_inventory.json").write_text(json.dumps(bundle.inventory,indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"correction_report.json").write_text(json.dumps(bundle.correction_report,indent=2,ensure_ascii=False),encoding="utf-8")
    (out/"OPEN_IN_CAD.txt").write_text("AutoCAD: OPEN; Z then E for extents; SAVEAS for DWG.\n"+bundle.x_note+"\nTables use DXF lines/text, not an Excel link or native ACAD_TABLE.\nEstimated corrections are not original measured offsets.\nNative AutoCAD/Rhino testing has not been performed.\n",encoding="utf-8")
    return report
