"""Read-only current-render observations, never defect or repair decisions.

The renderer is supplied by the controller. This module has no native runtime,
browser, provider, source-image or credential dependency.
"""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import time
import xml.etree.ElementTree as ET

import numpy as np
from PIL import Image


class ObservationUnsupported(ValueError):
    """Analysis could not establish its prerequisites; preserve its directory."""


DEFAULT_CONFIG = {
    # Dimensionless p90 relative-luminance contrast ratio, not RGB delta.
    'text_contrast_p90_max': 2.0,
    'close_text_gap_height_ratio': 0.2,
    'close_text_vertical_overlap_height_ratio': 0.5,
    'frequency_spellings': ['Hz', 'kHz', 'MHz', 'GHz', 'THz', 'mHz'],
    'orthogonal_min_horizontal_segments': 2,
    'orthogonal_min_vertical_segments': 2,
}
_NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
_TOKEN = re.compile(r'[MmLlHhVvZz]|' + _NUMBER)
_DEFINITIONS = {'defs', 'marker', 'symbol', 'clipPath', 'mask', 'pattern'}


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _dump(path, obj):
    path.write_text(json.dumps(obj, indent=2, sort_keys=True, allow_nan=False)+'\n', encoding='utf-8')


def _tag(node):
    return node.tag.rsplit('}', 1)[-1]


def _finite(values):
    return all(isinstance(v, (float, int)) and not isinstance(v, bool) and math.isfinite(v) for v in values)


def _rect(raw):
    if not isinstance(raw, dict):
        return None
    vals = [raw.get(k) for k in ('left', 'top', 'right', 'bottom')]
    if not _finite(vals) or vals[2] <= vals[0] or vals[3] <= vals[1]:
        return None
    return [vals[0], vals[1], vals[2]-vals[0], vals[3]-vals[1]]


def _intersect(a, b):
    return [max(a[0], b[0]), max(a[1], b[1]),
            max(0, min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0])),
            max(0, min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]))]


def _union(a, b):
    x, y = min(a[0], b[0]), min(a[1], b[1])
    return [x, y, max(a[0]+a[2], b[0]+b[2])-x, max(a[1]+a[3], b[1]+b[3])-y]


def _style(node):
    out = {}
    for part in node.get('style', '').split(';'):
        if ':' in part:
            k, v = part.split(':', 1)
            out[k.strip().lower()] = v.replace('!important', '').strip().lower()
    return out


def _property(node, name):
    return _style(node).get(name, node.get(name, '').strip().lower())


def _visible_rgb(array):
    # Hidden RGB under alpha=0 contributes zero to visible difference.
    rgb = array[..., :3].astype(np.float64)
    alpha = array[..., 3:4].astype(np.float64)/255
    return rgb*alpha+255*(1-alpha)


def _relative_luminance(visible_rgb):
    srgb = visible_rgb/255
    linear = np.where(srgb <= 0.04045, srgb/12.92, ((srgb+0.055)/1.055)**2.4)
    return linear @ np.array([0.2126, 0.7152, 0.0722])


def _overlap_groups(neighbors):
    """Connected components of the existing positive-box-overlap relation."""
    remaining = set(neighbors)
    while remaining:
        pending, members = [min(remaining)], set()
        while pending:
            ident = pending.pop()
            if ident in members:
                continue
            members.add(ident)
            pending.extend(neighbors[ident]-members)
        remaining.difference_update(members)
        if len(members) >= 2:
            yield sorted(members)


def _group_ink_observations(member_boxes, canvas, diff, contrast, unsupported_reasons):
    """Unattributed conditional pixels in a box union; never member contrast."""
    observations = {
        'member_boxes': member_boxes,
        'basis': 'unattributed current-render distribution conditional on hiding all eligible text',
        'measurement_status': 'unsupported', 'unsupported_reasons': unsupported_reasons,
        'changed_visible_pixels': None, 'contrast_p10': None, 'contrast_p50': None,
        'contrast_p90': None, 'fraction_contrast_at_or_below_2': None,
        'contrast_observation_setting': 2.0, 'ink_components': None,
        'metric': 'dimensionless relative-luminance contrast ratio (maxL+0.05)/(minL+0.05) after sRGB linearization of white-composited visibleRGB, on changed pixels in the union of member boxes only',
        'limitations': [
            'components_are_unassigned_to_svg_members',
            'high_aggregate_or_component_p90_cannot_exclude_faint_members',
            'tiny_antialias_components_retained_without_size_filter',
            'eight_connected_ink_can_join_or_split',
            'hidden_or_revealed_layers_blending_and_nontext_occlusion',
            'unsupported_geometry_style_or_paint_remains_unknown',
            'white_flattened_native_exports_do_not_recover_original_alpha_or_other_backgrounds',
            'no_intrinsic_member_contrast_necessity_defect_coverage_or_edit_authority',
        ],
    }
    if unsupported_reasons:
        return observations
    height, width = diff.shape
    scale_x, scale_y = width/canvas[2], height/canvas[3]
    union = np.zeros(diff.shape, dtype=bool)
    for member in member_boxes:
        rect = member['bbox']
        left = max(0, math.floor((rect[0]-canvas[0])*scale_x))
        top = max(0, math.floor((rect[1]-canvas[1])*scale_y))
        right = min(width, math.ceil((rect[0]+rect[2]-canvas[0])*scale_x))
        bottom = min(height, math.ceil((rect[1]+rect[3]-canvas[1])*scale_y))
        union[top:bottom, left:right] = True
    changed_mask = union & (diff > 1e-9)
    changed = contrast[changed_mask]
    observations.update(changed_visible_pixels=int(changed.size), ink_components=[],
                        measurement_status='unknown_no_conditional_difference')
    if not changed.size:
        observations['limitations'].append('nontext_occlusion_or_unchanged_conditional_render')
        return observations
    p10, p50, p90 = np.percentile(changed, [10, 50, 90])
    observations.update(measurement_status='measured', contrast_p10=float(p10),
                        contrast_p50=float(p50), contrast_p90=float(p90),
                        fraction_contrast_at_or_below_2=float(np.mean(changed <= 2.0)))
    # Row-major seeds and all eight neighbors. No size/contrast pruning and no
    # mapping from an ink component to any one SVG text member.
    remaining = changed_mask.copy()
    for y, x in zip(*np.nonzero(changed_mask)):
        if not remaining[y, x]:
            continue
        pending, values = [(int(y), int(x))], []
        remaining[y, x] = False
        left = right = int(x)
        top = bottom = int(y)
        while pending:
            cy, cx = pending.pop()
            values.append(contrast[cy, cx])
            left, right = min(left, cx), max(right, cx)
            top, bottom = min(top, cy), max(bottom, cy)
            for ny in range(max(0, cy-1), min(height, cy+2)):
                for nx in range(max(0, cx-1), min(width, cx+2)):
                    if remaining[ny, nx]:
                        remaining[ny, nx] = False
                        pending.append((ny, nx))
        observations['ink_components'].append({
            'pixel_bbox': [left, top, right-left+1, bottom-top+1],
            'pixel_count': len(values), 'contrast_p90': float(np.percentile(values, 90)),
        })
    return observations


def _rgba(path):
    with Image.open(path) as image:
        return np.asarray(image.convert('RGBA')).copy()


def _configuration(config):
    value = deepcopy(DEFAULT_CONFIG)
    if config is not None:
        if not isinstance(config, dict) or set(config)-set(value):
            raise ObservationUnsupported('unknown or invalid configuration fields')
        value.update(deepcopy(config))
    for key in ('text_contrast_p90_max', 'close_text_gap_height_ratio', 'close_text_vertical_overlap_height_ratio'):
        if not _finite([value[key]]) or value[key] < 0:
            raise ObservationUnsupported('invalid configuration: '+key)
    if value['close_text_vertical_overlap_height_ratio'] > 1:
        raise ObservationUnsupported('vertical overlap ratio exceeds one')
    for key in ('orthogonal_min_horizontal_segments', 'orthogonal_min_vertical_segments'):
        if type(value[key]) is not int or value[key] < 2:
            raise ObservationUnsupported('orthogonal segment minima must be integers >=2')
    if value['frequency_spellings'] != DEFAULT_CONFIG['frequency_spellings']:
        raise ObservationUnsupported('frequency spellings are frozen for this version')
    return value


def _trace(node):
    """Parse only one continuous open M/L/H/V path or numeric polyline."""
    if _tag(node) == 'polyline':
        raw = node.get('points', '')
        nums = re.findall(_NUMBER, raw)
        if re.sub(_NUMBER, '', raw).strip(' ,\t\r\n') or len(nums) < 4 or len(nums) % 2:
            return None, 'unsupported_polyline_points'
        values = [float(n) for n in nums]
        return list(zip(values[::2], values[1::2])), None
    raw = node.get('d', '')
    if re.search(r'[Zz]', raw):
        return None, 'closed_geometry'
    tokens = _TOKEN.findall(raw)
    if _TOKEN.sub('', raw).strip(' ,\t\r\n'):
        return None, 'unsupported_path_commands'
    points, current, command = [], (0.0, 0.0), None
    i, moves = 0, 0
    while i < len(tokens):
        if tokens[i].isalpha():
            command = tokens[i]
            i += 1
        if command is None or i == len(tokens):
            return None, 'invalid_path_arguments'
        cmd = command.upper()
        count = 2 if cmd in ('M', 'L') else 1
        if i+count > len(tokens) or any(t.isalpha() for t in tokens[i:i+count]):
            return None, 'invalid_path_arguments'
        numbers = [float(n) for n in tokens[i:i+count]]
        i += count
        relative = command.islower()
        if cmd in ('M', 'L'):
            point = (numbers[0]+(current[0] if relative else 0), numbers[1]+(current[1] if relative else 0))
        elif cmd == 'H':
            point = (numbers[0]+(current[0] if relative else 0), current[1])
        elif cmd == 'V':
            point = (current[0], numbers[0]+(current[1] if relative else 0))
        else:
            return None, 'unsupported_path_commands'
        if cmd == 'M':
            moves += 1
            if moves > 1:
                return None, 'multiple_subpaths'
            command = 'l' if relative else 'L'
        elif not points:
            return None, 'path_missing_move'
        points.append(point)
        current = point
    if not points or not all(_finite(p) for p in points):
        return None, 'invalid_path_coordinates'
    return points, None


def build_observation_proposals(svg_path, png_path, bounds_path, output_dir,
                                render_callback, *, pack_path=None, config=None):
    """Build facts about the current SVG/PNG; all proposals require source review.

    Writes only a newly created directory. A repaint failure produces an
    unsupported manifest and retained artifacts, and never usable proposals.
    """
    output = Path(output_dir)
    output.mkdir(parents=True, exist_ok=False)
    started = time.monotonic()
    manifest = {
        'format': 'svg-observation-manifest-v1', 'status': 'building',
        'started_utc': datetime.now(timezone.utc).isoformat(),
        'started_monotonic': started, 'artifacts': {},
        'source_image_read': False, 'renderer': 'injected_callback',
    }

    def artifacts():
        return {p.name: {'path': p.name, 'sha256': _sha(p.read_bytes())}
                for p in (output/'base-repaint.png', output/'text-hidden.svg',
                          output/'text-hidden.png', output/'text-group-components.json',
                          output/'proposals.json') if p.is_file()}

    def finish(status, reason=None):
        manifest.update(status=status, artifacts=artifacts(),
                        finished_utc=datetime.now(timezone.utc).isoformat(),
                        finished_monotonic=time.monotonic())
        manifest['duration_seconds'] = manifest['finished_monotonic']-started
        if reason:
            manifest['unsupported_reason'] = reason
        _dump(output/'manifest.json', manifest)

    try:
        options = _configuration(config)
        paths = {'current_svg': Path(svg_path), 'current_png': Path(png_path), 'bounds': Path(bounds_path)}
        inputs = {k: p.read_bytes() for k, p in paths.items()}
        hashes = {k: _sha(b) for k, b in inputs.items()}
        manifest.update(revision=hashes['current_svg'], evidence_hashes=hashes, config=options)
        svg_text = inputs['current_svg'].decode('utf-8')
        root = ET.fromstring(svg_text)
        if _tag(root) != 'svg':
            raise ObservationUnsupported('root must be an SVG')
        nodes, parent = {}, {child: node for node in root.iter() for child in node}
        for node in root.iter():
            if node.get('id'):
                if node.get('id') in nodes:
                    raise ObservationUnsupported('duplicate SVG IDs')
                nodes[node.get('id')] = node
        bounds = json.loads(inputs['bounds'])
        canvas = bounds.get('canvas', {})
        c = [canvas.get(k) for k in ('x', 'y', 'width', 'height')]
        if not _finite(c) or c[2] <= 0 or c[3] <= 0 or not isinstance(bounds.get('objects'), dict):
            raise ObservationUnsupported('unsupported native bounds schema')
        if root.get('viewBox'):
            parts = re.split(r'[\s,]+', root.get('viewBox').strip())
            if len(parts) != 4:
                raise ObservationUnsupported('unsupported SVG viewBox')
            declared_canvas = [float(v) for v in parts]
        else:
            sizes = [root.get(k, '') for k in ('width', 'height')]
            if any(not re.fullmatch(_NUMBER+r'(?:px)?', v) for v in sizes):
                raise ObservationUnsupported('unsupported SVG viewport units')
            declared_canvas = [0, 0]+[float(v.removesuffix('px')) for v in sizes]
        if not _finite(declared_canvas) or any(abs(a-b) > 1e-8 for a, b in zip(c, declared_canvas)):
            raise ObservationUnsupported('native canvas disagrees with SVG viewBox/viewport')
        ancestors = {}
        for ident, node in nodes.items():
            chain, n = [node], node
            while n in parent:
                n = parent[n]
                chain.append(n)
            ancestors[ident] = chain
        referenced = set()
        for node in root.iter():
            for key, value in node.attrib.items():
                if key.rsplit('}', 1)[-1] == 'href' and value.startswith('#'):
                    referenced.add(value[1:])
                referenced.update(re.findall(r'url\(\s*[\"\']?#([^\s)\"\']+)', value))
            if _tag(node) == 'style':
                referenced.update(re.findall(r'url\(\s*[\"\']?#([^\s)\"\']+)', node.text or ''))

        current = _rgba(paths['current_png'])
        render_callback(svg_text, output/'base-repaint.png')
        repaint = _rgba(output/'base-repaint.png')
        if repaint.shape != current.shape or not np.array_equal(repaint, current):
            raise ObservationUnsupported('normal repaint does not exactly match current PNG RGBA and dimensions')
        manifest['repaint_rgba_exact'] = True

        limits = [
            {'scope': 'all', 'reason': 'current_render_observations_only',
             'detail': 'No source image, identity, necessity, defect, correction or coverage certification is inferred.'},
            {'scope': 'text_mask', 'reason': 'white_composited_transparency',
             'detail': 'Visible RGB is composited over white; hidden RGB is ignored. Other display backgrounds are unknown.'},
            {'scope': 'text_mask', 'reason': 'aggregate_text_removal',
             'detail': 'Full-render versus text-hidden visibleRGB relative-luminance contrast is a dimensionless candidate heuristic, not compliance, necessity or contrast-to-source. Changes can include occlusion reveal, antialiasing and blending.'},
            {'scope': 'styles', 'reason': 'computed_style_not_available',
             'detail': 'Native bounds carry effects but not computed styles; intentional faintness, stylesheet visibility, external font state and paint attribution require review.'},
            {'scope': 'all', 'reason': 'no_silent_pruning', 'detail': 'All supported matching proposals are emitted; excluded and unsupported items are recorded.'},
        ]

        def exclude(ids, family, reason):
            limits.append({'target_ids': ids, 'scope': family, 'reason': reason})

        def supported(ident, family):
            chain = ancestors[ident]
            if any(_tag(n) in _DEFINITIONS for n in chain):
                exclude([ident], family, 'definition_content')
                return None
            if any(_tag(n) == 'svg' and n is not root for n in chain):
                exclude([ident], family, 'nested_svg_viewport')
                return None
            if any(n.get('id') in referenced for n in chain):
                exclude([ident], family, 'referenced_text_subtree' if family == 'text' else 'referenced_geometry_subtree')
                return None
            data = bounds['objects'].get(ident)
            if not isinstance(data, dict):
                exclude([ident], family, 'missing_native_bounds')
                return None
            for n in chain:
                measured = bounds['objects'].get(n.get('id'), {})
                if measured.get('effects') or measured.get('bounds_complete') is False or any(
                    _property(n, prop) not in ('', 'none') for prop in ('clip-path', 'mask', 'filter', 'marker-start', 'marker-mid', 'marker-end')
                ):
                    exclude([ident], family, 'incomplete_or_effect_bounds')
                    return None
            if data.get('bounds_complete') is not True:
                exclude([ident], family, 'incomplete_or_effect_bounds')
                return None
            world = data.get('world')
            if not isinstance(world, list) or len(world) != 6 or not _finite(world) or not (
                world[0] > 0 and abs(world[1]) <= 1e-9 and abs(world[2]) <= 1e-9 and abs(world[0]-world[3]) <= 1e-9
            ):
                exclude([ident], family, 'unsupported_world_transform')
                return None
            rect = _rect(data.get('geometry_bbox'))
            if rect is None:
                exclude([ident], family, 'missing_or_empty_geometry_bbox')
                return None
            if rect[0] < c[0] or rect[1] < c[1] or rect[0]+rect[2] > c[0]+c[2] or rect[1]+rect[3] > c[1]+c[3]:
                exclude([ident], family, 'outside_canvas')
                return None
            return rect

        frames = []
        if pack_path is not None:
            pack_bytes = Path(pack_path).read_bytes()
            manifest['pack_sha256'] = _sha(pack_bytes)
            pack = json.loads(pack_bytes)
            for frame in pack.get('frames', []):
                rect = frame.get('canvas_crop')
                if isinstance(frame.get('frame_id'), str) and isinstance(rect, list) and len(rect) == 4 and _finite(rect) and min(rect[2:]) > 0:
                    frames.append((frame['frame_id'], rect))
                else:
                    limits.append({'scope': 'pack', 'reason': 'unsupported_frame_viewing_aid'})
            limits.append({'scope': 'pack', 'reason': 'viewing_aids_only', 'detail': 'Frame intersections do not establish correspondence, identity, containment requirements or necessity; pair images are never read.'})

        proposals = []

        def propose(kind, ids, rect, observations):
            identity = json.dumps([kind, sorted(ids), hashes['current_svg']], separators=(',', ':'))
            proposal = {
                'id': 'obs-'+_sha(identity.encode())[:24], 'kind': kind,
                'target_ids': sorted(ids), 'bbox': rect, 'observations': observations,
                'evidence': {'revision': hashes['current_svg'], 'evidence_hashes': hashes,
                             'bounds_space': 'native_canvas', 'normal_repaint_rgba_exact': True},
                'requires_source_verification': True, 'not_a_finding': True,
            }
            aids = sorted({fid for fid, fr in frames if min(_intersect(rect, fr)[2:]) > 0})
            if aids:
                proposal['suggested_frame_ids'] = aids
            proposals.append(proposal)

        texts = {}
        css = '\n'.join(n.text or '' for n in root.iter() if _tag(n) == 'style')
        for ident, node in sorted(nodes.items()):
            if _tag(node) != 'text':
                continue
            rect = supported(ident, 'text')
            if rect is None:
                continue
            text = ''.join(node.itertext())
            if not text.strip():
                exclude([ident], 'text', 'empty_text')
                continue
            if any(_property(n, 'display') == 'none' or _property(n, 'visibility') in ('hidden', 'collapse') or
                   _property(n, 'opacity') in ('0', '0.0', '0%') for n in ancestors[ident]):
                exclude([ident], 'text', 'explicitly_hidden')
                continue
            fill = next((_property(n, 'fill') for n in ancestors[ident] if _property(n, 'fill')), '')
            stroke = next((_property(n, 'stroke') for n in ancestors[ident] if _property(n, 'stroke')), 'none')
            if fill == 'none' and stroke == 'none' and not re.search(r'(?:fill|stroke)\s*:', css):
                exclude([ident], 'text', 'explicit_no_text_paint')
                continue
            texts[ident] = (rect, text)

        # Only modify the existing text's style. Adding even an anonymous g
        # changes native parse's automatic IDs on later anonymous drawables.
        # Attribute/pseudo/structural selectors can observe a changed style;
        # unsupported CSS therefore disables masking AND pixel attribution.
        selectors = re.sub(r'\{[^}]*\}', '{}', css)
        style_dependency_unknown = bool(re.search(r'[\[\]:>+~@\\]', selectors))
        if style_dependency_unknown:
            limits.append({'scope': 'text_mask', 'reason': 'mask_style_selector_dependency_unknown',
                           'detail': 'Analysis leaves text unchanged; CSS dependencies on changed style/structure cannot be isolated.'})
        copy = deepcopy(root)
        for node in copy.iter():
            if not style_dependency_unknown and _tag(node) == 'text' and node.get('id') in texts:
                style = node.get('style', '').rstrip().rstrip(';')
                node.set('style', (style+';' if style else '')+'opacity:0 !important')
        manifest['mask_method'] = 'existing_text_inline_opacity_no_new_nodes'
        hidden_text = ET.tostring(copy, encoding='unicode')
        (output/'text-hidden.svg').write_text(hidden_text, encoding='utf-8')
        render_callback(hidden_text, output/'text-hidden.png')
        hidden = _rgba(output/'text-hidden.png')
        if hidden.shape != current.shape:
            raise ObservationUnsupported('text-hidden image dimensions differ from current PNG')
        for name, path in paths.items():
            if _sha(path.read_bytes()) != hashes[name]:
                raise ObservationUnsupported('input changed during analysis: '+name)

        overlapping = set()
        overlap_neighbors = {ident: set() for ident in texts}
        for index, a in enumerate(sorted(texts)):
            ar = texts[a][0]
            for b in sorted(texts)[index+1:]:
                br = texts[b][0]
                overlap = _intersect(ar, br)
                if min(overlap[2:]) > 0:
                    overlapping.update((a, b))
                    overlap_neighbors[a].add(b)
                    overlap_neighbors[b].add(a)
                gap = max(ar[0], br[0])-min(ar[0]+ar[2], br[0]+br[2])
                smaller = min(ar[3], br[3])
                if gap <= options['close_text_gap_height_ratio']*smaller and overlap[3] >= options['close_text_vertical_overlap_height_ratio']*smaller:
                    propose('close_text_boxes', [a, b], _union(ar, br), {
                        'horizontal_gap': gap, 'vertical_overlap': overlap[3],
                        'smaller_height': smaller, 'overlap_area': overlap[2]*overlap[3],
                        'basis': 'native_geometry_boxes_only; contact may be harmless and is source-dependent',
                    })

        height, width = current.shape[:2]
        scale_x, scale_y = width/c[2], height/c[3]
        mapping_ok = abs(scale_x-scale_y) <= 1e-9
        if not mapping_ok:
            limits.append({'scope': 'text_mask', 'reason': 'unsupported_nonuniform_canvas_pixel_mapping'})
        current_rgb, hidden_rgb = _visible_rgb(current), _visible_rgb(hidden)
        # RGB delta identifies changed visible pixels only; it is not contrast.
        diff = np.max(np.abs(current_rgb-hidden_rgb), axis=2)
        current_luminance = _relative_luminance(current_rgb)
        hidden_luminance = _relative_luminance(hidden_rgb)
        contrast_ratio = ((np.maximum(current_luminance, hidden_luminance)+0.05) /
                          (np.minimum(current_luminance, hidden_luminance)+0.05))
        group_unsupported = []
        if not mapping_ok:
            group_unsupported.append('unsupported_nonuniform_canvas_pixel_mapping')
        if style_dependency_unknown:
            group_unsupported.append('mask_style_selector_dependency_unknown')
        for members in _overlap_groups(overlap_neighbors):
            enclosure = texts[members[0]][0]
            for ident in members[1:]:
                enclosure = _union(enclosure, texts[ident][0])
            member_boxes = [{'target_id': ident, 'bbox': texts[ident][0]} for ident in members]
            propose('text_mask_overlap_group', members, enclosure,
                    _group_ink_observations(member_boxes, c, diff, contrast_ratio, group_unsupported))
        frequencies = {}
        for spelling in options['frequency_spellings']:
            frequencies.setdefault(spelling.casefold(), []).append(spelling)
        frequency_pattern = re.compile(r'(?<![\w.])('+_NUMBER+r')\s*([A-Za-z]+)(?![\w])')
        for ident, (rect, text) in sorted(texts.items()):
            if ident in overlapping:
                exclude([ident], 'text_mask', 'overlapping_text_mask_attribution')
            elif mapping_ok and not style_dependency_unknown:
                left = max(0, math.floor((rect[0]-c[0])*scale_x))
                top = max(0, math.floor((rect[1]-c[1])*scale_y))
                right = min(width, math.ceil((rect[0]+rect[2]-c[0])*scale_x))
                bottom = min(height, math.ceil((rect[1]+rect[3]-c[1])*scale_y))
                crop = diff[top:bottom, left:right]
                changed = contrast_ratio[top:bottom, left:right][crop > 1e-9]
                p90 = float(np.percentile(changed, 90)) if changed.size else None
                if p90 is None or p90 <= options['text_contrast_p90_max']:
                    propose('text_low_visible_ink', [ident], rect, {
                        'ink_state': 'no_visible_difference' if p90 is None else 'low_visible_difference',
                        'changed_visible_pixels': int(changed.size), 'contrast_p90': p90,
                        'metric': 'p90 dimensionless relative-luminance contrast ratio (maxL+0.05)/(minL+0.05) after sRGB linearization of white-composited visibleRGB, on changed pixels only',
                        'pixel_bbox': [left, top, right-left, bottom-top],
                        'intentional_or_occluded_or_unsupported_appearance_possible': True,
                    })
                else:
                    limits.append({'target_ids': [ident], 'scope': 'text_mask',
                                   'reason': 'above_low_difference_candidate_threshold',
                                   'changed_visible_pixels': int(changed.size), 'contrast_p90': p90})
            matches = []
            for match in frequency_pattern.finditer(text):
                token = match.group(2)
                canonical = frequencies.get(token.casefold(), [])
                if canonical and token not in canonical:
                    matches.append({'numeric_context': match.group(1), 'token': token,
                                    'text_span': list(match.span(2)),
                                    'matching_canonical_spellings': canonical,
                                    'casefold_ambiguous': len(canonical) > 1})
            if matches:
                propose('numeric_frequency_unit_casing', [ident], rect, {
                    'matches': matches, 'basis': 'numeric-context spelling only; meaning and source spelling are unknown',
                })
            else:
                exclude([ident], 'frequency_unit_casing', 'no_noncanonical_numeric_frequency_token')

        for ident, node in sorted(nodes.items()):
            if _tag(node) not in ('path', 'polyline'):
                continue
            rect = supported(ident, 'orthogonal_path')
            if rect is None:
                continue
            fill = next((_property(n, 'fill') for n in ancestors[ident] if _property(n, 'fill')), '')
            if fill != 'none':
                exclude([ident], 'orthogonal_path', 'fill_may_close_open_geometry')
                continue
            points, reason = _trace(node)
            if reason:
                exclude([ident], 'orthogonal_path', reason)
                continue
            if len(points) < 2 or points[0] == points[-1]:
                exclude([ident], 'orthogonal_path', 'closed_or_empty_geometry')
                continue
            horizontal = vertical = zero = 0
            diagonal = False
            for a, b in zip(points, points[1:]):
                dx, dy = b[0]-a[0], b[1]-a[1]
                if dx == 0 and dy == 0:
                    zero += 1
                elif dy == 0:
                    horizontal += 1
                elif dx == 0:
                    vertical += 1
                else:
                    diagonal = True
            if diagonal:
                exclude([ident], 'orthogonal_path', 'diagonal_segments')
            elif horizontal >= options['orthogonal_min_horizontal_segments'] and vertical >= options['orthogonal_min_vertical_segments']:
                propose('continuous_orthogonal_path', [ident], rect, {
                    'horizontal_segments': horizontal, 'vertical_segments': vertical,
                    'zero_length_segments': zero, 'subpaths': 1, 'open': True,
                    'basis': 'syntactic connected axis-aligned segments only; a step-like path may be correct',
                })
            else:
                exclude([ident], 'orthogonal_path', 'below_segment_candidate_minima')

        for node in root.iter():
            if _tag(node) in ('text', 'path', 'polyline') and not node.get('id'):
                limits.append({'scope': _tag(node), 'reason': 'missing_stable_target_id'})
        for ident in sorted(set(bounds['objects'])-set(nodes)):
            exclude([ident], 'bounds', 'bounds_id_absent_from_svg')
        # Every component is preserved for offline audit. The initial semantic
        # role always receives the same bounded-per-group projection, even for
        # empty or tiny lists; the detail artifact is not a role input.
        component_groups = {}
        groups = [p for p in proposals if p['kind'] == 'text_mask_overlap_group']
        for proposal in groups:
            observations = proposal['observations']
            components = observations.pop('ink_components')
            count = len(components) if components is not None else None
            observations['ink_component_count'] = count
            component_groups[proposal['id']] = {
                'target_ids': proposal['target_ids'], 'member_boxes': observations['member_boxes'],
                'measurement_status': observations['measurement_status'],
                'unsupported_reasons': observations['unsupported_reasons'],
                'component_count': count, 'ink_components': components,
            }
        detail = output/'text-group-components.json'
        _dump(detail, {'format': 'svg-text-group-components-v1', 'status': 'ready',
                       'revision': hashes['current_svg'], 'evidence_hashes': hashes,
                       'groups': component_groups})
        detail_hash = _sha(detail.read_bytes())
        for proposal in groups:
            proposal['observations']['component_evidence'] = {
                'artifact': detail.name, 'sha256': detail_hash, 'key': proposal['id'],
                'projection_note': 'All component detail is retained for offline audit and unavailable to this role. Do not follow this reference; omitted detail is neither passed nor negative evidence. Supplied source/current figures determine necessity.',
            }
        result = {
            'format': 'svg-observation-proposals-v1', 'status': 'ready',
            'revision': hashes['current_svg'], 'evidence_hashes': hashes,
            'config': options, 'proposals': proposals, 'coverage_limits': limits,
            'artifacts': artifacts(),
        }
        _dump(output/'proposals.json', result)
        finish('ready')
        return result
    except Exception as exc:
        finish('unsupported', str(exc))
        if isinstance(exc, ObservationUnsupported):
            raise
        raise ObservationUnsupported(str(exc)) from exc
