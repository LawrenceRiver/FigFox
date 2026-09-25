"""Exhaustive current-SVG mechanical candidates, never a defect verdict.

Accepts tight TP (status/tight_bbox) and native TP (geometry_bbox/
bounds_complete). Coordinates always belong to the supplied current SVG.
"""
import json
import math
import re
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path


_DRAWABLE = {'path', 'rect', 'circle', 'ellipse', 'line', 'polyline',
             'polygon', 'text', 'tspan', 'image', 'use', 'foreignObject'}
_DEFINITIONS = {'defs', 'symbol', 'marker', 'clipPath', 'mask', 'pattern'}
_NUM = r'[-+]?(?:\d*\.\d+|\d+\.?\d*)(?:[eE][-+]?\d+)?'


def build_diagnostics(svg_path, tp_path):
    """Read only these two explicit inputs; return a JSON-serializable report."""
    report = {'domain': 'current_svg_only', 'diagnosis_confirmed': False,
              'visual_passed': False, 'objects': [], 'relation_candidates': [],
              'normal_containment': [], 'structure_candidates': [], 'unmeasurable': [],
              'instruction': 'Candidates are not real errors. Original-image VLM must confirm or refute semantics and actual contours. Never map current TP coordinates onto the original image. Inspect unlisted regions too.'}
    root = ET.parse(Path(svg_path)).getroot()
    tp = json.loads(Path(tp_path).read_text())
    if tp.get('coordinate_space') not in (None, 'current_svg_world'):
        raise ValueError('Only current_svg_world TP is accepted')
    nodes = list(root.iter())
    tag = lambda n: n.tag.rsplit('}', 1)[-1]
    parent = {c: p for p in nodes for c in p}
    keys = {n: n.get('id') or '@node:%d' % i for i, n in enumerate(nodes)}
    counts = Counter(n.get('id') for n in nodes if n.get('id'))
    ids = {n.get('id'): n for n in nodes if n.get('id')}
    def ancestors(n):
        result = []
        while n in parent:
            n = parent[n]
            result.append(n)
        return result
    def inherited(n, prop, default=None):
        for q in [n] + ancestors(n):
            style = dict(re.findall(r'([\w-]+)\s*:\s*([^;]+)', q.get('style', '')))
            if prop in style or prop in q.attrib:
                return style.get(prop, q.get(prop))
        return default
    def structure(kind, n, **extra):
        report['structure_candidates'].append(dict(kind=kind, object_id=keys[n], **extra))
    for oid, count in counts.items():
        if count > 1:
            structure('duplicate_id', ids[oid], occurrences=count)
    for n in nodes:
        refs = []
        for attr, value in n.attrib.items():
            refs.extend(re.findall(r'url\(\s*[\'"]?#([^\s)\'"]+)', value))
            if attr.rsplit('}', 1)[-1] == 'href' and value.startswith('#'):
                refs.append(value[1:])
        if tag(n) == 'style':
            refs.extend(re.findall(r'url\(\s*[\'"]?#([^\s)\'"]+)', n.text or ''))
        for ref in sorted(set(refs)):
            if ref not in ids or counts[ref] > 1:
                structure('invalid_reference' if ref not in ids else 'ambiguous_reference', n, target_id=ref)
        if tag(n) == 'path' and inherited(n, 'fill', 'black').strip() != 'none':
            for part in re.split('[Mm]', n.get('d', ''))[1:]:
                if not re.search('[Zz]', part):
                    # SVG fills implicitly close open subpaths; valid but worth visual review.
                    numbers = re.findall(_NUM, part)
                    if len(numbers) >= 6 or len(re.findall('[LlHhVvCcSsQqTtAa]', part)) >= 2:
                        structure('open_filled_contour', n, basis='SVG implicit closure; CSS and intended contour require visual check')
                        break
    raw = tp.get('objects', {})
    if not isinstance(raw, dict):
        raise ValueError('TP objects must be an ID-keyed mapping')
    boxes = {}
    formats = set()
    for n in nodes:
        if tag(n) not in _DRAWABLE | {'g', 'svg'}:
            continue
        oid = keys[n]
        definition = any(tag(q) in _DEFINITIONS for q in [n] + ancestors(n))
        item = raw.get(n.get('id'), {})
        b = item.get('tight_bbox') if 'tight_bbox' in item else item.get('geometry_bbox')
        fmt = 'tight' if 'tight_bbox' in item else 'geometry'
        if item:
            formats.add(fmt)
        reason = None
        if definition: reason = 'definition_only; inspect rendered use instances'
        elif not n.get('id'): reason = 'missing_svg_id'
        elif counts[n.get('id')] > 1: reason = 'ambiguous_duplicate_id'
        elif not item: reason = 'missing_tp_measurement'
        elif fmt == 'tight' and item.get('status') != 'measured': reason = item.get('reason', item.get('status', 'unmeasured'))
        elif not isinstance(b, dict) or any(not isinstance(b.get(k), (int, float)) or isinstance(b.get(k), bool) or not math.isfinite(b[k]) for k in ('left', 'top', 'right', 'bottom')): reason = 'invalid_or_missing_bbox'
        elif b['right'] < b['left'] or b['bottom'] < b['top']: reason = 'inverted_bbox'
        entry = {'object_id': oid, 'tag': tag(n), 'is_leaf': not any(tag(c) in _DRAWABLE | {'g'} for c in n),
                 'measurement_format': fmt if item else None, 'bounds_complete': item.get('bounds_complete', False),
                 'status': 'unmeasurable' if reason else 'measured'}
        if reason:
            report['unmeasurable'].append({'object_id': oid, 'reason': reason})
        else:
            boxes[oid] = (n, b)
            entry['bbox'] = b
        report['objects'].append(entry)
    for oid in sorted(set(raw) - set(ids)):
        report['unmeasurable'].append({'object_id': oid, 'reason': 'tp_id_missing_from_svg'})
    eps = 1e-6
    def contains(a, b):
        return a['left'] <= b['left'] + eps and a['top'] <= b['top'] + eps and a['right'] >= b['right'] - eps and a['bottom'] >= b['bottom'] - eps
    def emit(kind, a, b=None, **extra):
        report['relation_candidates'].append(dict(kind=kind, object_ids=[a] + ([b] if b else []), basis='current_axis_aligned_bounds_only', requires_original_vlm_refutation=True, **extra))
    pairs = skipped = 0
    items = list(boxes.items())
    for i, (aid, (an, a)) in enumerate(items):
        for bid, (bn, b) in items[i + 1:]:
            pairs += 1
            if an in ancestors(bn) or bn in ancestors(an):
                skipped += 1
                continue
            dx = min(a['right'], b['right']) - max(a['left'], b['left'])
            dy = min(a['bottom'], b['bottom']) - max(a['top'], b['top'])
            if dx < -eps or dy < -eps: continue
            if contains(a, b) or contains(b, a):
                outer, inner, x, y = (aid, bid, a, b) if contains(a, b) else (bid, aid, b, a)
                margins = [y['left']-x['left'], y['top']-x['top'], x['right']-y['right'], x['bottom']-y['bottom']]
                report['normal_containment'].append({'container_id': outer, 'content_id': inner, 'semantic_relation_confirmed': False})
                if min(margins) <= eps:
                    emit('containment_boundary_touch', inner, outer, margins_ltrb=margins)
            else:
                possible_containers = [oid for oid, node in ((aid, an), (bid, bn)) if tag(node) in {'rect', 'circle', 'ellipse', 'polygon'}]
                emit('edge_touch' if min(dx, dy) <= eps else 'edge_intersection', aid, bid, intersection_size=[max(0, dx), max(0, dy)], possible_container_ids=possible_containers, container_semantics_confirmed=False)
    canvas = tp.get('canvas')
    if not canvas:
        nums = re.findall(_NUM, root.get('viewBox', ''))
        if len(nums) == 4:
            canvas = dict(zip(('x', 'y', 'width', 'height'), map(float, nums)))
    if canvas and all(isinstance(canvas.get(k), (int, float)) and math.isfinite(canvas[k]) for k in ('x', 'y', 'width', 'height')) and canvas['width'] > 0 and canvas['height'] > 0:
        boundary = dict(left=canvas['x'], top=canvas['y'], right=canvas['x']+canvas['width'], bottom=canvas['y']+canvas['height'])
        for oid, (n, b) in items:
            if tag(n) == 'svg': continue
            if not contains(boundary, b): emit('canvas_overflow', oid, canvas_bbox=boundary)
    else:
        report['unmeasurable'].append({'object_id': '@canvas', 'reason': 'missing_or_invalid_canvas'})
    report['coverage'] = {'svg_node_count': len(nodes), 'object_count': len(report['objects']), 'measured_count': len(boxes), 'pair_count': pairs, 'ancestor_pairs_excluded': skipped, 'candidate_limit': None, 'tp_formats': sorted(formats), 'scope': 'all drawable leaves and measured SVG containers; no name-based semantics', 'limitations': ['AABB intersection is not painted contour collision', 'TP provenance/freshness is not independently verified', 'Tight raster TP is viewport-clipped and cannot prove absence of outside-viewport paint', 'CSS cascade, filter effects, text shaping, occlusion and intended semantic groups require rendered/reference review', 'Unmeasured objects are not certified collision-free', 'Strict containment is recorded, not treated as an error; container semantics require VLM', 'External references and general SVG grammar are not fully validated', 'Geometric TP bounds may omit paint effects; bounds_complete is preserved per object', 'Only SVG nodes and measured groups are enumerated; unnamed conceptual semantic groups require VLM compilation']}
    return report
