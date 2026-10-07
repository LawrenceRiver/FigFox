"""Generic TP/SP operations. Numerical parameters belong to model responses."""
from figfox_plus.image_io import imread
from copy import deepcopy
import json
import math
from pathlib import Path
import xml.etree.ElementTree as ET
from .document import SVG,tag,validate,serialize,measure,parse
from ..tp.transforms import compose,inverse,IDENTITY
from ..tp.groups import union_bounds,alignment_delta,scaling_matrix
from ..tp.relations import proposals
from ..sp.compiler import compile_scene
from ..assets import crop_asset, remove_background_asset,vector_element,raster_part
from ..vectorize import vectorize_asset

def nodes(root):return {n.get('id'):n for n in root.iter() if n.get('id')}
def parents(root):return {c:p for p in root.iter() for c in p}
def number(v):
    if isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v):raise ValueError('finite number required')
    return v

def move(root,ids,transform,bounds):
    by=nodes(root);par=parents(root);selected={by[i] for i in ids}
    for n in selected:
        parent=par[n];ancestor=parent
        while ancestor in par and ancestor not in selected:ancestor=par[ancestor]
        if ancestor in selected:continue
        b=bounds['objects'][n.get('id')];pm=b['parent_world']
        local=compose(inverse(pm),compose(transform,b['world']))
        n.set('transform','matrix('+' '.join(format(v,'.12g') for v in local)+')')

def replacement(root,ids,element):
    by=nodes(root);par=parents(root);target=by[ids[0]]
    selected={by[i] for i in ids}
    if any(other is not target and other in set(target.iter()) for other in selected):raise ValueError('replacement targets include ancestor/descendant')
    # <use> has an instance viewport in addition to its transform. Preserve it
    # by delegating the original symbol viewBox mapping to native SVG layout.
    # All numbers come from the existing API SVG, never a reference-image answer.
    if tag(target)=='use':
        href=target.get('href',target.get('{http://www.w3.org/1999/xlink}href',''))
        referenced=by.get(href[1:]) if href.startswith('#') else None
        if referenced is None:raise ValueError('cannot preserve unresolved use viewport')
        wrapper=ET.Element('{'+SVG+'}g')
        if tag(referenced) in ('symbol','svg'):
            attrs={'x':target.get('x','0'),'y':target.get('y','0'),
                   'width':target.get('width',referenced.get('width','100%')),
                   'height':target.get('height',referenced.get('height','100%'))}
            for key in ('viewBox','preserveAspectRatio','overflow'):
                if referenced.get(key) is not None:attrs[key]=referenced.get(key)
            viewport=ET.SubElement(wrapper,'{'+SVG+'}svg',attrs);viewport.append(element)
        else:
            viewport=ET.SubElement(wrapper,'{'+SVG+'}g',{'transform':f"translate({target.get('x','0')} {target.get('y','0')})"});viewport.append(element)
        element=wrapper
    element.set('id',ids[0])
    if target.get('transform'):element.set('transform',target.get('transform'))
    parent=par[target];position=list(parent).index(target)
    for node in selected:par[node].remove(node)
    parent.insert(position,element)

def sp_element(kind,data,oid):
    # Model supplies constructor data, actual geometry is produced by registered code.
    scene={'version':'plus-0.1','canvas':{'width':1,'height':1},'objects':[{'id':oid,'name':oid,'kind':kind,'data':data}], 'relations':[],'assets':[]}
    svg,_=compile_scene(scene);compiled=ET.fromstring(svg);g=ET.Element('{'+SVG+'}g')
    g.extend(list(compiled));g.set('data-plus-kind',kind);return g

def check_relations(root,relations,bounds=None):
    bounds=bounds or measure(root);reports=[]
    for r in relations:
        try:
            if r['predicate']=='legal_overlap':reports.append({'id':r['id'],'status':'declared_legal'});continue
            if r['predicate']=='contain':
                by=nodes(root)
                if any(tag(by[i])!='rect' for i in r['object_ids']):raise NotImplementedError('nonrectangular containment needs visual/shape review; AABB cannot prove it')
                if any(abs(bounds['objects'][i]['world'][k])>1e-8 for i in r['object_ids'] for k in (1,2)):
                    raise NotImplementedError('rotated container needs shape review')
            ds=proposals(r,bounds['objects'])
            reports.append({'id':r['id'],'status':'satisfied' if all(abs(n)<=1e-3 for d in ds.values() for n in d) else 'violated','residuals':ds})
        except (KeyError,ValueError,NotImplementedError) as e:reports.append({'id':r['id'],'status':'unresolved','reason':str(e)})
    return reports

def _execute_ops(root,ops,issues,original,folder,relations=()):
    result=deepcopy(root);results={};log=[];byissue={i['id']:i for i in issues}
    for op in ops:
        by=nodes(result);ids=op.get('target_ids',[]);a=op.get('args',{});action=op['action'];issue=byissue[op['issue_id']]
        if not ids or any(i not in by for i in ids):raise ValueError('operation needs existing target IDs')
        scope=set(issue.get('_scope_ids',[]))|{n.get('id') for i in issue['target_ids'] if i in by for n in by[i].iter()}
        if not set(ids)<=scope:raise ValueError('target outside semantic issue scope')
        if action in ('translate','align','scale','fit'):
            b=measure(result)
            if action=='translate':m=[1,0,0,1,number(a['dx']),number(a['dy'])]
            elif action=='align':
                dx,dy=alignment_delta(union_bounds(ids,b['objects']),union_bounds(a['reference_ids'],b['objects']),a['mode'],a.get('gap',0));m=[1,0,0,1,dx,dy]
            elif action=='scale':m=scaling_matrix(a)
            else:
                box=union_bounds(ids,b['objects']);x,y,w,h=[number(v) for v in a['world_box']]
                if min(w,h,box['right']-box['left'],box['bottom']-box['top'])<=0:raise ValueError('empty fit box')
                sx=w/(box['right']-box['left']);sy=h/(box['bottom']-box['top'])
                if a.get('uniform',True):sx=sy=min(sx,sy)
                m=[sx,0,0,sy,x-box['left']*sx,y-box['top']*sy]
            move(result,ids,m,b)
        elif action=='relink':
            import base64
            catalog=json.loads((Path(folder)/'asset-catalog.json').read_text(encoding='utf-8'))
            asset_id=a['asset_id']
            if asset_id not in catalog:raise ValueError('unknown board asset ID')
            if any(tag(by[i])!='image' for i in ids):raise ValueError('relink requires image targets')
            data=Path(catalog[asset_id]).read_bytes()
            for i in ids:
                by[i].attrib.pop('{http://www.w3.org/1999/xlink}href',None)
                by[i].set('href','data:image/png;base64,'+base64.b64encode(data).decode())
        elif action=='patch':
            # Partial attributes preserve unspecified style/geometry and IDs.
            allowed={'x','y','x1','x2','y1','y2','width','height','rx','ry','cx','cy','r','d','points','fill','stroke','stroke-width','stroke-dasharray','stroke-dashoffset','opacity','fill-opacity','font-size','font-family','font-weight','font-style','text-anchor','dominant-baseline','marker-start','marker-end','transform','data-plus-kind','style','stroke-linecap','stroke-linejoin'}
            attrs=a.get('attributes',{})
            if set(attrs)-allowed:raise ValueError('unsupported SVG patch attribute')
            if attrs.get('d') is not None and len(ids)>1:
                measured=measure(result)
                worlds={tuple(measured['objects'][i]['world']) for i in ids}
                if len(worlds)==1 and len({by[i].get('d') for i in ids})>1:
                    raise ValueError('shared path data would collapse distinct paths in one coordinate system; provide separate paths per target')
            for i in ids:
                for k,v in attrs.items():
                    if v is None:by[i].attrib.pop(k,None)
                    else:
                        by[i].set(k,str(v))
                        if k in {'fill','stroke','stroke-width','stroke-dasharray','opacity','fill-opacity','font-size','font-family','font-weight','font-style','text-anchor','dominant-baseline','marker-start','marker-end'}:
                            styles=dict(x.split(':',1) for x in by[i].get('style','').split(';') if ':' in x)
                            styles[k]=str(v);by[i].set('style',';'.join(key+':'+value for key,value in styles.items()))
                if 'text' in a:
                    if tag(by[i])!='text':raise ValueError('text patch needs text node')
                    for c in list(by[i]):by[i].remove(c)
                    by[i].text=a['text']
        elif action=='sp':replacement(result,ids,sp_element(a['kind'],a['data'],op['id']))
        elif action=='svg':
            # Local VLM-written fallback, interpreted as SVG, never executable code.
            fragment=parse('<svg xmlns="'+SVG+'">'+a['fragment']+'</svg>')
            def drawable(node):
                if tag(node) in ('defs','pattern','marker','clipPath','mask','symbol','style','title','desc'):return False
                return tag(node) in ('rect','circle','ellipse','polygon','polyline','path','line','text','image','use') or any(drawable(c) for c in node)
            if not drawable(fragment):raise ValueError('replacement contains no visible drawing, only definitions/empty groups')
            g=ET.Element('{'+SVG+'}g');g.extend(list(fragment))
            # Prefix fragment identities/references without changing geometry.
            prefix='local_'+op['id']+'_'+str(len(by))+'_'
            mapping={n.get('id'):prefix+n.get('id') for n in g.iter() if n.get('id')}
            for n in g.iter():
                for key,value in list(n.attrib.items()):
                    if key=='id':n.set(key,mapping[value])
                    else:
                        for old,new in mapping.items():value=value.replace('url(#'+old+')','url(#'+new+')')
                        if key.endswith('href') and value.startswith('#') and value[1:] in mapping:value='#'+mapping[value[1:]]
                        n.set(key,value)
            replacement(result,ids,g)
        elif action=='create':
            if len(ids)!=1:raise ValueError('create requires one existing parent')
            new_id=a['id']
            if new_id in by:raise ValueError('create ID already exists')
            g=sp_element(a['kind'],a['data'],op['id']);g.set('id',new_id);by[ids[0]].append(g)
        elif action=='remove':
            par=parents(result)
            for i in ids:
                if by[i] not in par:raise ValueError('cannot remove SVG root')
                par[by[i]].remove(by[i])
        elif action=='asset':
            classification=a['classification']
            if classification not in ('photo','complex_geometry','abstract'):raise ValueError('asset needs explicit semantic classification')
            backend=a.get('backend','imagetracerjs')
            if backend not in ('imagetracerjs','vtracer'):raise ValueError('only registered curve tracing candidates are enabled')
            asset=remove_background_asset(crop_asset(original,a['source_crop'],Path(folder)/'assets'),Path(folder)/'assets')
            data=dict(zip(('x','y','width','height'),a['target_box']));data['asset_id']=asset['id']
            if classification=='photo':
                p=raster_part(data,[asset]);g=ET.Element('{'+SVG+'}g');ET.SubElement(g,'{'+SVG+'}image',{k:str(v) for k,v in p['attrs'].items()})
            else:
                asset=vectorize_asset(asset,backend,Path(folder)/'assets');data['asset_id']=asset['id']
                g=ET.Element('{'+SVG+'}g');g.append(vector_element(data,[asset],op['id']))
            replacement(result,ids,g);results[op['id']]=asset
        elif action=='sample_color':
            import cv2
            import numpy as np
            # Model selects semantic face/line ROI; code returns dominant color.
            x,y,w,h=[number(v) for v in a['source_crop']];im=imread(str(original),cv2.IMREAD_COLOR)
            x0,y0=max(0,math.floor(x)),max(0,math.floor(y));x1,y1=min(im.shape[1],math.ceil(x+w)),min(im.shape[0],math.ceil(y+h))
            if x1<=x0 or y1<=y0:raise ValueError('empty color sample')
            roi=im[y0:y1,x0:x1].reshape(-1,3);colors,counts=np.unique(roi,axis=0,return_counts=True);b,g,r=map(int,colors[counts.argmax()]);color=f'#{r:02x}{g:02x}{b:02x}'
            attr=a.get('attribute','fill')
            if attr not in ('fill','stroke'):raise ValueError('color attribute must be fill/stroke')
            for i in ids:
                by[i].set(attr,color)
                styles=dict(x.split(':',1) for x in by[i].get('style','').split(';') if ':' in x);styles[attr]=color;by[i].set('style',';'.join(k+':'+v for k,v in styles.items()))
            results[op['id']]={'color':color,'method':'OpenCV ROI dominant color','source_crop':a['source_crop']}
        elif action=='constrain':
            rr=a['relations'];movable=set(a['movable_ids'])
            if not movable<=scope:raise ValueError('movable TP outside issue scope')
            seen=set();trace=[]
            for _ in range(6):
                key=serialize(result)
                if key in seen:break
                seen.add(key);b=measure(result);reports=check_relations(result,rr,b);trace.append(reports)
                if all(r['status'] in ('satisfied','declared_legal') for r in reports):break
                for relation,report in zip(rr,reports):
                    if report['status']!='violated':continue
                    ds=proposals(relation,measure(result)['objects'])
                    if not set(ds)<=movable:raise ValueError('constraint attempts undeclared move')
                    # Move same-delta selection once, preventing ancestor double transforms.
                    groups={}
                    for i,d in ds.items():groups.setdefault(tuple(d),[]).append(i)
                    for d,members in groups.items():move(result,members,[1,0,0,1,*d],measure(result))
            results[op['id']]={'iterations':trace,'final':check_relations(result,rr),'quality_passed':False}
        else:raise ValueError('unregistered native tool '+action)
        validate(result)
        log.append({'id':op['id'],'action':action,'status':'executed','result':results.get(op['id']), 'joint_relations':check_relations(result,relations) if relations else [],'visual_passed':False})
    return result,log


def execute(root,ops,issues,original,folder,relations=()):
    result=deepcopy(root);logs=[]
    initial=nodes(root);issues=deepcopy(issues)
    for issue in issues:issue['_scope_ids']=[n.get('id') for i in issue['target_ids'] if i in initial for n in initial[i].iter()]
    for op in ops:
        try:
            result,step=_execute_ops(result,[op],issues,original,folder,relations)
            if op['action'] in ('svg','sp','asset'):
                measured=measure(result);box=measured['objects'][op['target_ids'][0]]['geometry_bbox'];c=measured['canvas']
                if box['right']<=box['left'] or box['bottom']<=box['top']:raise ValueError('replacement has empty measured geometry')
                if box['right']<=c['x'] or box['bottom']<=c['y'] or box['left']>=c['x']+c['width'] or box['top']>=c['y']+c['height']:raise ValueError('replacement entirely outside visible canvas')
            logs.extend(step)
        except (ValueError,KeyError,TypeError,IndexError) as e:
            raise ValueError(f"operation {op.get('id')} ({op.get('action')}): {e}") from e
    return result,logs
