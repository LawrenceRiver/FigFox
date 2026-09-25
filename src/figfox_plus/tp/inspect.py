"""Conservative overlap evidence, never an automatic quality decision."""
from itertools import combinations
from ..executor import descendants


def inspect_overlaps(scene,measured):
    objects={o['id']:o for o in scene['objects']};result=[]
    legal=set()
    for r in scene.get('relations',[]):
        if r.get('predicate')=='legal_overlap':
            legal.update(frozenset((a,b)) for a in r['subject_ids'] for b in r['object_ids'])
    for a,b in combinations(objects,2):
        x=measured[a]['paint_bbox'];y=measured[b]['paint_bbox']
        overlap={'left':max(x['left'],y['left']),'right':min(x['right'],y['right']),
                 'top':max(x['top'],y['top']),'bottom':min(x['bottom'],y['bottom'])}
        if overlap['right']<=overlap['left'] or overlap['bottom']<=overlap['top']:continue
        hierarchy=b in descendants(a,objects) or a in descendants(b,objects)
        result.append({'target_ids':[a,b],'status':'hierarchy_overlap' if hierarchy else
            'declared_legal' if frozenset((a,b)) in legal else 'candidate','intersection':overlap,
            'evidence':'conservative paint boxes overlap; inspect actual image','automatic_error':False})
    return result


def inspect_relations(scene,measured):
    """Report model-declared relation residuals without modifying its scene."""
    from .relations import proposals
    records=[]
    for relation in scene.get('relations',[]):
        record={'id':relation['id'],'description':relation['description']}
        try:
            moves=proposals(relation,measured)
            record.update(status='satisfied' if all(abs(v)<=1e-3 for d in moves.values() for v in d) else 'violated',
                          required_world_displacements=moves)
        except NotImplementedError as error:record.update(status='unresolved',reason=str(error))
        except (ValueError,KeyError,TypeError,IndexError) as error:record.update(status='conflict',reason=str(error))
        records.append(record)
    return records
