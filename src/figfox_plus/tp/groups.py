"""Temporary world-space selections, with no new SVG parent or persistent grouping."""
from math import isfinite
from .transforms import IDENTITY, compose, inverse


def union_bounds(ids, measured, field='paint_bbox'):
    if not isinstance(ids, list) or not ids or len(set(ids)) != len(ids):
        raise ValueError('selection requires unique IDs')
    if any(i not in measured for i in ids):
        raise ValueError('selection contains unknown ID')
    boxes=[measured[i][field] for i in ids]
    if any(not all(isfinite(b[k]) for k in ('left','right','top','bottom')) for b in boxes):
        raise ValueError('nonfinite selection bounds')
    return dict(left=min(b['left'] for b in boxes),right=max(b['right'] for b in boxes),
                top=min(b['top'] for b in boxes),bottom=max(b['bottom'] for b in boxes))


def selection_bounds(scene, ids, measured=None):
    if measured is None:
        from ..sp.compiler import compile_scene
        from ..render import measure
        measured=measure(*compile_scene(scene))
    return union_bounds(ids, measured)


def alignment_delta(subject, reference, mode, gap=0):
    if isinstance(gap,bool) or not isinstance(gap,(int,float)) or not isfinite(gap):
        raise ValueError('alignment gap must be finite')
    if mode in ('left','right','top','bottom'):
        offset=reference[mode]-subject[mode]+(-gap if mode in ('right','bottom') else gap)
        return (offset,0) if mode in ('left','right') else (0,offset)
    if mode=='center_x':return (reference['left']+reference['right']-subject['left']-subject['right'])/2+gap,0
    if mode=='center_y':return 0,(reference['top']+reference['bottom']-subject['top']-subject['bottom'])/2+gap
    raise ValueError('unsupported group alignment mode')


def scaling_matrix(args):
    if set(args)-{'sx','sy','pivot'}:raise ValueError('unsupported scale argument')
    sx,sy=args.get('sx'),args.get('sy')
    if any(isinstance(n,bool) or not isinstance(n,(int,float)) or not isfinite(n) or n<=0 for n in (sx,sy)):
        raise ValueError('scale factors must be positive finite values')
    pivot=args.get('pivot')
    if not isinstance(pivot,list) or len(pivot)!=2 or any(isinstance(n,bool) or not isinstance(n,(int,float)) or not isfinite(n) for n in pivot):
        raise ValueError('scale needs explicit world pivot [x,y]')
    x,y=pivot
    return [sx,0,0,sy,x*(1-sx),y*(1-sy)]


def apply_world_transform(objects, roots, transform, world):
    # Snapshot all parent matrices before changing any selected root.
    parents={i:world(objects[i]['parent_id'],objects) if objects[i].get('parent_id') else IDENTITY for i in roots}
    for i in roots:
        parent=parents[i];local=objects[i].get('matrix',IDENTITY)
        objects[i]['matrix']=compose(inverse(parent),compose(transform,compose(parent,local)))


def joint_recheck(scene, measured=None):
    """Report all declared relations and overlap candidates together; never auto-accept."""
    from ..sp.compiler import compile_scene
    from ..render import measure
    from .inspect import inspect_overlaps, inspect_relations
    if measured is None:measured=measure(*compile_scene(scene))
    return dict(relations=inspect_relations(scene,measured),overlaps=inspect_overlaps(scene,measured),
                categories=['overlap','overflow','alignment'],
                coverage='Declared relations and conservative bounds only; not complete visual detection',
                visual_passed=False,requires_visual_review=True)
