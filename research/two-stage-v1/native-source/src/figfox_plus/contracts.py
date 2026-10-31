"""Validate identifiers and relationships before generating any SVG."""
import math
import re

KINDS = {'frame','geometry','text','formula','arrow','picture','group','vector_asset'}
ID = re.compile(r'[A-Za-z][A-Za-z0-9_-]*\Z')


def validate_scene(scene: dict) -> list[dict]:
    errors=[]
    def err(code,path,detail=''):
        errors.append({'code':code,'path':path,'detail':str(detail)})
    def finite(value,path):
        if isinstance(value,float) and not math.isfinite(value): err('non_finite',path)
        elif isinstance(value,dict):
            for k,v in value.items(): finite(v,f'{path}.{k}')
        elif isinstance(value,list):
            for i,v in enumerate(value): finite(v,f'{path}[{i}]')
    if not isinstance(scene,dict): return [{'code':'invalid_scene','path':'$','detail':'expected object'}]
    finite(scene,'$')
    if scene.get('version')!='plus-0.1': err('unsupported_version','version')
    canvas=scene.get('canvas',{})
    if not isinstance(canvas,dict): err('invalid_canvas','canvas'); canvas={}
    for key in ('width','height'):
        n=canvas.get(key)
        if isinstance(n,bool) or not isinstance(n,(int,float)) or not math.isfinite(n) or n<=0:
            err('invalid_canvas',f'canvas.{key}')
    objects=scene.get('objects')
    if not isinstance(objects,list): err('invalid_objects','objects'); objects=[]
    by_id={}
    for i,obj in enumerate(objects):
        p=f'objects[{i}]'
        if not isinstance(obj,dict): err('invalid_object',p); continue
        oid=obj.get('id')
        if not isinstance(oid,str) or not ID.fullmatch(oid): err('invalid_id',p); continue
        if oid in by_id: err('duplicate_id',p,oid)
        by_id[oid]=obj
        if obj.get('kind') not in KINDS: err('unsupported_kind',p,obj.get('kind'))
        if not isinstance(obj.get('name'),str) or not obj['name'].strip(): err('missing_name',p)
        if not isinstance(obj.get('data'),dict): err('invalid_data',p)
        matrix=obj.get('matrix',[1,0,0,1,0,0])
        if not isinstance(matrix,list) or len(matrix)!=6 or any(isinstance(n,bool) or not isinstance(n,(float,int)) for n in matrix):
            err('invalid_matrix',p)
        if 'children' in obj: err('ambiguous_membership',p,'use parent_id only')
    for oid,obj in by_id.items():
        parent=obj.get('parent_id')
        if parent is not None and (not isinstance(parent,str) or parent not in by_id):
            err('unknown_parent',oid,parent); continue
        seen={oid}; node=parent
        while isinstance(node,str) and node in by_id:
            if node in seen: err('parent_cycle',oid); break
            seen.add(node); node=by_id[node].get('parent_id')
    relations=scene.get('relations',[])
    if not isinstance(relations,list): err('invalid_relations','relations'); relations=[]
    rids=set()
    for i,r in enumerate(relations):
        p=f'relations[{i}]'
        if not isinstance(r,dict): err('invalid_relation',p); continue
        rid=r.get('id')
        if not isinstance(rid,str) or not ID.fullmatch(rid): err('invalid_id',p)
        elif rid in rids: err('duplicate_id',p,rid)
        else: rids.add(rid)
        if not r.get('description'): err('missing_description',p)
        for key in ('subject_ids','object_ids'):
            ids=r.get(key)
            if not isinstance(ids,list) or not ids: err('missing_relation_participant',p,key); continue
            if len(set(str(x) for x in ids))!=len(ids): err('duplicate_member',p,key)
            for ref in ids:
                if not isinstance(ref,str) or ref not in by_id: err('unknown_reference',p,ref)
    return errors
