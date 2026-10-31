"""Current-only mechanical observations; no reference, labels, or defect verdicts."""
import re


def current_diagnostics(root,tp):
    tag=lambda n:n.tag.rsplit('}',1)[-1]
    nodes={n.get('id'):n for n in root.iter() if n.get('id')}
    parents={c:p for p in root.iter() for c in p}
    boxes={oid:item['tight_bbox'] for oid,item in tp['objects'].items()
           if item.get('status')=='measured' and item.get('tight_bbox') and oid in nodes}
    def area(b):return max(0,b['right']-b['left'])*max(0,b['bottom']-b['top'])
    def intersect(a,b):
        return max(0,min(a['right'],b['right'])-max(a['left'],b['left']))*max(0,min(a['bottom'],b['bottom'])-max(a['top'],b['top']))
    # Include image/geometry-only containers, not just rectangles with text.
    frames={oid:b for oid,b in boxes.items() if tag(nodes[oid])=='rect'
            and any(other!=oid and 0<area(t)<area(b) and intersect(b,t)/area(t)>=0.5
                    for other,t in boxes.items())}
    boundary=[]
    for oid,b in boxes.items():
        if tag(nodes[oid]) not in {'text','use','image','polygon','rect','circle','ellipse'} or area(b)<=0:continue
        candidates=[(fid,f) for fid,f in frames.items() if fid!=oid and area(f)>area(b)
                    and intersect(f,b)/area(b)>=0.2]
        if not candidates:continue
        fid,f=min(candidates,key=lambda pair:area(pair[1]))
        margins=[b['left']-f['left'],b['top']-f['top'],f['right']-b['right'],f['bottom']-b['bottom']]
        if min(margins)<=0.25:
            boundary.append({'subject_id':oid,'possible_container_id':fid,'margins_ltrb':margins,
                             'basis':'smallest intersecting rectangle containing visible content; AABB only',
                             'requires_reference_relationship_check':True})
    def inherited(node,name):
        while node is not None:
            style=dict(re.findall(r'([\w-]+)\s*:\s*([^;]+)',node.get('style','')))
            if name in style:return style[name].strip()
            if name in node.attrib:return node.get(name)
            node=parents.get(node)
        return None
    open_fill=[]
    def segment_count(part):
        arity={'l':2,'h':1,'v':1,'c':6,'s':4,'q':4,'t':2,'a':7}
        total=0
        for command,values in re.findall(r'([LlHhVvCcSsQqTtAa])([^LlHhVvCcSsQqTtAa]*)',part):
            numbers=re.findall(r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?',values)
            total+=len(numbers)//arity[command.lower()]
        return total
    for oid,node in nodes.items():
        if tag(node)!='path' or inherited(node,'fill') is not None:continue
        if inherited(node,'stroke') in (None,'none'):continue
        parts=re.split(r'[Mm]',node.get('d',''))[1:]
        if not any(not re.search('[Zz]',p) and segment_count(p)>=2 for p in parts):continue
        ancestors=set();n=node
        while n is not None:
            if n.get('id'):ancestors.add(n.get('id'))
            n=parents.get(n)
        instances=[uid for uid,u in nodes.items() if tag(u)=='use'
                   and (u.get('href') or u.get('{http://www.w3.org/1999/xlink}href',''))[1:] in ancestors]
        open_fill.append({'source_id':oid,'instance_ids':instances,
                          'observation':'stroked open multi-segment subpath has no explicit inherited fill; CSS may override default closed fill',
                          'requires_render_and_reference_check':True})
    return {'domain':'current_svg_only','diagnosis_confirmed':False,
            'instruction':'These are fallible mechanical candidates, not defects. Confirm actual contours and original relationships visually; never map these coordinates to original material crops. Continue checking regions not listed.',
            'boundary_candidates':boundary,'open_fill_candidates':open_fill}
