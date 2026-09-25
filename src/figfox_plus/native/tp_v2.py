"""Explicit TP selections and world-coordinate transformations on measured paint."""
from copy import deepcopy
import math,re
import xml.etree.ElementTree as ET
from .document import measure,serialize,validate
from .tight_tp import measure_tight,union_tight
from .sp_v2 import canonical_targets,fit_matrix,_css_unescape
from ..tp.transforms import compose,inverse

def selection(root,ids,scale=4):
    members=canonical_targets(root,ids);measured=measure_tight(root,members,scale=scale)
    bbox=union_tight(measured,members)
    if bbox is None:raise ValueError('selection has no visible TP')
    return {'ids':members,'bbox':bbox,'measurement':measured}

def transform(root,ids,world_matrix,scale=4):
    """Apply once per topmost selected subtree, converting through each parent CTM."""
    if len(world_matrix)!=6 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in world_matrix):raise ValueError('matrix requires six finite numbers')
    inverse(world_matrix)
    trial=deepcopy(root);before=selection(trial,ids,scale);geometry=measure(trial)['objects'];nodes={n.get('id'):n for n in trial.iter() if n.get('id')}
    affected={n for i in before['ids'] for n in nodes[i].iter()};affected_ids={n.get('id') for n in affected if n.get('id')}
    for n in trial.iter():
        if n in affected:continue
        values=[*n.attrib.values()]+([''.join(n.itertext())] if n.tag.rsplit('}',1)[-1]=='style' else [])
        refs=set()
        for value in values:refs.update(re.findall(r'url\(\s*[\"\']?#([^\s)\"\']+)',_css_unescape(value),re.I))
        for k,v in n.attrib.items():
            if k.rsplit('}',1)[-1]=='href' and v.startswith('#'):refs.add(v[1:])
        if refs&affected_ids:raise ValueError('transform would change an unselected reference consumer')
    parents={c:p for p in trial.iter() for c in p}
    for i in before['ids']:
        o=geometry[i];local=compose(inverse(o['parent_world']),compose(world_matrix,o['world']))
        if nodes[i].tag.rsplit('}',1)[-1]=='svg':
            if any(n.tag.rsplit('}',1)[-1]=='style' for n in trial.iter()):raise ValueError('nested SVG wrapper with stylesheet requires explicit constructor replacement')
            parent=parents[nodes[i]];position=list(parent).index(nodes[i])
            delta=compose(inverse(o['parent_world']),compose(world_matrix,o['parent_world']))
            wrapper=ET.Element('{http://www.w3.org/2000/svg}g',{'data-plus-tp-wrapper':'true','transform':'matrix('+' '.join(format(v,'.15g') for v in delta)+')'})
            parent.remove(nodes[i]);wrapper.append(nodes[i]);parent.insert(position,wrapper);continue
        # SVG transform attribute would be overridden by an existing CSS transform.
        node=nodes[i];style=node.get('style','')
        if 'transform' in style or any(n.tag.rsplit('}',1)[-1]=='style' for n in trial.iter()):
            # Explicit inline geometry override preserves the measured CTM; origin is zero.
            css='matrix('+','.join(format(v,'.15g') for v in local)+')'
            node.set('style',style+';transform:'+css+' !important;transform-origin:0 0 !important;transform-box:view-box !important')
        else:node.set('transform','matrix('+' '.join(format(v,'.15g') for v in local)+')')
    validate(trial);after=selection(trial,before['ids'],scale)
    root.attrib.clear();root.attrib.update(trial.attrib);root[:]=list(trial)
    return {'selected_ids':before['ids'],'before':before['bbox'],'after':after['bbox'],'world_matrix':list(world_matrix),'temporary_selection':True}

def align(root,ids,reference_ids,mode='center_x',scale=4):
    a=selection(root,ids,scale)['bbox'];b=selection(root,reference_ids,scale)['bbox']
    if mode=='center_x':dx=(b['left']+b['right']-a['left']-a['right'])/2;dy=0
    elif mode=='center_y':dy=(b['top']+b['bottom']-a['top']-a['bottom'])/2;dx=0
    elif mode in ('left','right'):dx=b[mode]-a[mode];dy=0
    elif mode in ('top','bottom'):dy=b[mode]-a[mode];dx=0
    else:raise ValueError('unknown alignment')
    selected=canonical_targets(root,ids);refs=canonical_targets(root,reference_ids)
    by={n.get('id'):n for n in root.iter() if n.get('id')}
    if any(by[r] in set(by[s].iter()) or by[s] in set(by[r].iter()) for s in selected for r in refs):raise ValueError('reference moves with selection; specify independent reference')
    return transform(root,ids,[1,0,0,1,dx,dy],scale)

def fit(root,ids,target_tp,mode='contain',scale=4):
    source=selection(root,ids,scale)['bbox']
    return transform(root,ids,fit_matrix(source,target_tp,mode),scale)
