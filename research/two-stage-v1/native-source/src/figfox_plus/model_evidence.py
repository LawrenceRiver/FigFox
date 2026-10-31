"""Remove duplicated serialization, never supply reference-specific answer values."""
from copy import deepcopy

def public_scene(scene):
    result=deepcopy(scene)
    result['assets']=[{k:v for k,v in a.items() if k in ('id','source_crop','representation','role','source_size','backend')} for a in scene.get('assets',[])]
    return result

def compact_evidence(pack):
    frames=[]
    for f in pack.get('frames',[]):
        item={k:v for k,v in f.items() if k!='images'}
        item['images']=[{k:v for k,v in im.items() if k!='path'} for im in f['images']];frames.append(item)
    overlaps=[]
    for o in pack.get('overlaps',[]):
        b=o['intersection'];overlaps.append([*o['target_ids'],o['status'],b['left'],b['top'],b['right'],b['bottom'],o.get('automatic_error',False)])
    return {'frames':frames,'relations':pack.get('relations',[]),'overlap_columns':['first_id','second_id','status','left','top','right','bottom','automatic_error'],'overlaps':overlaps,'overlap_note':'Conservative candidate bounds only, not proof of unwanted overlap. Hierarchy overlaps are normally expected; compare original/current visually.'}
