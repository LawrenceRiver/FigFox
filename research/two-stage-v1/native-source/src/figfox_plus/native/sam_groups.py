"""Compile model-selected asset groups using only SAM source geometry."""
import json
import math
import xml.etree.ElementTree as ET
from .document import SVG


def compile_groups(root, assets):
    catalog={a['id']:a for a in assets if a['role']!='arrow_hint'}
    log=[]
    for node in list(root.iter()):
        declaration=node.get('data-plus-sam-group')
        if not declaration:continue
        members=json.loads(declaration)
        if not isinstance(members,list) or len(members)<2 or any(not isinstance(i,str) for i in members) or len(set(members))!=len(members):
            raise ValueError('SAM group needs distinct model-selected member IDs')
        if list(node):raise ValueError('SAM group placeholder must be empty')
        chosen=[catalog[i] for i in members]
        boxes=[[float(v) for v in a['source_crop']] for a in chosen]
        x,y,w,h=[float(node.get(k)) for k in ('x','y','width','height')]
        if not all(math.isfinite(v) for b in boxes for v in b) or not all(math.isfinite(v) for v in (x,y,w,h)) or w<=0 or h<=0 or any(b[2]<=0 or b[3]<=0 for b in boxes):
            raise ValueError('invalid SAM group geometry')
        left=min(b[0] for b in boxes);top=min(b[1] for b in boxes)
        sw=max(b[0]+b[2] for b in boxes)-left;sh=max(b[1]+b[3] for b in boxes)-top
        scale=min(w/sw,h/sh);tx=x+(w-sw*scale)/2;ty=y+(h-sh*scale)/2
        node.tag='{'+SVG+'}g'
        for key in ('data-plus-sam-group','x','y','width','height'):node.attrib.pop(key,None)
        placement=ET.SubElement(node,'{'+SVG+'}g',{'transform':f'translate({tx} {ty}) scale({scale})'})
        for asset,b in zip(chosen,boxes):
            ET.SubElement(placement,'{'+SVG+'}image',{'href':asset['id'],'x':str(b[0]-left),'y':str(b[1]-top),'width':str(b[2]),'height':str(b[3]),'preserveAspectRatio':'none'})
        log.append({'id':node.get('id'),'members':members,'source_union':[left,top,sw,sh],'model_target':[x,y,w,h],'scale':scale,'placement':[tx,ty]})
    return log


def restore_source_boxes(root, assets):
    """Native images keep SAM source boxes; model ancestor transforms place blocks."""
    catalog={a['id']:a for a in assets if a['role']!='arrow_hint'}
    log=[]
    for node in root.iter():
        if node.tag.rsplit('}',1)[-1]!='image':continue
        aid=node.get('href') or node.get('{http://www.w3.org/1999/xlink}href')
        if aid not in catalog:continue
        box=catalog[aid]['source_crop']
        before={k:node.get(k) for k in ('x','y','width','height')}
        for key,value in zip(('x','y','width','height'),box):node.set(key,str(value))
        node.set('preserveAspectRatio','none')
        log.append({'id':node.get('id'),'asset_id':aid,'model_box':before,'source_box':box})
    return log


def crop_target_box(node, source_box):
    keys=('x','y','width','height')
    supplied=[node.get(k) is not None for k in keys]
    if all(supplied):return [float(node.get(k)) for k in keys]
    if not any(supplied) and node.tag.rsplit('}',1)[-1]=='g':return list(source_box)
    raise ValueError('partial or missing crop target geometry')
