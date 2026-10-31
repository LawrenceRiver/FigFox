"""Bounded single-pass relation proposals, followed by hard-constraint checks."""
from copy import deepcopy
from math import isfinite
from ..executor import execute,descendants
from ..sp.compiler import compile_scene
from ..render import measure


def delta(relation,measured):
    from .groups import union_bounds
    s=union_bounds(relation['subject_ids'],measured);r=union_bounds(relation['object_ids'],measured)
    p=relation['predicate'];args=relation.get('params',{});gap=args.get('gap',0)
    if p in ('center_symmetry','axis_symmetry'):
        sx=(s['left']+s['right'])/2;sy=(s['top']+s['bottom'])/2
        rx=(r['left']+r['right'])/2;ry=(r['top']+r['bottom'])/2
        if p=='center_symmetry':
            cx,cy=args['center'];return 2*cx-rx-sx,2*cy-ry-sy
        axis=args['axis'];position=args['position']
        if axis=='x':return 2*position-rx-sx,ry-sy
        if axis=='y':return rx-sx,2*position-ry-sy
        raise ValueError('axis must be x or y')
    if p=='avoid':
        limit=args['max_distance'];directions=args['directions']
        if gap<0 or limit<0:raise ValueError('avoid gap/distance must be nonnegative')
        if s['right']<=r['left']-gap+1e-3 or s['left']>=r['right']+gap-1e-3 or s['bottom']<=r['top']-gap+1e-3 or s['top']>=r['bottom']+gap-1e-3:return 0,0
        choices={'left':(r['left']-gap-s['right'],0),'right':(r['right']+gap-s['left'],0),
                 'up':(0,r['top']-gap-s['bottom']),'down':(0,r['bottom']+gap-s['top'])}
        if not directions or any(d not in choices for d in directions):raise ValueError('explicit valid directions required')
        candidates=[choices[d] for d in directions if sum(abs(v) for v in choices[d])<=limit]
        if not candidates:raise ValueError('no avoidance within allowed distance')
        return min(candidates,key=lambda d:sum(abs(v) for v in d))
    if p in ('align_left','align_right'):return r[p[6:]]-s[p[6:]]+(-gap if p=='align_right' else gap),0
    if p in ('align_top','align_bottom'):return 0,r[p[6:]]-s[p[6:]]+(-gap if p=='align_bottom' else gap)
    if p=='center_x':return (r['left']+r['right']-s['left']-s['right'])/2,0
    if p=='center_y':return 0,(r['top']+r['bottom']-s['top']-s['bottom'])/2
    if p=='contain':
        pad=args.get('padding',0)
        if pad<0:raise ValueError('negative padding')
        ranges=[(r['left']+pad-s['left'],r['right']-pad-s['right']),
                (r['top']+pad-s['top'],r['bottom']-pad-s['bottom'])]
        if any(lo>hi for lo,hi in ranges):raise ValueError('subject does not fit container')
        return tuple(max(lo,min(0,hi)) for lo,hi in ranges)
    raise NotImplementedError('unsupported relation: '+str(p))


def validate_params(relation):
    args=relation.get('params',{})
    if not isinstance(args,dict):raise ValueError('params must be an object')
    for key in ('gap','padding','max_distance','position'):
        if key in args and (isinstance(args[key],bool) or not isinstance(args[key],(int,float)) or not isfinite(args[key])):
            raise ValueError(key+' must be a finite number')
    required={'avoid':['directions','max_distance'],'center_symmetry':['center'],'axis_symmetry':['axis','position']}
    for key in required.get(relation['predicate'],[]):
        if key not in args:raise ValueError('missing parameter: '+key)
    if 'directions' in args and (not isinstance(args['directions'],list) or not args['directions'] or any(d not in ('left','right','up','down') for d in args['directions'])):
        raise ValueError('directions must be a nonempty list of allowed directions')
    if 'center' in args and (not isinstance(args['center'],list) or len(args['center'])!=2 or any(isinstance(n,bool) or not isinstance(n,(float,int)) or not isfinite(n) for n in args['center'])):
        raise ValueError('center must be two finite coordinates')


def proposals(relation,measured):
    validate_params(relation)
    if relation['predicate'] not in ('center_spacing','edge_gap'):
        move=delta(relation,measured)
        return {oid:move for oid in relation['subject_ids']}
    ids=relation['subject_ids'];args=relation.get('params',{})
    if len(ids)<2 or len(relation['object_ids'])!=1:raise ValueError('spacing needs members and one container')
    axis=args.get('axis','x')
    if axis not in ('x','y'):raise ValueError('invalid spacing axis')
    lo,hi=('left','right') if axis=='x' else ('top','bottom')
    container=measured[relation['object_ids'][0]]['paint_bbox'];pad=args.get('padding',0)
    if pad<0:raise ValueError('negative padding')
    start=container[lo]+pad;length=container[hi]-pad-start
    boxes=[measured[i]['paint_bbox'] for i in ids];sizes=[b[hi]-b[lo] for b in boxes]
    gap=(length-sum(sizes))/(len(ids)+1)
    if relation['predicate']=='edge_gap' and gap<0:raise ValueError('members do not fit')
    cursor=start+gap;moves={}
    for n,(oid,b,size) in enumerate(zip(ids,boxes,sizes)):
        target=cursor if relation['predicate']=='edge_gap' else start+length*(n+.5)/len(ids)-size/2
        if target<start-1e-6 or target+size>start+length+1e-6:raise ValueError('member exceeds container')
        offset=target-b[lo];moves[oid]=(offset,0) if axis=='x' else (0,offset)
        cursor+=size+gap
    return moves


def solve_relations(scene,measured=None):
    # Always remeasure; caller-supplied bounds may be stale after edits.
    result=deepcopy(scene);reports=[];hard=[]
    ordered=sorted(scene.get('relations',[]),key=lambda r:r.get('priority')!='hard')
    for relation in ordered:
        record={'id':relation['id'],'description':relation['description']}
        try:
            bounds=measure(*compile_scene(result));moves=proposals(relation,bounds)
            objects={o['id']:o for o in result['objects']}
            scope=set().union(*(descendants(i,objects) for i in relation['subject_ids']))
            scope.update(o['id'] for o in objects.values() if o['kind']=='arrow' and any(
                o['data'].get(end,{}).get('object_id') in scope for end in ('start','end')))
            if any(a!=b and b in descendants(a,objects) for a in moves for b in moves):
                raise ValueError('relation members cannot include ancestor and descendant')
            variants=[moves]
            if relation['predicate']=='avoid':
                variants=[]
                for direction in relation['params']['directions']:
                    alternative=deepcopy(relation);alternative['params']['directions']=[direction]
                    try:variants.append(proposals(alternative,bounds))
                    except ValueError:pass
                variants.sort(key=lambda v:sum(abs(x) for d in v.values() for x in d))
            failures=[]
            for variant in variants:
                try:
                    candidate,_=execute(result,[{'id':'relation-'+relation['id']+'-'+oid,'action':'translate',
                        'target_ids':[oid],'args':{'dx':d[0],'dy':d[1]}} for oid,d in variant.items()],scope)
                    after=measure(*compile_scene(candidate))
                    for constraint in hard+[relation]:
                        if any(abs(v)>1e-3 for d in proposals(constraint,after).values() for v in d):
                            raise ValueError('conflicts with relation '+constraint['id'])
                    break
                except ValueError as error:failures.append(str(error))
            else:raise ValueError('; '.join(failures) or 'no allowed candidate')
            result=candidate;record['status']='satisfied'
            if relation.get('priority')=='hard':hard.append(relation)
        except NotImplementedError as error:
            record.update(status='unresolved',reason=str(error))
        except ValueError as error:
            record.update(status='conflict',reason=str(error))
        reports.append(record)
    return result,reports
