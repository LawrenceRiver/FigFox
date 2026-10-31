"""Conservative current-scene bounds from a hash/revision-bound native TP asset.

No raster remeasurement, source labels, original-image positions or inferred
semantic regions are used. Missing proof leaves Task 1's full-evidence fallback.
"""
import json
import math
import re
from pathlib import Path
import xml.etree.ElementTree as ET

import tinycss2

from .capacity_partition import digest


def _numbers(values):
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in values):
        raise ValueError('bounds/transform must be finite numbers')
    return list(values)


def _box(value):
    if not isinstance(value,dict):raise ValueError('native bbox object required')
    box=_numbers([value[k] for k in ('left','top','right','bottom')])
    if box[0]>box[2] or box[1]>box[3]:raise ValueError('inverted native bbox')
    return box


# Native TP does not record resolved vector-effect or complete CSS provenance.
# Accept only ordinary, static paint/typography declarations whose geometry is
# measured by getBBox and whose conventional stroke is covered by native pad.
_SAFE_PAINT_PROPERTIES={
    'fill','fill-opacity','fill-rule','stroke','stroke-opacity','stroke-width',
    'stroke-linecap','stroke-linejoin','stroke-miterlimit','stroke-dasharray',
    'stroke-dashoffset','opacity','font-family','font-size','font-style',
    'font-weight','font-variant','font-stretch','text-anchor','dominant-baseline',
    'alignment-baseline','letter-spacing','word-spacing','color','display','visibility'}
_NUMBER=re.compile(r'[+]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?(?:px)?')


def _paint_value_risk(name,value):
    value=value.strip().lower()
    if name=='vector-effect' and value!='none':return 'unsupported vector-effect paint'
    if name in ('stroke-width','stroke-miterlimit'):
        if not _NUMBER.fullmatch(value):return 'unresolved or relative '+name
        number=float(value.removesuffix('px'))
        if not math.isfinite(number):return 'nonfinite '+name
        # Native pad uses max(1,miterlimit); below sqrt(2) it need not enclose a
        # diagonal square cap. A conservative supported floor of 2 also avoids
        # claiming proof for nonstandard low-limit join behavior.
        if name=='stroke-miterlimit' and (value.endswith('px') or number<2):return 'unsupported stroke-miterlimit paint'
    if name=='stroke-linejoin' and value not in ('miter','round','bevel'):return 'unsupported stroke-linejoin paint'
    if name=='stroke-linecap' and value not in ('butt','round','square'):return 'unsupported stroke-linecap paint'
    return None


def _declaration_risk(source):
    def unresolved(tokens):
        for token in tokens:
            if token.type=='error':return True
            if token.type=='function':
                if token.lower_name in ('var','env','attr') or unresolved(token.arguments):return True
            if hasattr(token,'content') and token.content is not None and unresolved(token.content):return True
        return False
    for declaration in tinycss2.parse_declaration_list(source,skip_whitespace=True,skip_comments=True):
        if declaration.type!='declaration':return 'unresolved CSS declaration'
        name=declaration.lower_name
        if name=='vector-effect':return 'unresolved CSS vector-effect'
        if name not in _SAFE_PAINT_PROPERTIES:return 'unsupported CSS paint property: '+name
        if unresolved(declaration.value):return 'unresolved CSS paint value: '+name
        risk=_paint_value_risk(name,tinycss2.serialize(declaration.value))
        if risk:return risk
    return None


def _source_paint_risks(root,source):
    global_risk='external stylesheet paint unproven' if '<?xml-stylesheet' in source.lower() else None
    risks={}
    for node in root.iter():
        tag=node.tag.rsplit('}',1)[-1]
        if tag=='style':
            if node.get('type','text/css')!='text/css':global_risk='unknown stylesheet type'
            for rule in tinycss2.parse_stylesheet(''.join(node.itertext()),skip_whitespace=True,skip_comments=True):
                if rule.type!='qualified-rule':global_risk='unresolved CSS rule or at-rule'
                else:global_risk=global_risk or _declaration_risk(rule.content)
        risk='referenced use paint closure unproven' if tag=='use' else None
        if 'style' in node.attrib:risk=risk or _declaration_risk(node.attrib['style'])
        for name,value in node.attrib.items():
            name=name.rsplit('}',1)[-1]
            risk=risk or _paint_value_risk(name,value)
            if name in ('filter','mask','clip-path','marker','marker-start','marker-mid','marker-end','text-decoration') and value.strip()!='none':
                risk=risk or 'unsupported ancestor/self paint effect: '+name
        if risk:risks[node]=risk
    return global_risk,risks


def verified_bounds(scene):
    audit={'current_revision':scene['current_revision'],'coordinate_system':'current_svg_scene',
           'basis':'hash/revision-bound native TP paint envelope verified against native world/local geometry',
           'accepted_ids':[],'rejected':[],'paint_closure_expansions':[],
           'supported_paint':'static ordinary paint/typography; absolute conventional strokes with orthogonal scene axes and miter limit >=2; no vector-effect, unresolved CSS/ancestor effects or use indirection',
           'visual_correctness_proven':False}
    result={}
    try:
        asset=scene['current_tp']
        if asset.get('domain')!='current' or asset.get('current_revision')!=scene['current_revision']:
            raise ValueError('TP must bind exact current SVG revision and domain')
        if digest(asset['path'])!=asset['sha256'] or digest(scene['current_svg']['path'])!=scene['current_revision']:
            raise ValueError('bound TP/SVG asset hash mismatch')
        tp=json.loads(Path(asset['path']).read_text());source=Path(scene['current_svg']['path']).read_text()
        root=ET.fromstring(source)
        global_paint_risk,paint_risks=_source_paint_risks(root,source)
        parents={child:parent for parent in root.iter() for child in parent}
        objects=tp.get('objects')
        if not isinstance(objects,dict):raise ValueError('native TP objects map required')
        if root.get('viewBox'):
            canvas=[float(v) for v in root.get('viewBox').replace(',',' ').split()]
        else:canvas=[0,0,float(root.get('width','').removesuffix('px')),float(root.get('height','').removesuffix('px'))]
        reported=_numbers([tp['canvas'][k] for k in ('x','y','width','height')])
        if len(canvas)!=4 or any(not math.isfinite(v) for v in canvas) or canvas!=reported:
            raise ValueError('TP canvas does not match current SVG scene coordinates')
        nodes={n.get('id'):n for n in root.iter() if n.get('id')}
        valid={}
        for ident,row in objects.items():
            try:
                if ident not in nodes:raise ValueError('unknown current SVG ID')
                if global_paint_risk:raise ValueError(global_paint_risk)
                node=nodes[ident]
                while node is not None:
                    if node in paint_risks:raise ValueError(paint_risks[node]+' on self/ancestor')
                    node=parents.get(node)
                if not isinstance(row,dict) or row.get('bounds_complete') is not True or row.get('bounds_conservative') is not True or row.get('effects')!=[]:
                    raise ValueError('native complete/conservative/effect-free bounds required')
                geometry=_box(row.get('geometry_bbox'));paint=_box(row.get('paint_bbox'))
                local=row['local_bbox'];x,y,w,h=_numbers([local[k] for k in ('x','y','width','height')])
                matrix=row['world']
                if not isinstance(matrix,list) or len(matrix)!=6:raise ValueError('native scene world matrix required')
                a,b,c,d,e,f=_numbers(matrix)
                norms=math.hypot(a,b)*math.hypot(c,d)
                if norms==0 or abs(a*c+b*d)>1e-9*norms:
                    raise ValueError('nonorthogonal/singular scene transform paint unproven')
                if w<0 or h<0:raise ValueError('invalid native local bbox')
                corners=[(a*u+c*v+e,b*u+d*v+f) for u,v in ((x,y),(x+w,y),(x,y+h),(x+w,y+h))]
                transformed=[min(p[0] for p in corners),min(p[1] for p in corners),max(p[0] for p in corners),max(p[1] for p in corners)]
                if any(not math.isclose(u,v,rel_tol=1e-9,abs_tol=1e-6) for u,v in zip(geometry,transformed)):
                    raise ValueError('geometry bbox is not in the reported current scene coordinates')
                if paint[0]>geometry[0] or paint[1]>geometry[1] or paint[2]<geometry[2] or paint[3]<geometry[3]:
                    raise ValueError('paint bounds do not enclose geometry')
                valid[ident]=paint
            except (ValueError,TypeError,KeyError) as exc:audit['rejected'].append({'id':ident,'reason':str(exc)})
        drawable={'g','svg','a','use','text','tspan','rect','circle','ellipse','line','polyline','polygon','path','image'}
        for ident,box in valid.items():
            # Native group getBBox omits child filter/marker paint. Do not accept
            # a group's "complete" flag if any drawable child lacks that proof.
            descendants=[n for n in nodes[ident].iter() if n is not nodes[ident] and n.tag.rsplit('}',1)[-1] in drawable]
            if any(n.get('id') not in valid for n in descendants):
                audit['rejected'].append({'id':ident,'reason':'drawable descendant lacks complete native bounds'})
            else:
                # Native group getBBox and its own stroke do not enclose child
                # strokes. All these paint boxes are independently verified in
                # the same scene coordinates; union the complete descendant
                # closure, including deeper containers, before evidence lookup.
                boxes=[box]+[valid[n.get('id')] for n in descendants]
                closed=[min(b[0] for b in boxes),min(b[1] for b in boxes),
                        max(b[2] for b in boxes),max(b[3] for b in boxes)]
                result[ident]=closed
                if closed!=box:
                    audit['paint_closure_expansions'].append({'id':ident,'native_paint_bbox':box,
                        'conservative_paint_bbox':closed,'descendant_ids':[n.get('id') for n in descendants]})
    except (ValueError,TypeError,KeyError,OSError,ET.ParseError) as exc:
        audit['rejected'].append({'id':None,'reason':str(exc)})
    audit['accepted_ids']=sorted(result)
    return result,audit
