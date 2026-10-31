"""Atomic local translation with host-provided scope and endpoint reconnection."""
from copy import deepcopy
from math import isfinite
from .contracts import validate_scene
from .sp.compiler import compile_scene
from .render import measure
from .tp.transforms import IDENTITY,compose,inverse,apply,translate_world


def world(oid,objects):
    obj=objects[oid]
    parent=world(obj['parent_id'],objects) if obj.get('parent_id') else IDENTITY
    return compose(parent,obj.get('matrix',IDENTITY))


def descendants(oid,objects):
    result={oid}
    for child,obj in objects.items():
        if obj.get('parent_id')==oid:result.update(descendants(child,objects))
    return result


def anchor(box,name):
    x=(box['left']+box['right'])/2;y=(box['top']+box['bottom'])/2
    options={'left':[box['left'],y],'right':[box['right'],y],
             'top':[x,box['top']],'bottom':[x,box['bottom']],'center':[x,y]}
    if name not in options:raise ValueError('unsupported anchor')
    return options[name]


def execute(scene,ops,host_scope):
    errors=[e for e in validate_scene(scene) if not e['path'].startswith('relations')]
    if errors:raise ValueError(errors)
    if not isinstance(ops,list):raise ValueError('operations must be a list')
    for op in ops:
        if not isinstance(op,dict) or not isinstance(op.get('id'),str) or not op['id']:
            raise ValueError('operation needs id')
        if op.get('action') not in ('translate','scale','align','reconstruct','reroute','create'):raise ValueError('unsupported action')
        ids=op.get('target_ids');deps=op.get('depends_on',[])
        for name,values in [('target_ids',ids),('depends_on',deps)]:
            if not isinstance(values,list) or any(not isinstance(v,str) for v in values) or len(set(values))!=len(values):
                raise ValueError(name+' must contain unique string IDs')
        if not isinstance(op.get('args'),dict):raise ValueError('operation args must be object')
        if op['action']=='translate':
            for key in ('dx','dy'):
                n=op['args'].get(key)
                if isinstance(n,bool) or not isinstance(n,(int,float)) or not isfinite(n):raise ValueError(key+' must be finite')
    result=deepcopy(scene);objects={o['id']:o for o in result['objects']};log=[];done=set()
    pending=set()
    for op_index,op in enumerate(ops):
        if op['id'] in done or not set(op.get('depends_on',[]))<=done:
            raise ValueError('duplicate operation or unsatisfied dependency')
        ids=set(op['target_ids'])
        if op['action']=='create':
            new=deepcopy(op['args'].get('object'))
            if not isinstance(new,dict) or ids!={new.get('id')} or not ids<=host_scope or ids & objects.keys():raise ValueError('invalid create target or scope')
            if new.get('parent_id') and new['parent_id'] not in host_scope:raise ValueError('create parent outside scope')
            result['objects'].append(new);objects[new['id']]=new;compile_scene(result)
            log.append({'id':op['id'],'status':'executed','created':new['id']});done.add(op['id']);continue
        if not ids or not ids<=objects.keys():raise ValueError('invalid targets')
        affected=set().union(*(descendants(i,objects) for i in ids))
        if not affected<=host_scope:raise ValueError('outside host scope including descendants')
        roots=[i for i in ids if not any(i in descendants(j,objects) for j in ids if i!=j)]
        if op['action']=='translate':
            for i in roots:
                obj=objects[i];parent=world(obj['parent_id'],objects) if obj.get('parent_id') else IDENTITY
                obj['matrix']=translate_world(obj.get('matrix',IDENTITY),parent,op['args']['dx'],op['args']['dy'])
        elif op['action'] in ('scale','align'):
            from .tp.groups import scaling_matrix, union_bounds, alignment_delta, apply_world_transform
            if op['action']=='scale':transform=scaling_matrix(op['args'])
            else:
                args=op['args']
                if set(args)-{'reference_ids','mode','gap'}:raise ValueError('unsupported align argument')
                refs=args.get('reference_ids')
                if not isinstance(refs,list) or not refs or any(not isinstance(i,str) or i not in objects for i in refs):
                    raise ValueError('align needs existing reference_ids')
                if any(descendants(i,objects) & affected for i in refs):
                    raise ValueError('align references must not overlap moving hierarchy')
                bounds=measure(*compile_scene(result))
                dx,dy=alignment_delta(union_bounds(op['target_ids'],bounds),union_bounds(refs,bounds),args.get('mode'),args.get('gap',0))
                transform=[1,0,0,1,dx,dy]
            apply_world_transform(objects,roots,transform,world)
        elif op['action']=='reconstruct':
            if len(ids)!=1 or not isinstance(op['args'].get('data'),dict):raise ValueError('reconstruct needs one target and complete data')
            target=objects[next(iter(ids))]
            kind=op['args'].get('kind',target['kind'])
            if kind!=target['kind']:
                if kind not in ('picture','vector_asset') or target['kind'] not in ('geometry','picture','vector_asset'):
                    raise ValueError('kind conversion only supports local geometry/assets to picture/vector_asset')
                if len(descendants(target['id'],objects))!=1:raise ValueError('asset conversion cannot discard children')
                target['kind']=kind
            target['data']=deepcopy(op['args']['data'])
        elif op['action']=='reroute':
            if len(ids)!=1:raise ValueError('reroute needs one arrow')
            arrow=objects[next(iter(ids))]
            if arrow['kind']!='arrow':raise ValueError('reroute target must be arrow')
            if set(op['args'])-{'route','waypoints','radius'}:raise ValueError('unsupported reroute argument')
            if not {'route','waypoints'}<=op['args'].keys():raise ValueError('reroute needs route and waypoints')
            arrow['data'].update(deepcopy(op['args']))
            measured=measure(*compile_scene(result))
            for end,pos in [('start',0),('end',-1)]:
                binding=arrow['data'].get(end)
                if not binding:continue
                target=binding['object_id']
                if target not in objects or objects[target]['kind']=='arrow':raise ValueError('invalid endpoint binding')
                expected=anchor(measured[target]['geometry_bbox'],binding['anchor'])
                actual=apply(world(arrow['id'],objects),arrow['data']['waypoints'][pos])
                if any(abs(a-b)>1e-3 for a,b in zip(actual,expected)):raise ValueError('reroute endpoint disconnects binding')
            pending.discard(arrow['id'])
        else:raise ValueError('unsupported action')
        linked=[o for o in objects.values() if o['kind']=='arrow' and any(
            o['data'].get(end,{}).get('object_id') in affected for end in ('start','end'))]
        if any(o['id'] not in host_scope for o in linked):raise ValueError('linked arrow outside host scope')
        if linked:
            measured=measure(*compile_scene(result))
            for arrow in linked:
                data=arrow['data']
                if data.get('route','polyline')!='line':
                    if not any(later.get('action')=='reroute' and later.get('target_ids')==[arrow['id']]
                               for later in ops[op_index+1:]):
                        raise ValueError('anchored non-line route needs later explicit rerouting')
                    pending.add(arrow['id']);continue
                inv=inverse(world(arrow['id'],objects))
                for end,pos in [('start',0),('end',-1)]:
                    binding=data.get(end)
                    if not binding:continue
                    target=binding['object_id']
                    if target not in objects or objects[target]['kind']=='arrow':raise ValueError('invalid arrow binding')
                    point=anchor(measured[target]['geometry_bbox'],binding['anchor'])
                    data['waypoints'][pos]=apply(inv,point)
        compile_scene(result)  # reject invalid geometry before returning any mutation
        from .tp.groups import joint_recheck
        log.append({'id':op['id'],'status':'executed','moved_roots':roots,
                    'reconnected':[o['id'] for o in linked if o['id'] not in pending],
                    'pending_reroute':sorted(pending),
                    'joint_checks':joint_recheck(result)})
        done.add(op['id'])
    if pending:raise ValueError('unresolved reroutes')
    return result,log
