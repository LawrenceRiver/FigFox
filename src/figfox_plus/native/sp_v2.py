"""Opt-in SP adapter. World coordinates are SVG root viewBox coordinates.

Legacy SP entry points deliberately do not import this module. No scene-specific
parameters or inferred correspondence to original images are stored here.
"""
from copy import deepcopy
import math
import re
import xml.etree.ElementTree as ET
from .document import SVG, validate, measure
from ..tp.transforms import apply, compose, inverse
from ..sp.compiler import compile_scene
from ..assets import crop_asset
from ..vectorize import vectorize_asset


def box(value):
    out = {k: value[k] for k in ('left', 'top', 'right', 'bottom')}
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in out.values()):
        raise ValueError('TP requires finite numbers')
    if out['right'] <= out['left'] or out['bottom'] <= out['top']:
        raise ValueError('TP must have positive width and height')
    return out


def fit_matrix(source_tp, target_tp, mode='contain'):
    """Map source paint TP into world target; contain centers, stretch fills."""
    s, t = box(source_tp), box(target_tp)
    sw, sh = s['right']-s['left'], s['bottom']-s['top']
    tw, th = t['right']-t['left'], t['bottom']-t['top']
    sx, sy = tw/sw, th/sh
    if mode == 'contain': sx = sy = min(sx, sy)
    elif mode != 'stretch': raise ValueError('fit mode must be contain or stretch')
    return [sx, 0, 0, sy, t['left']+(tw-sw*sx)/2-s['left']*sx,
            t['top']+(th-sh*sy)/2-s['top']*sy]


def canonical_targets(root, ids):
    """Drop duplicates and descendants of selected ancestors, in document order."""
    by = {n.get('id'): n for n in root.iter() if n.get('id')}
    if not ids or any(i not in by for i in ids): raise ValueError('unknown/empty replacement targets')
    chosen = {by[i] for i in ids}
    if root in chosen: raise ValueError('cannot replace SVG root')
    parent = {c:p for p in root.iter() for c in p}
    result = []
    for node in root.iter():
        if node not in chosen: continue
        p = parent[node]
        while p not in chosen and p in parent: p = parent[p]
        if p not in chosen: result.append(node.get('id'))
    return result


def construct(kind, data, owner='replacement', assets=()):
    """Use the existing executable registry, including real MathJax and markers."""
    scene = {'version':'plus-0.1', 'canvas':{'width':1, 'height':1},
             'objects':[{'id':owner, 'name':owner, 'kind':kind, 'data':data}],
             'relations':[], 'assets':list(assets)}
    svg, _ = compile_scene(scene)
    group = ET.Element('{'+SVG+'}g', {'id':owner, 'data-plus-kind':kind})
    group.extend(list(ET.fromstring(svg)))
    return group


def measure_construction(element, viewport, scale=4):
    """Measure a constructor in an explicit unclipped source viewport.

    The caller supplies viewport (a TP box) large enough for all paint/effects.
    Contact with viewport edges is rejected rather than silently fitting a crop.
    """
    from .tight_tp import measure_tight
    b = box(viewport); w, h = b['right']-b['left'], b['bottom']-b['top']
    root = ET.Element('{'+SVG+'}svg', {'width':str(w), 'height':str(h),
        'viewBox':f"{b['left']} {b['top']} {w} {h}"})
    node = deepcopy(element); node.set('id', '__sp_measure__'); root.append(node)
    result = measure_tight(root, ['__sp_measure__'], scale=scale)['objects']['__sp_measure__']
    if result['status'] != 'measured': raise ValueError('construction TP is '+result['status'])
    t = box(result['tight_bbox'])
    if t['left'] <= b['left'] or t['top'] <= b['top'] or t['right'] >= b['right'] or t['bottom'] >= b['bottom']:
        raise ValueError('construction touches measurement viewport; enlarge it explicitly')
    return result


def measure_construction_adaptive(element, viewport, scale=4):
    """Expand only the source measuring window; never alter construction or target.

    Seed from complete DOM geometry, including disconnected components outside the
    suggested window. Tight raster measurement remains the final authority.
    """
    supplied=box(viewport);b=dict(supplied)
    probe=ET.Element('{'+SVG+'}svg',{'width':'100','height':'100','viewBox':'0 0 100 100'})
    node=deepcopy(element);node.set('id','__sp_adaptive_probe__');probe.append(node)
    objects=measure(probe)['objects']
    boxes=[o['paint_bbox'] for o in objects.values() if o.get('paint_bbox')]
    for candidate in boxes:
        for key in ('left','top'):b[key]=min(b[key],candidate[key])
        for key in ('right','bottom'):b[key]=max(b[key],candidate[key])
    padding=max(8,(b['right']-b['left'])*.1,(b['bottom']-b['top'])*.1)
    b={k:v+(-padding if k in ('left','top') else padding) for k,v in b.items()}
    for attempt in range(4):
        # measure_tight caps raster memory by adapting its sampling grid. Keep
        # the complete construction window, including distant source geometry.
        try:result=measure_construction(element,b,scale)
        except ValueError as exc:
            if 'touches measurement viewport' not in str(exc):raise
            if attempt==3:raise
            pad=max(b['right']-b['left'],b['bottom']-b['top'])/2
            b={k:v+(-pad if k in ('left','top') else pad) for k,v in b.items()}
        else:
            result.update(supplied_viewport=supplied,measurement_viewport=b,
                          viewport_adjusted=b!=supplied,measurement_attempts=attempt+1)
            return result


def _unique_ids(element, reserved, owner):
    mapping = {}; serial = 0
    for n in element.iter():
        old = n.get('id')
        if not old: continue
        if old in mapping: raise ValueError('duplicate constructor ID')
        candidate = f'{owner}.replacement.{serial}'
        while candidate in reserved: serial += 1; candidate = f'{owner}.replacement.{serial}'
        serial += 1; reserved.add(candidate); mapping[old] = candidate
    for n in element.iter():
        for k,v in list(n.attrib.items()):
            if k == 'id': n.set(k, mapping[v])
            elif k.rsplit('}',1)[-1] == 'href' and v.startswith('#'):
                n.set(k, '#'+mapping.get(v[1:], v[1:]))
            else:
                n.set(k, re.sub(r'url\(\s*[\"\']?#([^\s)\"\']+)[\"\']?\s*\)',
                    lambda m:'url(#'+mapping.get(m[1],m[1])+')', v))


def _css_unescape(value):
    """Decode CSS escapes before conservatively checking local references."""
    def decode(match):
        if match[1]:
            codepoint = int(match[1], 16)
            return chr(codepoint) if 0 < codepoint <= 0x10ffff else '\ufffd'
        return match[2]
    return re.sub(r'\\([0-9a-fA-F]{1,6})(?:\r\n|[\t\n\r\f ])?|\\([^\n\r\f])', decode, value)


def replace(root, ids, element, source_tp, target_tp, mode='contain', scale=4):
    """Transactionally replace selected subtrees and fit source paint to world TP.

    Preserve the insertion parent's transforms and context. Target's own transform
    is consumed by its world TP; copying it again would double-transform content.
    Different-parent targets consolidate at the first selected node's parent.
    """
    from .tight_tp import measure_tight
    trial = deepcopy(root); selected = canonical_targets(trial, ids)
    by = {n.get('id'):n for n in trial.iter() if n.get('id')}
    parents = {c:p for p in trial.iter() for c in p}
    anchor = by[selected[0]]; parent = parents[anchor]; position = list(parent).index(anchor)
    # Protect surviving consumers even when the insertion anchor reuses its ID.
    # Checking only dangling IDs misses <use href="#anchor"> silently acquiring
    # the new geometry. Rejection is transactional; no old-resource snapshot is
    # invented and no unrelated consumer is modified.
    removed_nodes = {n for oid in selected for n in by[oid].iter()}
    replaced_ids = {n.get('id') for n in removed_nodes if n.get('id')}
    for node in trial.iter():
        if node in removed_nodes: continue
        refs = []
        for key, value in node.attrib.items():
            refs.extend(re.findall(r'url\(\s*[\"\']?#([^\s)\"\']+)', _css_unescape(value), re.I))
            if key.rsplit('}', 1)[-1] == 'href' and value.startswith('#'):
                refs.append(value[1:])
        if replaced_ids.intersection(refs):
            raise ValueError('replacement would change a surviving reference consumer')
        if node.tag.rsplit('}', 1)[-1] == 'style':
            css = _css_unescape(''.join(node.itertext()))
            # Includes selector references as well as url() dependencies. A raw
            # hash occurrence is deliberately conservative, not a CSS parser.
            if any('#'+oid in css for oid in replaced_ids):
                raise ValueError('replacement would change a surviving stylesheet reference')
    geometry = measure(trial)['objects']
    if any(oid not in geometry for oid in selected): raise ValueError('target is not a rendered SVG object')
    local = compose(inverse(geometry[selected[0]]['parent_world']), fit_matrix(source_tp, target_tp, mode))
    replacement = ET.Element('{'+SVG+'}g', {'id':selected[0],
        'transform':'matrix('+' '.join(format(v,'.15g') for v in local)+')'})
    child = deepcopy(element)
    _unique_ids(child, set(by), selected[0]); replacement.append(child)
    for oid in selected: parents[by[oid]].remove(by[oid])
    parent.insert(position, replacement); validate(trial)
    # Dangling references would make apparently successful replacements corrupt
    # unrelated use/marker/clip consumers. Fail before touching the original.
    remaining = {n.get('id') for n in trial.iter() if n.get('id')}
    removed = set(by)-remaining
    for n in trial.iter():
        for k,v in n.attrib.items():
            refs = re.findall(r'url\(\s*[\"\']?#([^\s)\"\']+)', v)
            if k.rsplit('}',1)[-1] == 'href' and v.startswith('#'): refs.append(v[1:])
            if removed.intersection(refs): raise ValueError('replacement would leave a dangling reference')
    observed = measure_tight(trial, [selected[0]], scale=scale)['objects'][selected[0]]
    if observed['status'] != 'measured': raise ValueError('replacement TP is '+observed['status'])
    root.attrib.clear(); root.attrib.update(trial.attrib); root[:] = list(trial)
    return {'target_ids':selected, 'replacement_id':selected[0], 'source_tp':box(source_tp),
            'requested_target_tp':box(target_tp), 'local_matrix':local, 'fit':mode,
            'observed':observed, 'context_note':'Parent clipping, opacity and filters remain active; inspect observed TP.'}


def original_crop(original, target_tp, world_to_original, out_dir, backend=None):
    """Crop explicit source correspondence; never infer it from current position.

    Axis-aligned positive scaling/translation is required because a rotated AABB
    crop would introduce unmatched corner pixels. Report rounding and inverse map.
    """
    t = box(target_tp); m = list(world_to_original)
    if len(m) != 6 or any(isinstance(v, bool) or not isinstance(v, (int,float)) or not math.isfinite(v) for v in m):
        raise ValueError("crop mapping requires six finite numbers")
    inverse(m)
    if m[1] != 0 or m[2] != 0 or m[0] <= 0 or m[3] <= 0:
        raise ValueError('crop mapping requires positive axis-aligned scale and translation')
    l, top = apply(m, [t['left'],t['top']]); r,b = apply(m,[t['right'],t['bottom']])
    asset = crop_asset(original, [l,top,r-l,b-top], out_dir)
    x,y,w,h = asset['source_crop']
    asset['coordinate_mapping'] = {'world_to_original':m, 'target_tp':t,
        'crop_pixels_to_world':compose(inverse(m),[1,0,0,1,x,y]),
        'rounding':'floor left/top, ceil right/bottom, clipped to original extent'}
    if backend is not None: asset = vectorize_asset(asset, backend, out_dir)
    from pathlib import Path
    from ..state import write_json
    write_json(Path(asset['path']).with_suffix('.mapping.json'), asset['coordinate_mapping'])
    return asset
