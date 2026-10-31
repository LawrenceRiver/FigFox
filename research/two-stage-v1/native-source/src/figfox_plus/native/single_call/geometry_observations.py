"""Reference-free current SVG geometry facts, not automatic defect labels."""
import math
import re
from collections import defaultdict
from itertools import combinations

NUMBER=r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?'


def _cross(a,b,c):return (b[0]-a[0])*(c[1]-a[1])-(b[1]-a[1])*(c[0]-a[0])
def _area(p):return sum(a[0]*b[1]-a[1]*b[0] for a,b in zip(p,p[1:]+p[:1]))/2


def _polygon(node):
    if node.get('transform') or node.get('fill')=='none':return None
    nums=[float(x) for x in re.findall(NUMBER,node.get('points',''))]
    if len(nums)<6 or len(nums)%2 or not all(math.isfinite(x) for x in nums):return None
    p=list(zip(nums[::2],nums[1::2]))
    if p[0]==p[-1]:p.pop()
    if len(p)<3 or abs(_area(p))<1e-9:return None
    turns=[_cross(p[i-1],p[i],p[(i+1)%len(p)]) for i in range(len(p))]
    if any(v>1e-9 for v in turns) and any(v<-1e-9 for v in turns):return None
    return p


def _intersection(subject,clip):
    output=list(subject);sign=1 if _area(clip)>0 else -1
    for a,b in zip(clip,clip[1:]+clip[:1]):
        source=output;output=[]
        if not source:break
        prev=source[-1];pv=sign*_cross(a,b,prev)
        for point in source:
            value=sign*_cross(a,b,point)
            if (value>=-1e-9)!=(pv>=-1e-9):
                fraction=pv/(pv-value)
                output.append((prev[0]+fraction*(point[0]-prev[0]),prev[1]+fraction*(point[1]-prev[1])))
            if value>=-1e-9:output.append(point)
            prev,pv=point,value
    return abs(_area(output)) if len(output)>=3 else 0


def geometry_observations(root):
    tag=lambda n:n.tag.rsplit('}',1)[-1]
    parents={c:p for p in root.iter() for c in p}
    def instances(node):
        ancestors=set()
        while node is not None:
            if node.get('id'):ancestors.add(node.get('id'))
            node=parents.get(node)
        return [u.get('id') for u in root.iter() if tag(u)=='use' and u.get('id')
                and (u.get('href') or u.get('{http://www.w3.org/1999/xlink}href',''))[1:] in ancestors]
    overlaps=[]
    for parent in root.iter():
        faces=[(n,_polygon(n)) for n in parent if tag(n)=='polygon' and n.get('id')]
        for (na,a),(nb,b) in combinations(faces,2):
            if a is None or b is None:continue
            edges_a={frozenset((x,y)) for x,y in zip(a,a[1:]+a[:1])}
            edges_b={frozenset((x,y)) for x,y in zip(b,b[1:]+b[:1])}
            if not edges_a&edges_b:continue
            area=_intersection(a,b)
            if area<=max(1e-6,0.01*min(abs(_area(a)),abs(_area(b)))):continue
            overlaps.append({'source_ids':[na.get('id'),nb.get('id')],
                'instance_ids':instances(parent),'intersection_area_local':round(area,6),
                'observation':'same-parent convex polygons share an edge but their interiors also overlap; may be intentional layering, or incorrectly projected opaque faces',
                'requires_reference_check':True})
    css='\n'.join(''.join(n.itertext()) for n in root.iter() if tag(n)=='style')
    rules=defaultdict(str)
    for selectors,body in re.findall(r'([^{}]+)\{([^{}]*)\}',css):
        for name in re.findall(r'\.([\w-]+)',selectors):rules[name]+=';'+body
    groups=defaultdict(list)
    for node in root.iter():
        if tag(node)!='path' or not node.get('id') or node.get('transform'):continue
        declarations=node.get('style','')+';'.join(rules[c] for c in node.get('class','').split())
        if not (node.get('marker-end') or node.get('marker-start') or re.search(r'marker-(?:end|start)\s*:',declarations)):continue
        m=re.fullmatch(r'\s*M\s*('+NUMBER+r')[ ,]+('+NUMBER+r')\s*([VH])\s*('+NUMBER+r')\s*',node.get('d',''))
        if not m:continue
        x,y,end=float(m[1]),float(m[2]),float(m[4]);direction=m[3]
        if not all(math.isfinite(v) for v in (x,y,end)):continue
        base=y if direction=='V' else x;position=x if direction=='V' else y
        key=(parents.get(node),direction,base,node.get('class',''),node.get('stroke',''))
        groups[key].append({'id':node.get('id'),'position_local':position,'start_local':base,'end_local':end,'length_local':abs(end-base)})
    parallel=[]
    for (_,direction,base,_,_),members in groups.items():
        if len(members)<4:continue
        members.sort(key=lambda x:x['position_local'])
        differences=[abs(members[i]['length_local']-members[-1-i]['length_local']) for i in range(len(members)//2)]
        if max(differences,default=0)<0.5:continue
        parallel.append({'subject_ids':[m['id'] for m in members],'axis':direction,'common_start_local':base,
            'members':members,'mirror_length_differences':differences,
            'observation':'parallel arrows sharing a start line do not have equal mirrored lengths; this alone does not establish intended symmetry',
            'requires_reference_symmetry_check':True})
    return {'shared_face_overlap_candidates':overlaps,'parallel_group_candidates':parallel}
