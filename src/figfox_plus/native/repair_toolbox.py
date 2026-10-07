"""Bounded, transactional local TP/SP/BP operations for a model-authored repair plan.

Coordinates supplied to this module are SVG root viewBox units, except
``sp_photo.source_crop``, which is always in original-image pixels.
Native ``bp_patch`` x/y/size attributes are element-local SVG values; use TP
for world-space transformations of nested or bound objects.
"""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
import math
import re
import time
import xml.etree.ElementTree as ET

from PIL import Image
from . import tp_v2, sp_v2
from .diagnosis import CATEGORIES
from .document import SVG, HREF, measure, serialize, validate, tag
from .tight_tp import measure_tight
from ..assets import crop_asset, remove_background_asset
from ..vectorize import vectorize_asset
from ..state import write_json
from ..tp.transforms import inverse

_TYPES = set(CATEGORIES)
_METHOD_TYPES = {'tp_transform':'TP', 'tp_align':'TP', 'tp_fit':'TP',
                 'sp_replace':'SP', 'sp_photo':'SP',
                 'bp_patch':'BP', 'bp_add':'BP', 'bp_remove':'BP'}
_PATCH_ATTRS = {'fill','stroke','stroke-width','stroke-dasharray','stroke-dashoffset',
                'stroke-linecap','stroke-linejoin','d','points','marker-start',
                'marker-mid','marker-end','font-family','font-size','font-weight',
                'font-style','font-variant','text-anchor','text-decoration',
                'letter-spacing','word-spacing'}
_STYLE_ATTRS = _PATCH_ATTRS - {'points'}
_GEOMETRY_BY_TAG = {
    'rect':{'x','y','width','height','rx','ry'},
    'image':{'x','y','width','height'},'use':{'x','y','width','height'},
    'text':{'x','y','dx','dy'},'tspan':{'x','y','dx','dy'},
    'line':{'x1','y1','x2','y2'},'circle':{'cx','cy','r'},
    'ellipse':{'cx','cy','rx','ry'},
}
_GEOMETRY_ATTRS = set().union(*_GEOMETRY_BY_TAG.values())
_HREF_PATCH_KEYS = {'href', 'xlink:href', HREF}
_URL_REF = re.compile(r'url\(\s*["\']?#([^\s)"\']+)', re.I)


def _nodes(root):
    return {n.get('id'): n for n in root.iter() if n.get('id')}


def _is_canvas_background(root, node):
    if node.get('id','').lower() in {'background','canvas','canvas-background'}:
        return True
    if tag(node) != 'rect':
        return False
    viewbox = root.get('viewBox')
    if not viewbox:
        return False
    try:
        x,y,w,h = [float(v) for v in viewbox.replace(',',' ').split()]
        return (float(node.get('x',0)) <= x and float(node.get('y',0)) <= y
                and float(node.get('width',-1)) >= w and float(node.get('height',-1)) >= h)
    except (ValueError, TypeError):
        return False


def _refs(node):
    out = set()
    for key, value in node.attrib.items():
        value = sp_v2._css_unescape(value)
        out.update(_URL_REF.findall(value))
        if key.rsplit('}', 1)[-1] == 'href' and value.startswith('#'):
            out.add(value[1:])
    if tag(node) == 'style':
        css = sp_v2._css_unescape(''.join(node.itertext()))
        out.update(_URL_REF.findall(css))
        out.update(re.findall(r'#([\w.:-]+)', css))
    return out


def _protect_consumers(root, changing_ids, selected_nodes):
    for node in root.iter():
        if node in selected_nodes:
            continue
        if _refs(node) & changing_ids:
            raise ValueError('edit would change an external reference consumer')


def _source_ancestors(root, nodes):
    parents = {c:p for p in root.iter() for c in p}
    sources = set()
    for node in nodes:
        while node is not None and node not in sources:
            sources.add(node)
            node = parents.get(node)
    return {node.get('id') for node in sources if node.get('id')}, sources


def _scope(root, issue):
    if not isinstance(issue, dict) or not isinstance(issue.get('id'), str) or not issue['id']:
        raise ValueError('issue requires id')
    types = issue.get('types')
    if not isinstance(types, list) or not types or any(t not in _TYPES for t in types):
        raise ValueError('unknown or missing issue type')
    if not isinstance(issue.get('description'), str) or not issue['description'].strip():
        raise ValueError('issue requires description')
    if not issue.get('original_evidence'):
        raise ValueError('issue requires original_evidence')
    ids = issue.get('target_ids')
    if not isinstance(ids, list) or not ids or any(not isinstance(i, str) for i in ids):
        raise ValueError('issue requires target anchors')
    by = _nodes(root)
    if any(i not in by for i in ids) or root in (by[i] for i in ids):
        raise ValueError('issue has unknown/root target anchor')
    neighbors = issue.get('neighbor_ids', [])
    if not isinstance(neighbors, list) or any(i not in by for i in neighbors):
        raise ValueError('issue has unknown neighbor')
    operations = issue.get('operations')
    if not isinstance(operations, list) or not operations:
        raise ValueError('issue requires operations')
    permitted = set(ids) | set(neighbors)
    for i in ids + neighbors:
        permitted.update(n.get('id') for n in by[i].iter() if n.get('id'))
    return permitted


def _target_ids(op, permitted, root):
    ids = op.get('target_ids')
    if not isinstance(ids, list) or not ids or any(i not in permitted for i in ids):
        raise ValueError('operation targets exceed issue scope')
    by = _nodes(root)
    if any(i not in by or by[i] is root for i in ids):
        raise ValueError('operation target missing or root')
    if any(_is_canvas_background(root, node) for i in ids for node in by[i].iter()):
        raise ValueError('canvas background cannot be edited')
    return ids


def _box(value):
    return sp_v2.box(value)


def _required_box(args, name, method):
    expected = '{"left":number,"top":number,"right":number,"bottom":number} with positive width and height'
    if name not in args or args[name] is None:
        raise ValueError(f'{method} requires args.{name}: {expected}')
    if not isinstance(args[name], dict):
        raise ValueError(f'{method} args.{name} must be {expected}')
    try:
        return _box(args[name])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f'{method} args.{name} must be {expected}: {exc}') from exc


def _safe_style(value):
    """A restricted presentation-declaration subset, appended as overrides."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError('bp_patch args.attributes.style must be CSS presentation declarations, e.g. "fill:#234; font-family:Arial"')
    if (any(c in value for c in ('\\','{','}','@','<','>','\x00')) or '/*' in value or '*/' in value
            or re.search(r'\b(?:url|var|expression)\s*\(', value, re.I)):
        raise ValueError('bp_patch style forbids escapes, rules, active/external references, and CSS functions other than color values')
    declarations = []
    for chunk in value.split(';'):
        if not chunk.strip():
            continue
        if ':' not in chunk:
            raise ValueError('bp_patch style must use property:value declarations separated by semicolons')
        name, raw = chunk.split(':', 1)
        name = name.strip().lower()
        if name not in _STYLE_ATTRS:
            raise ValueError('bp_patch style property outside presentation whitelist: '+name)
        raw = raw.strip()
        if not raw or not re.fullmatch(r'[\w\s#.%(),+\-"\']+(?:\s*!important)?', raw, re.I):
            raise ValueError('bp_patch style has invalid value for '+name)
        clean = re.sub(r'\s*!important\s*$', '', raw, flags=re.I).strip()
        if not clean:
            raise ValueError('bp_patch style has empty value for '+name)
        declarations.append(name+':'+clean+' !important')
    if not declarations:
        raise ValueError('bp_patch style requires at least one presentation declaration')
    return '; '.join(declarations)


def _use_href_source(root, node, value, by):
    if tag(node) != 'use':
        raise ValueError('bp_patch href may only target a <use> node')
    if not isinstance(value, str) or not value.startswith('#') or value.count('#') != 1:
        raise ValueError('bp_patch href must be a local #existing-id reference')
    source = by.get(value[1:])
    if source is None:
        raise ValueError('bp_patch href source ID does not exist in this SVG')
    if source is root or source is node or source in set(node.iter()) or node in set(source.iter()):
        raise ValueError('bp_patch href cannot reference root, self, or a containing/contained node')
    if tag(source) not in {'g','symbol','rect','circle','ellipse','path','polygon','polyline','line','text'}:
        raise ValueError('bp_patch href source must be an existing g, symbol, or simple drawable')
    if any(tag(n) == 'use' for n in source.iter()):
        raise ValueError('bp_patch href source containing <use> is rejected to prevent reference cycles')
    return source


def _patch(root, ids, args, permitted):
    attrs = args.get('attributes', {})
    if not isinstance(attrs, dict) or any(k not in _PATCH_ATTRS | _GEOMETRY_ATTRS | {'style'} | _HREF_PATCH_KEYS for k in attrs):
        raise ValueError('BP attributes outside small whitelist')
    if not attrs and 'text' not in args:
        raise ValueError('bp_patch requires args.attributes: nonempty allowed-attribute object, or args.text: string for a text node')
    if any(not isinstance(v, (str, int, float)) or isinstance(v, bool) for v in attrs.values()):
        raise ValueError('BP attribute values must be scalar')
    safe_style = _safe_style(attrs['style']) if 'style' in attrs else None
    by = _nodes(root)
    for key in attrs.keys() & _GEOMETRY_ATTRS:
        try:value=float(attrs[key])
        except (TypeError,ValueError):raise ValueError('BP geometry requires finite scalar numbers')
        if not math.isfinite(value):raise ValueError('BP geometry requires finite scalar numbers')
        if key in {'width','height','rx','ry','r'} and value<0:
            raise ValueError('BP geometry size must be nonnegative')
        if any(key not in _GEOMETRY_BY_TAG.get(tag(by[oid]),set()) for oid in ids):
            raise ValueError('BP geometry attribute does not apply to selected element: '+key)
    href_keys = [k for k in attrs if k in _HREF_PATCH_KEYS]
    if len(href_keys) > 1:
        raise ValueError('bp_patch accepts one href/xlink:href value per operation')
    if href_keys:
        for oid in ids:
            _use_href_source(root, by[oid], attrs[href_keys[0]], by)
    chosen = {by[i] for i in ids}
    changed = {n.get('id') for node in chosen for n in node.iter() if n.get('id')}
    ancestors, sources = _source_ancestors(root, chosen)
    in_scope = {by[i] for i in permitted if i in by}
    _protect_consumers(root, changed | ancestors, sources | in_scope)
    for oid in ids:
        node = by[oid]
        for key, value in attrs.items():
            if key in _HREF_PATCH_KEYS:
                node.attrib.pop('href', None)
                node.attrib.pop(HREF, None)
                node.attrib.pop('xlink:href', None)
                node.set('href', value)
            elif key == 'style':
                existing = node.get('style','').strip()
                node.set('style', (existing.rstrip(';')+'; ' if existing else '')+safe_style)
            else:
                node.set(key, str(value))
        if 'text' in args:
            if tag(node) != 'text' or not isinstance(args['text'], str):
                raise ValueError('BP text replacement requires text node and string')
            for child in list(node):
                node.remove(child)
            node.text = args['text']
    validate(root)
    all_ids = set(_nodes(root))
    if any(_refs(by[oid]) - all_ids for oid in ids):
        raise ValueError('BP patch introduced unresolved local reference')
    return {'target_ids': ids, 'attributes': attrs, 'text': args.get('text')}


def _remove(root, ids, permitted):
    selected = sp_v2.canonical_targets(root, ids)
    by = _nodes(root)
    removed_nodes = {n for oid in selected for n in by[oid].iter()}
    removed_ids = {n.get('id') for n in removed_nodes if n.get('id')}
    if removed_ids - permitted:
        raise ValueError('BP removal contains unrelated objects')
    ancestors, sources = _source_ancestors(root, {by[oid] for oid in selected})
    in_scope = {by[i] for i in permitted if i in by}
    # A deleted ID cannot be retained by any surviving consumer, even one
    # listed as a neighbor. Scope only permits changes to ancestor instances.
    _protect_consumers(root, removed_ids, removed_nodes)
    _protect_consumers(root, ancestors - removed_ids, removed_nodes | sources | in_scope)
    parents = {c:p for p in root.iter() for c in p}
    for oid in selected:
        parents[by[oid]].remove(by[oid])
    validate(root)
    return {'removed_ids': selected}


def _add(root, args, permitted, anchors):
    parent_id = args.get('parent_id')
    by = _nodes(root)
    if parent_id == '@parent':
        parents = {c:p for p in root.iter() for c in p}
        chosen = [by[i] for i in anchors]
        containers = {parents[n] for n in chosen}
        if len(containers) != 1:
            raise ValueError('BP @parent anchors require one common container')
        parent = next(iter(containers))
    else:
        if parent_id not in permitted or parent_id not in by or by[parent_id] is root:
            raise ValueError('BP parent exceeds issue scope')
        parent = by[parent_id]
    if tag(parent) not in {'g','svg'}:
        raise ValueError('BP parent must be a g or svg container')
    ancestors, sources = _source_ancestors(root, {parent})
    in_scope = {by[i] for i in permitted if i in by}
    _protect_consumers(root, ancestors, sources | in_scope)
    fragment = args.get('svg')
    if not isinstance(fragment, str) or not fragment.strip():
        raise ValueError('bp_add requires args.svg: one to five inert local SVG fragments with explicit IDs')
    wrapped = ET.fromstring('<g xmlns="'+SVG+'">'+fragment+'</g>')
    children = list(wrapped)
    if not 1 <= len(children) <= 5:
        raise ValueError('BP addition requires one to five fragments')
    new_nodes = [n for child in children for n in child.iter()]
    if any(tag(n) not in {'g','line','path','rect','circle','ellipse','polyline','polygon','text','tspan'} for n in new_nodes):
        raise ValueError('BP fragment must be inert local geometry')
    ids = [n.get('id') for n in new_nodes]
    if any(not i for i in ids) or len(ids) != len(set(ids)) or set(ids) & set(by):
        raise ValueError('BP addition requires unique explicit IDs')
    references = set().union(*(_refs(n) for n in new_nodes))
    if references - (set(ids) | set(by)):
        raise ValueError('BP fragment has unresolved local references')
    if parent is root:
        local = [1,0,0,1,0,0]
    else:
        geometry = measure(root)['objects']
        actual_parent_id = parent.get('id')
        if actual_parent_id not in geometry:
            raise ValueError('BP parent has no world frame')
        local = inverse(geometry[actual_parent_id]['world'])
    wrapper = ET.Element('{'+SVG+'}g', {'transform': 'matrix('+' '.join(format(x,'.15g') for x in local)+')',
                                      'data-plus-bp-world':'true'})
    wrapper.extend(children)
    parent.append(wrapper)
    validate(root)
    return {'parent_id':parent_id, 'resolved_parent_id':parent.get('id'),
            'added_ids': ids, 'world_to_parent_matrix':local,
            'read_only_existing_references': sorted(references-set(ids))}


def _photo(root, ids, args, original, folder, scale):
    crop = args.get('source_crop')
    if not isinstance(crop, (list, tuple)) or len(crop) != 4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in crop):
        raise ValueError('photo source_crop requires finite original pixel xywh')
    x,y,w,h = crop
    with Image.open(original) as image:
        width,height = image.size
    if w <= 0 or h <= 0 or x < 0 or y < 0 or x+w > width or y+h > height:
        raise ValueError('photo crop empty or outside original')
    if x == 0 and y == 0 and w == width and h == height:
        raise ValueError('photo crop cannot be whole original')
    representation = args.get('representation')
    if representation not in {'raster','vector'}:
        raise ValueError('photo representation must be raster or vector')
    target = _required_box(args, 'target_tp', 'sp_photo')
    padding = args.get('padding', 0)
    if isinstance(padding,bool) or not isinstance(padding,(int,float)) or not math.isfinite(padding) or padding < 0:
        raise ValueError('photo padding must be finite nonnegative')
    inner = _box({'left':target['left']+padding,'top':target['top']+padding,
                  'right':target['right']-padding,'bottom':target['bottom']-padding})
    asset = crop_asset(original, crop, Path(folder)/'assets')
    rounded = asset['source_crop']
    removal = args.get('remove_background', True)
    if not isinstance(removal, bool):raise ValueError('remove_background must be boolean')
    if removal:asset = remove_background_asset(asset, Path(folder)/'assets')
    if representation == 'vector':
        asset = vectorize_asset(asset, args.get('backend', 'vtracer'), Path(folder)/'assets')
    data = {'asset_id':asset['id'], 'x':0, 'y':0, 'width':rounded[2], 'height':rounded[3]}
    kind = 'picture' if representation == 'raster' else 'vector_asset'
    element = sp_v2.construct(kind, data, owner='photo_replacement', assets=[asset])
    # The constructor viewport is deliberately larger than its source pixels.
    margin = max(2, rounded[2]*.1, rounded[3]*.1)
    viewport = {'left':-margin,'top':-margin,'right':rounded[2]+margin,'bottom':rounded[3]+margin}
    measured = sp_v2.measure_construction(element, viewport, scale)
    result = sp_v2.replace(root, ids, element, measured['tight_bbox'], inner,
                           args.get('mode','contain'), scale)
    replacement = _nodes(root)[result['replacement_id']]
    replacement.set('data-plus-representation', representation)
    replacement.set('data-plus-kind', kind)
    replacement.set('data-plus-source-crop', json.dumps(rounded))
    validate(root)
    result['asset'] = {k:v for k,v in asset.items() if k != 'path'}
    result['asset_path'] = asset['path']
    result['source_mapping'] = {'requested_crop':list(crop),'actual_crop':rounded,
                                'original_pixel_mapping':'identity',
                                'crop_pixels_to_original':[1,0,0,1,rounded[0],rounded[1]],
                                'rounding':'floor left/top, ceil right/bottom'}
    result['representation'] = representation
    result['padding'] = padding
    result['padded_target_tp'] = inner
    result['constructor_data'] = data
    return result


def _run_operation(root, op, issue, permitted, original, folder, scale):
    if not isinstance(op, dict) or op.get('method') not in _METHOD_TYPES:
        raise ValueError('operation.method must be a supported TP/SP/BP method at the operation top level, alongside target_ids and args; do not place it in args.method. Example: {\"method\":\"bp_patch\",\"target_ids\":[\"selected-id\"],\"args\":{\"attributes\":{\"fill\":\"#000000\"}}}')
    method = op['method']
    args = op.get('args', {})
    if not isinstance(args, dict):
        raise ValueError('operation args must be object')
    ids = _target_ids(op, permitted, root)
    if method == 'tp_transform':
        if 'world_matrix' not in args or args['world_matrix'] is None:
            raise ValueError('tp_transform requires args.world_matrix: [a,b,c,d,e,f] in SVG root viewBox units')
        return tp_v2.transform(root, ids, args.get('world_matrix'), scale)
    if method == 'tp_align':
        refs = args.get('reference_ids')
        if not isinstance(refs, list) or not refs or any(i not in _nodes(root) for i in refs):
            raise ValueError('tp_align requires args.reference_ids: nonempty list of existing SVG IDs')
        return tp_v2.align(root, ids, refs, args.get('mode','center_x'), scale)
    if method == 'tp_fit':
        return tp_v2.fit(root, ids, _required_box(args, 'target_tp', method), args.get('mode','contain'), scale)
    if method == 'sp_replace':
        kind = args.get('kind')
        if kind not in {'geometry','frame','text','formula','arrow'}:
            raise ValueError('sp_replace requires args.kind: geometry, frame, text, formula, or arrow')
        if not isinstance(args.get('data'), dict):
            raise ValueError('sp_replace requires args.data: constructor parameter object for the selected kind')
        viewport = _required_box(args, 'measurement_viewport', method)
        target = _required_box(args, 'target_tp', method)
        element = sp_v2.construct(kind, args['data'])
        measured = sp_v2.measure_construction_adaptive(element, viewport, scale)
        result = sp_v2.replace(root, ids, element, measured['tight_bbox'], target,
                               args.get('mode','contain'), scale)
        _nodes(root)[result['replacement_id']].set('data-plus-kind', kind)
        result['constructor_kind'] = kind
        result['constructor_data'] = args['data']
        result['construction_measurement'] = measured
        return result
    if method == 'sp_photo':
        return _photo(root, ids, args, original, folder, scale)
    if method == 'bp_patch':
        return _patch(root, ids, args, permitted)
    if method == 'bp_add':
        if 'parent_id' not in args or args['parent_id'] is None:
            raise ValueError('bp_add requires args.parent_id: selected g/svg ID or "@parent" for selected anchors\' common container')
        if args.get('parent_id') != '@parent' and args.get('parent_id') not in ids:
            raise ValueError('BP parent must be an operation target')
        return _add(root, args, permitted, ids)
    return _remove(root, ids, permitted)


def _descendant_ids(root, ids):
    by = _nodes(root)
    out = set(ids)
    for oid in ids:
        if oid in by:
            out.update(n.get('id') for n in by[oid].iter() if n.get('id'))
    return out


def _nearby(cache, selected, explicit):
    boxes = [cache.get(i, {}).get('tight_bbox') for i in selected]
    boxes = [b for b in boxes if b]
    result = set(explicit) | set(selected)
    if not boxes:
        return result
    region = {k:(min if k in ('left','top') else max)(b[k] for b in boxes)
              for k in ('left','top','right','bottom')}
    pad = max(10, .2*max(region['right']-region['left'], region['bottom']-region['top']))
    for oid, item in cache.items():
        b = item.get('tight_bbox')
        if b and b['right'] >= region['left']-pad and b['left'] <= region['right']+pad and b['bottom'] >= region['top']-pad and b['top'] <= region['bottom']+pad:
            result.add(oid)
    return result


def _relationships(root, objects, selected):
    by = _nodes(root)
    ids = sorted(i for i, v in objects.items() if i in by and v.get('tight_bbox'))
    pairs = []
    for ix,a in enumerate(ids):
        for b in ids[ix+1:]:
            if a not in selected and b not in selected:
                continue
            if by[a] in set(by[b].iter()) or by[b] in set(by[a].iter()):
                continue
            x,y = objects[a]['tight_bbox'],objects[b]['tight_bbox']
            ox = min(x['right'],y['right'])-max(x['left'],y['left'])
            oy = min(x['bottom'],y['bottom'])-max(x['top'],y['top'])
            pairs.append({'ids':[a,b], 'overlap_area':max(0,ox)*max(0,oy),
                          'gap_x':max(0,-ox), 'gap_y':max(0,-oy),
                          'candidate_only':True})
    return pairs


def _checks(before_root, after_root, before, after, selected):
    ids = sorted(set(before) | set(after))
    objects = {}
    for oid in ids:
        old,new = before.get(oid,{}),after.get(oid,{})
        a,b = old.get('tight_bbox'),new.get('tight_bbox')
        objects[oid] = {'old_bbox':a, 'new_bbox':b,
                        'old_status':old.get('status','missing'), 'new_status':new.get('status','missing'),
                        'moved':bool(a and b and any(abs(a[k]-b[k]) > .01 for k in a)),
                        'vanished':bool(a and not b), 'new':bool(b and not a)}
    old_pairs = _relationships(before_root,before,selected)
    new_pairs = _relationships(after_root,after,selected)
    viewbox = after_root.get('viewBox')
    clipping = []
    if viewbox:
        v = [float(x) for x in viewbox.replace(',',' ').split()]
        if len(v) == 4:
            for oid,item in after.items():
                b = item.get('tight_bbox')
                if b and (b['left'] <= v[0] or b['top'] <= v[1] or b['right'] >= v[0]+v[2] or b['bottom'] >= v[1]+v[3]):
                    clipping.append({'id':oid,'kind':'output_boundary_contact','candidate_only':True})
    return {'objects':objects,'before_pairs':old_pairs,'after_pairs':new_pairs,
            'candidates':clipping+[{'ids':p['ids'],'kind':'overlap_candidate','candidate_only':True}
                                  for p in new_pairs if p['overlap_area'] > 0],
            'quality_verdict':None}


def _revision(root):
    return sha256(serialize(root).encode()).hexdigest()


def execute_batch(root, issues, original, folder, scale=4):
    """Apply each issue atomically and return a JSON-compatible local evidence report."""
    started = time.perf_counter()
    validate(root)
    if not isinstance(issues, list):
        raise ValueError('issues must be a list')
    folder = Path(folder)
    folder.mkdir(parents=True, exist_ok=True)
    baseline_revision = _revision(root)
    (folder/'before.svg').write_text(serialize(root), encoding='utf-8')
    write_json(folder/'operation_inputs.json', issues)
    # Layout boxes index the neighborhood. Isolated alpha stays on convergence and $measure.
    cache = measure_tight(root, scale=scale, layout=True)['objects'] if issues else {}
    reports = []
    for index, issue in enumerate(issues):
        began = time.perf_counter()
        old_root = deepcopy(root)
        trial = deepcopy(root)
        issue_dir = folder/f'issue-{index+1:03d}'
        issue_dir.mkdir(parents=True, exist_ok=True)
        (issue_dir/'before.svg').write_text(serialize(old_root), encoding='utf-8')
        write_json(issue_dir/'input.json', issue)
        item = {'id':issue.get('id') if isinstance(issue,dict) else None,
                'status':'error','applied_operations':[],'errors':[],
                'baseline_revision':_revision(old_root)}
        try:
            permitted = _scope(trial, issue)
            anchors = set(issue['target_ids']) | set(issue.get('neighbor_ids',[]))
            selected = _descendant_ids(old_root, anchors)
            nearby = _nearby(cache, selected, issue.get('neighbor_ids',[]))
            before = {i:cache[i] for i in nearby if i in cache}
            added_ids = set()
            for op in issue['operations']:
                result = _run_operation(trial, op, issue, permitted, original, folder, scale)
                added_ids.update(result.get('added_ids', []))
                item['applied_operations'].append({'input':op,'result':result})
            validate(trial)
            post_ids = _descendant_ids(trial, anchors) | added_ids
            # New positions can encounter old objects outside the former neighborhood.
            new_selected = sorted(i for i in post_ids if i in _nodes(trial))
            seed = measure_tight(trial, new_selected, scale=scale, layout=True)['objects'] if new_selected else {}
            merged = {**cache, **seed}
            nearby |= _nearby(merged, post_ids, issue.get('neighbor_ids',[]))
            after_ids = sorted(i for i in nearby | post_ids if i in _nodes(trial))
            after = {i:merged[i] for i in after_ids if i in merged}
            for oid in nearby:
                if oid in cache and oid not in before:
                    before[oid] = cache[oid]
            item['checks'] = _checks(old_root,trial,before,after,selected | post_ids)
            item['status'] = 'applied'
            root.attrib.clear(); root.attrib.update(trial.attrib); root[:] = list(trial)
            cache.update(after)
            for oid in set(before)-set(after):
                cache.pop(oid,None)
        except Exception as exc:
            item['errors'].append(f'{type(exc).__name__}: {exc}')
            item['applied_operations'] = []  # no operation from this issue committed
            item['checks'] = {'quality_verdict':None}
        item['resulting_revision'] = _revision(root)
        item['elapsed_seconds'] = time.perf_counter()-began
        (issue_dir/'after.svg').write_text(serialize(root), encoding='utf-8')
        write_json(issue_dir/'report.json',item)
        reports.append(item)
    (folder/'after.svg').write_text(serialize(root), encoding='utf-8')
    report = {'baseline_revision':baseline_revision,'resulting_revision':_revision(root),
              'issues':reports,'elapsed_seconds':time.perf_counter()-started,
              'measurement_policy':'layout boxes for the neighborhood; isolated alpha stays on convergence and $measure',
              'visual_acceptance':None}
    write_json(folder/'report.json',report)
    return report
