"""Validated, resumable local transactions shared by both constructor phases."""
import base64
from copy import deepcopy
from decimal import Decimal, InvalidOperation
import fcntl
from fractions import Fraction
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re
import xml.etree.ElementTree as ET
from .scene import digest, descendants, assert_target_scope, write_checkpoint
from .sandbox import run_code
from . import paint_effect
from .quality import crop_gate, validate_contract, converge
from ..document import validate
from ..single_call.executor import _perform as _base_perform, _resolve_id, _relation_report
from ..tp_alarms import compare_reports
from ..tight_tp import measure_tight
from ..single_call.contract import MUTATIONS


def _has_expression(value):
    if isinstance(value,dict):return any(str(k).startswith('$') or _has_expression(v) for k,v in value.items())
    if isinstance(value,list):return any(_has_expression(v) for v in value)
    return False


def _literal_patch_group(step):
    ops=step.get('args',{}).get('operations')
    return isinstance(ops,list) and bool(ops) and all(isinstance(op,dict) and op.get('method')=='bp_patch' and not op.get('id') and not _has_expression(op.get('args')) for op in ops)


def _perform(root,step,issue,original,folder,aliases,results):
    if step.get('method')=='bp_program' and _literal_patch_group(step):
        return _base_perform(root,step,issue,original,folder,aliases,results)
    if step.get('method')=='bp_program':
        values=[];actual=[];reports=[]
        for index,child in enumerate(step['args']['operations']):
            value,args,child_reports=_perform(root,child,issue,original,folder/f'nested-{index}',aliases,results)
            if child.get('id'):results[child['id']]=deepcopy(value)
            values.append(value);actual.append(args);reports.extend(child_reports)
        return {'operations':values},{'operations':actual},reports
    if step.get('method')=='check_tp':
        report=_relation_report(root,issue.get('relations',[]),aliases)
        return report,deepcopy(step.get('args',{})),[]
    return _base_perform(root,step,issue,original,folder,aliases,results)


def _atomic_json(path,data):
    tmp=path.with_suffix('.tmp');tmp.write_text(json.dumps(data,ensure_ascii=False,indent=2));tmp.replace(path)


def _id_list(value):
    if isinstance(value,str) and value.strip():return [value]
    if isinstance(value,list):return [item for item in value if isinstance(item,str) and item.strip()]
    return []


def normalize_relations(program, issues):
    """Accept the relation shapes the planner actually writes.

    subject_id/object_id stay as written. target_ids with reference_ids or
    container_ids become those two sides. A contain rule with several contents
    becomes one relation per content, and its repair is copied onto each.
    Missing relation evidence is taken from the issue that already stated it.
    """
    rules=program.get('relations')
    if not isinstance(rules,list):return
    evidence=' '.join(str(issue.get('original_evidence') or '').strip() for issue in issues if isinstance(issue,dict)).strip()
    expanded=[];clones=[]
    for rule in rules:
        if not isinstance(rule,dict):
            expanded.append(rule);continue
        if not str(rule.get('reference_evidence') or '').strip() and evidence:
            rule['reference_evidence']=evidence
        if rule.get('subject_id') and rule.get('object_id'):
            expanded.append(rule);continue
        targets=_id_list(rule.get('target_ids'))
        containers=_id_list(rule.get('container_ids')) or _id_list(rule.get('reference_ids'))
        predicate=rule.get('predicate') or rule.get('kind')
        if predicate=='contain' and targets and containers:
            pairs=[(target,containers[0]) for target in targets]
        elif len(targets)>=2 and not containers:
            pairs=[(targets[0],targets[1])]
        elif targets and containers:
            pairs=[(targets[0],containers[0])]
        else:
            pairs=[]
        if not pairs:
            expanded.append(rule);continue
        base=rule.get('id') if isinstance(rule.get('id'),str) and rule['id'].strip() else 'relation'
        for index,(subject,obj) in enumerate(pairs):
            item=dict(rule);item['subject_id']=subject;item['object_id']=obj
            item['id']=base if index==0 else f'{base}__{index}'
            expanded.append(item)
            if index:clones.append((base,item['id']))
    program['relations']=expanded
    repairs=(program.get('convergence') or {}).get('repairs')
    if isinstance(repairs,list):
        for old,new in clones:
            for op in list(repairs):
                if isinstance(op,dict) and op.get('check_id')==old:
                    copy=dict(op);copy['check_id']=new;repairs.append(copy)


def _contains_measure(value):
    if isinstance(value,dict):return '$measure' in value or any(_contains_measure(v) for v in value.values())
    if isinstance(value,list):return any(_contains_measure(v) for v in value)
    return False


def _measurement_references(value):
    refs=set()
    if isinstance(value,dict):
        if '$measure' in value:
            spec=value['$measure']
            if not isinstance(spec,dict) or not isinstance(spec.get('ids'),list) or any(not isinstance(x,str) for x in spec['ids']):raise ValueError('measurement requires explicit current object IDs')
            refs.update(spec['ids'])
        for child in value.values():refs.update(_measurement_references(child))
    elif isinstance(value,list):
        for child in value:refs.update(_measurement_references(child))
    return refs


def _walk_operations(operations):
    for operation in operations:
        yield operation
        if operation.get('method')=='bp_program':
            yield from _walk_operations(operation['args']['operations'])


def _compile_typed_scope(program,root):
    existing={n.get('id') for n in root.iter() if n.get('id')}
    created=set();writes=set();sources=[]
    def visit(operations,path):
        if not isinstance(operations,list):raise ValueError('typed operations must be array')
        for index,op in enumerate(operations):
            if not isinstance(op,dict) or not isinstance(op.get('target_ids'),list) or any(not isinstance(t,str) for t in op['target_ids']):raise ValueError('typed target_ids must be explicit strings')
            ids=set(op['target_ids']);where=path+[index]
            if not ids<=existing|created:raise ValueError('typed operation references unknown or not-yet-created ID')
            if op.get('method') in MUTATIONS|{'bp_program'}:
                writes.update(ids);sources.append({'path':where+['target_ids'],'target_ids':list(op['target_ids'])})
            args=op.get('args',{})
            if not isinstance(args,dict):raise ValueError('typed args must be object')
            for anchor in ('parent_id','before_id','after_id'):
                if anchor in args and args[anchor]!='@parent' and args[anchor] not in existing|created:raise ValueError('typed anchor references unknown or not-yet-created ID')
            if op.get('method') not in MUTATIONS|{'sample_colors','measure','check_tp','bp_program'}:raise ValueError('unsupported typed module method')
            if op.get('method')!='bp_program' and not _measurement_references(args)<=existing|created:raise ValueError('measurement references unknown or not-yet-created ID')
            if op.get('method')=='bp_program':visit(args.get('operations'),where+['args','operations'])
            if op.get('method')=='bp_add':
                fragment=ET.fromstring('<g>'+args.get('svg','')+'</g>')
                fresh=[n.get('id') for n in list(fragment.iter())[1:]]
                if not fresh or any(not i for i in fresh) or len(set(fresh))!=len(fresh) or set(fresh)&(existing|created):raise ValueError('new SVG IDs must be explicit and unique')
                created.update(fresh)
    visit(program.get('args',{}).get('operations',[]),['args','operations'])
    visit(program.get('convergence',{}).get('repairs',[]),['convergence','repairs'])
    return {'existing_write_ids':sorted(writes&existing),'created_write_ids':sorted(writes&created),'created_ids':sorted(created),'sources':sources,'basis':'explicit typed mutation target_ids only'}


def _execution_targets(program):
    if program.get('route')=='module_program':
        return program.get('compiled_scope',{}).get('existing_write_ids',[]) or program['target_ids']
    return program['target_ids']


def _prior_executed(records,images,roots):
    """Already executed same-task programs count as previous dependencies."""
    seen={};touched={}
    if records is None:records=[]
    if not isinstance(records,list):raise ValueError('prior executed programs must be an array')
    for record in records:
        if not isinstance(record,dict):raise ValueError('prior executed program must be an object')
        pid=record.get('program_id') or record.get('id')
        im=record.get('image_id')
        if not isinstance(pid,str) or not pid or pid in seen:raise ValueError('prior executed program identity must be unique')
        if im not in images:raise ValueError('prior executed program image is outside this task')
        raw=record.get('effective_target_ids') or record.get('target_ids') or []
        if not isinstance(raw,list) or any(not isinstance(t,str) for t in raw):raise ValueError('prior executed program targets must be ids')
        existing={n.get('id') for n in roots[im].iter() if n.get('id')}
        present=[t for t in raw if t in existing]
        objects=set(descendants(roots[im],present)) if present else set()
        objects.update(t for t in raw if t not in existing)
        deps=record.get('depends_on') or []
        if not isinstance(deps,list) or any(not isinstance(d,str) for d in deps):raise ValueError('prior executed dependencies must be ids')
        seen[pid]={'id':pid,'image_id':im,'_ancestors':set(deps),'_prior':True}
        touched.setdefault(im,[]).append((pid,objects))
    return seen,touched


def _has_cuboid_replace(program):
    def walk(operations):
        if not isinstance(operations, list):
            return False
        for op in operations:
            if not isinstance(op, dict):
                continue
            args = op.get('args') if isinstance(op.get('args'), dict) else {}
            data = args.get('data')
            if (op.get('method') == 'sp_replace' and args.get('kind') == 'geometry'
                    and isinstance(data, dict) and (
                        data.get('shape') in ('cuboid', 'lattice')
                        or (data.get('shape') == 'cluster' and isinstance(data.get('items'), list) and data['items']
                            and all(isinstance(item, dict) and item.get('shape') == 'cuboid' for item in data['items'])))):
                return True
            if op.get('method') == 'bp_program' and walk(args.get('operations')):
                return True
        return False
    return walk(program.get('args', {}).get('operations'))


def _existing_image_photo_replace(program, selected_issues, root):
    """Exempt only one audited photo replacement of existing image-only assets."""
    if (program.get('route') != 'module_program' or 'source_code' in program
            or {issue.get('category') for issue in selected_issues} != {'S1'}):
        return False
    convergence = program.get('convergence', {})
    if not isinstance(convergence, dict) or convergence.get('repairs'):
        return False
    args = program.get('args')
    if not isinstance(args, dict) or set(args) != {'operations'}:
        return False
    operations = args['operations']
    if not isinstance(operations, list) or len(operations) != 1:
        return False
    operation = operations[0]
    if not isinstance(operation, dict) or operation.get('method') != 'sp_photo':
        return False
    declared, targets = program.get('target_ids'), operation.get('target_ids')
    issue_targets = {target for issue in selected_issues for target in issue.get('target_ids', [])}
    if (not isinstance(declared, list) or not declared or not isinstance(targets, list)
            or any(not isinstance(t, str) or not t for t in declared + targets)
            or len(declared) != len(set(declared)) or len(targets) != len(set(targets))
            or set(declared) != set(targets) or not set(targets) <= issue_targets):
        return False
    by_id = {node.get('id'): node for node in root.iter() if node.get('id')}
    for target in targets:
        node = by_id.get(target)
        if node is None:
            return False
        nodes = list(node.iter())
        if (not any(n.tag.rsplit('}', 1)[-1] == 'image' for n in nodes)
                or any(n.tag.rsplit('}', 1)[-1] not in ('g', 'image')
                       or (n.tag.rsplit('}', 1)[-1] == 'image' and len(n)) for n in nodes)):
            return False
    return True


def _has_arrow(program):
    def walk(operations):
        if not isinstance(operations, list):
            return False
        for op in operations:
            if not isinstance(op, dict):
                continue
            args = op.get('args') if isinstance(op.get('args'), dict) else {}
            if op.get('method') == 'sp_replace' and args.get('kind') == 'arrow':
                return True
            if op.get('method') == 'bp_program' and walk(args.get('operations')):
                return True
        return False
    return walk(program.get('args', {}).get('operations'))


_LINE_NUMBER = r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
_LINE_SEPARATOR = r'(?:\s*,\s*|\s+|(?=[+-]))'
_SINGLE_LINE = re.compile(
    rf'\s*M\s*({_LINE_NUMBER}){_LINE_SEPARATOR}({_LINE_NUMBER})\s*'
    rf'L\s*({_LINE_NUMBER}){_LINE_SEPARATOR}({_LINE_NUMBER})\s*'
)


def _line_tokens(value):
    match = _SINGLE_LINE.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    try:
        for token in match.groups():
            decimal = Decimal(token)
            number = float(decimal)
            unit = float(f'1e{decimal.as_tuple().exponent}')
            if (not math.isfinite(number) or (decimal != 0 and number == 0)
                    or not math.isfinite(unit) or unit == 0):
                return None
    except (ValueError, OverflowError, InvalidOperation):
        return None
    return match.groups()


def _segment_meets_rounding_cell(start, end, endpoint, tokens):
    """The old segment must intersect the endpoint's decimal rounding box."""
    lower, upper = Fraction(0), Fraction(1)
    for origin, finish, center, token in zip(start, end, endpoint, tokens):
        exponent = Decimal(token).as_tuple().exponent
        half_unit = Fraction(10 ** exponent, 2) if exponent >= 0 else Fraction(1, 2 * 10 ** -exponent)
        delta = finish - origin
        if not delta:
            if abs(center - origin) > half_unit:
                return False
            continue
        edges = sorted(((center - half_unit - origin) / delta,
                        (center + half_unit - origin) / delta))
        lower, upper = max(lower, edges[0]), min(upper, edges[1])
        if lower > upper:
            return False
    return True


def _marked_line_endpoint_repair(program, selected_issues, root):
    """Admit only scoped inward trims of existing locally marker-ended lines."""
    if program.get('route') != 'module_program' or {i.get('category') for i in selected_issues} != {'D'}:
        return False
    convergence = program.get('convergence') or {}
    if not isinstance(convergence, dict) or convergence.get('repairs'):
        return False
    args = program.get('args')
    operations = args.get('operations') if isinstance(args, dict) else None
    declared_ids = program.get('target_ids')
    issue_targets = {target for issue in selected_issues for target in issue.get('target_ids', [])}
    if (not isinstance(operations, list) or not operations or not isinstance(declared_ids, list)
            or any(not isinstance(target, str) for target in declared_ids)
            or len(declared_ids) != len(set(declared_ids)) or not set(declared_ids) <= issue_targets):
        return False
    by_id = {node.get('id'): node for node in root.iter() if node.get('id')}
    edited = []
    for op in operations:
        if not isinstance(op, dict) or set(op) != {'method', 'target_ids', 'args'}:
            return False
        targets, args = op.get('target_ids'), op.get('args')
        if (op.get('method') != 'bp_patch' or not isinstance(targets, list) or len(targets) != 1
                or not isinstance(args, dict) or set(args) != {'attributes'}
                or not isinstance(args['attributes'], dict) or set(args['attributes']) != {'d'}):
            return False
        target = targets[0]
        if not isinstance(target, str) or target not in declared_ids:
            return False
        node = by_id.get(target)
        if node is None or node.tag.rsplit('}', 1)[-1] != 'path' or len(node):
            return False
        marker_ref = re.fullmatch(r'url\(#([^)]+)\)', node.get('marker-end') or '')
        marker = by_id.get(marker_ref.group(1)) if marker_ref else None
        if marker is None or marker.tag.rsplit('}', 1)[-1] != 'marker':
            return False
        old_tokens = _line_tokens(node.get('d'))
        new_tokens = _line_tokens(args['attributes']['d'])
        if old_tokens is None or new_tokens is None:
            return False
        old = tuple(Fraction(Decimal(value)) for value in old_tokens)
        new = tuple(Fraction(Decimal(value)) for value in new_tokens)
        start, end, endpoint = old[:2], old[2:], new[2:]
        vector = tuple(finish - origin for origin, finish in zip(start, end))
        offset = tuple(center - origin for origin, center in zip(start, endpoint))
        length_squared = sum(axis * axis for axis in vector)
        projection = sum(axis * step for axis, step in zip(vector, offset))
        if (not length_squared or old[:2] != new[:2] or not 0 < projection < length_squared
                or not _segment_meets_rounding_cell(start, end, endpoint, new_tokens[2:])):
            return False
        edited.append(target)
    return len(edited) == len(set(edited)) and set(edited) == set(declared_ids)


_PAINT_COLOR = re.compile(r'#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})')
_PAINT_PAIR = rf'({_LINE_NUMBER}){_LINE_SEPARATOR}({_LINE_NUMBER})'
_PAINT_CUBIC = re.compile(rf'\s*M\s*{_PAINT_PAIR}\s*C\s*{_PAINT_PAIR}{_LINE_SEPARATOR}{_PAINT_PAIR}{_LINE_SEPARATOR}{_PAINT_PAIR}\s*')
_PAINT_TRIANGLE = re.compile(rf'\s*M\s*{_PAINT_PAIR}\s*L\s*{_PAINT_PAIR}\s*L\s*{_PAINT_PAIR}\s*Z\s*')
_PAINT_VIEWBOX = re.compile(rf'\s*{_PAINT_PAIR}{_LINE_SEPARATOR}{_PAINT_PAIR}\s*')
_PAINT_PATH_ATTRIBUTES = {'id', 'd', 'fill', 'stroke', 'stroke-width', 'stroke-dasharray',
                          'stroke-dashoffset', 'stroke-linecap', 'stroke-linejoin', 'marker-end'}
_PAINT_MARKER_ATTRIBUTES = {'id', 'markerUnits', 'markerWidth', 'markerHeight', 'viewBox',
                            'refX', 'refY', 'orient'}
_PAINT_CSS_PROPERTIES = {'fill', 'stroke', 'stroke-width', 'stroke-dasharray', 'stroke-dashoffset',
                         'stroke-linecap', 'stroke-linejoin', 'font-family', 'font-size', 'font-weight'}


def _paint_numbers(value, pattern):
    """Fully consume a supported grammar, preserving exact finite geometry."""
    match = pattern.fullmatch(value) if isinstance(value, str) else None
    if match is None:
        return None
    try:
        values = tuple(Decimal(token) for token in match.groups())
        if any(not math.isfinite(float(number)) or (number != 0 and float(number) == 0)
               for number in values):
            return None
        return tuple(Fraction(number) for number in values)
    except (ValueError, OverflowError, InvalidOperation):
        return None


def _paint_number(value):
    values = _paint_numbers(value, re.compile(rf'\s*({_LINE_NUMBER})\s*'))
    return values[0] if values is not None else None


def _paint_tag(node):
    if not isinstance(node.tag, str):
        return ''
    # Foreign namespace lookalikes do not establish SVG geometry or paint.
    if node.tag.startswith('{') and not node.tag.startswith('{http://www.w3.org/2000/svg}'):
        return ''
    return node.tag.rsplit('}', 1)[-1]


def _paint_dasharray(value):
    if not isinstance(value, str) or re.fullmatch(rf'{_LINE_NUMBER}(?:{_LINE_SEPARATOR}{_LINE_NUMBER})*', value) is None:
        return False
    lengths = [_paint_number(token) for token in re.findall(_LINE_NUMBER, value)]
    return all(length is not None and length >= 0 for length in lengths) and any(lengths)


def _paint_css_literal(property_name, value):
    """Only literal declaration grammars needed by unmatched simple classes."""
    if property_name in {'fill', 'stroke'}:
        if value == 'none' or _PAINT_COLOR.fullmatch(value):
            return True
        rgba = re.compile(rf'rgba\(\s*({_LINE_NUMBER})\s*,\s*({_LINE_NUMBER})\s*,\s*({_LINE_NUMBER})\s*,\s*({_LINE_NUMBER})\s*\)')
        channels = _paint_numbers(value, rgba)
        return channels is not None and all(0 <= c <= 255 for c in channels[:3]) and 0 <= channels[3] <= 1
    if property_name == 'font-family':
        family = r'''(?:[A-Za-z][A-Za-z0-9 -]*|'[A-Za-z][A-Za-z0-9 -]*'|"[A-Za-z][A-Za-z0-9 -]*")'''
        return re.fullmatch(rf'{family}(?:\s*,\s*{family})*', value) is not None
    if property_name == 'font-weight':
        return value in {'normal', 'bold', 'bolder', 'lighter', *(str(n) for n in range(100, 1000, 100))}
    if property_name == 'font-size':
        number = _paint_number(value.removesuffix('px'))
        return number is not None and number > 0
    if property_name in {'stroke-width', 'stroke-dashoffset'}:
        number = _paint_number(value)
        return number is not None and (property_name == 'stroke-dashoffset' or number >= 0)
    if property_name == 'stroke-dasharray':
        return value == 'none' or bool(_paint_dasharray(value))
    if property_name == 'stroke-linecap':
        return value in {'butt', 'round', 'square'}
    if property_name == 'stroke-linejoin':
        return value in {'miter', 'round', 'bevel'}
    return False


def _paint_styles_unambiguous(root, source):
    # ElementTree discards processing instructions and DTD declarations.
    if re.search(r'<\?(?!xml(?:\s|\?>))|<!DOCTYPE|<!ENTITY', source, re.I):
        return False
    rule = re.compile(r'\s*\.[A-Za-z_][A-Za-z0-9_-]*\s*\{([^{}]*)\}')
    for node in root.iter():
        tag = _paint_tag(node)
        if (not tag or tag in {'script', 'foreignObject', 'set', 'discard', 'link'} or tag.startswith('animate')
                or any(name.lower().startswith('on') for name in node.attrib)):
            return False
        if tag != 'style':
            continue
        if node.attrib or len(node):
            return False
        css, position = node.text or '', 0
        while css[position:].strip():
            match = rule.match(css, position)
            if match is None:
                return False
            declarations = match.group(1).split(';')
            if not declarations[-1].strip():
                declarations.pop()
            if not declarations:
                return False
            for declaration in declarations:
                pair = declaration.split(':')
                if len(pair) != 2 or pair[0].strip() not in _PAINT_CSS_PROPERTIES:
                    return False
                value = pair[1].strip()
                if not _paint_css_literal(pair[0].strip(), value):
                    return False
            position = match.end()
    return True


def _paint_ancestor_context(node, parents, root, *, marker=False):
    """Only plain groups/defs and a numeric root viewport are supported."""
    ancestors = []
    current = parents.get(node)
    while current is not None:
        ancestors.append(current)
        if current is root:
            if (_paint_tag(current) != 'svg' or not set(current.attrib) <= {'id', 'width', 'height', 'viewBox'}
                    or any((_paint_number(current.get(name)) or 0) <= 0 for name in ('width', 'height'))):
                return None
            box = _paint_numbers(current.get('viewBox'), _PAINT_VIEWBOX)
            if box is None or min(box[2:]) <= 0:
                return None
            return ancestors
        if _paint_tag(current) != ('defs' if marker else 'g') or not set(current.attrib) <= {'id'}:
            return None
        current = parents.get(current)
    return None


def _paint_independent_marker(marker, parents, root):
    if (_paint_tag(marker) != 'marker' or not set(marker.attrib) <= _PAINT_MARKER_ATTRIBUTES
            or not _PAINT_MARKER_ATTRIBUTES <= set(marker.attrib) or len(marker) != 1
            or marker.get('markerUnits') not in {'userSpaceOnUse', 'strokeWidth'}
            or marker.get('orient') not in {'auto', 'auto-start-reverse'}):
        return None
    if any((_paint_number(marker.get(name)) or 0) <= 0 for name in ('markerWidth', 'markerHeight')):
        return None
    if any(_paint_number(marker.get(name)) is None for name in ('refX', 'refY')):
        return None
    box = _paint_numbers(marker.get('viewBox'), _PAINT_VIEWBOX)
    if box is None or min(box[2:]) <= 0:
        return None
    head = marker[0]
    if (_paint_tag(head) != 'path' or len(head) or not set(head.attrib) <= {'id', 'd', 'fill'}
            or _PAINT_COLOR.fullmatch(head.get('fill') or '') is None):
        return None
    triangle = _paint_numbers(head.get('d'), _PAINT_TRIANGLE)
    if triangle is None:
        return None
    x0, y0, x1, y1, x2, y2 = triangle
    if (x1 - x0) * (y2 - y0) == (x2 - x0) * (y1 - y0):
        return None
    if any(not box[0] <= x <= box[0] + box[2] or not box[1] <= y <= box[1] + box[3]
           for x, y in ((x0, y0), (x1, y1), (x2, y2))):
        return None
    ancestors = _paint_ancestor_context(marker, parents, root, marker=True)
    return [marker, head, *ancestors] if ancestors is not None else None


def _paint_png_resource(node, value):
    """A canonical PNG image cannot instantiate this document's SVG subtree."""
    from PIL import Image
    prefix = 'data:image/png;base64,'
    if _paint_tag(node) != 'image' or not value.startswith(prefix):
        return False
    encoded = value[len(prefix):]
    try:
        data = base64.b64decode(encoded, validate=True)
        if (base64.b64encode(data).decode() != encoded
                or not data.startswith(b'\x89PNG\r\n\x1a\n')
                or not data.endswith(b'\x00\x00\x00\x00IEND\xaeB`\x82')):
            return False
        # verify checks PNG structure/CRCs without decoding or rendering pixels.
        with Image.open(BytesIO(data), formats=['PNG']) as image:
            image.verify()
    except (ValueError, OSError, SyntaxError, Image.DecompressionBombError):
        return False
    return True


def _paint_consumers_unambiguous(nodes, by_id, source_ids):
    """Prove exact references; never guess how a browser normalizes a URL.

    Unknown URLs fail closed even when they appear unrelated. Only canonical
    local fragments and canonical url(#id) values are supported, plus verified
    PNG resources on image elements. IDs of source ancestors are protected too.
    """
    local_id = r'[A-Za-z_][A-Za-z0-9_.-]*'
    for node in nodes:
        for name, value in node.attrib.items():
            if name == '{http://www.w3.org/XML/1998/namespace}base':
                return False
            if name.rsplit('}', 1)[-1] == 'href':
                if _paint_png_resource(node, value):
                    continue
                reference = re.fullmatch(rf'#({local_id})', value)
                if (reference is None or reference.group(1) not in by_id
                        or reference.group(1) in source_ids):
                    return False
                continue
            # Escapes/comments/control characters can obscure CSS function tokens.
            # Supporting them would need a full CSS parser, beyond this predicate.
            if ('\\' in value or '/*' in value or '*/' in value
                    or any(ord(c) < 32 or ord(c) == 127 for c in value)):
                return False
            if 'url' in value.lower():
                reference = re.fullmatch(rf'url\(#({local_id})\)', value)
                if (reference is None or reference.group(1) not in by_id
                        or reference.group(1) in source_ids):
                    return False
    return True


def _marked_cubic_fill_removal(program, selected_issues, root, source):
    """Prove a single literal fill removal leaves cubic shafts and heads intact.

    This is deliberately not a general CSS/path renderer. Unhandled presentation,
    reference consumers, geometry, or program shapes retain the SP requirement.
    """
    if program.get('route') != 'module_program' or 'source_code' in program:
        return False
    convergence = program.get('convergence', {})
    if (not isinstance(convergence, dict) or not isinstance(convergence.get('repairs', []), list)
            or convergence.get('repairs')):
        return False
    args = program.get('args')
    if not isinstance(args, dict) or set(args) != {'operations'}:
        return False
    operations = args['operations']
    if not isinstance(operations, list) or len(operations) != 1:
        return False
    operation = operations[0]
    if (not isinstance(operation, dict) or set(operation) != {'method', 'target_ids', 'args'}
            or operation['method'] != 'bp_patch'
            or operation['args'] != {'attributes': {'fill': 'none'}}):
        return False
    declared, targets = program.get('target_ids'), operation['target_ids']
    issue_targets = {target for issue in selected_issues for target in issue.get('target_ids', [])}
    if (not isinstance(declared, list) or not declared or not isinstance(targets, list)
            or any(not isinstance(t, str) or not t for t in declared + targets)
            or len(declared) != len(set(declared)) or len(targets) != len(set(targets))
            or set(declared) != set(targets) or not set(targets) <= issue_targets):
        return False
    if not _paint_styles_unambiguous(root, source):
        return False
    nodes = list(root.iter())
    by_id = {node.get('id'): node for node in nodes if node.get('id')}
    if len(by_id) != sum(bool(node.get('id')) for node in nodes):
        return False
    parents = {child: parent for parent in nodes for child in parent}
    source_nodes = set()
    for target in targets:
        node = by_id.get(target)
        if (node is None or _paint_tag(node) != 'path' or len(node)
                or not set(node.attrib) <= _PAINT_PATH_ATTRIBUTES
                or _PAINT_COLOR.fullmatch(node.get('stroke') or '') is None
                or (_paint_number(node.get('stroke-width')) or 0) <= 0
                or ('fill' in node.attrib and _PAINT_COLOR.fullmatch(node.get('fill')) is None)):
            return False
        curve = _paint_numbers(node.get('d'), _PAINT_CUBIC)
        if curve is None or curve[:2] == curve[-2:]:
            return False
        if node.get('stroke-linecap', 'butt') not in {'butt', 'round', 'square'}:
            return False
        if node.get('stroke-linejoin', 'miter') not in {'miter', 'round', 'bevel'}:
            return False
        if 'stroke-dashoffset' in node.attrib and _paint_number(node.get('stroke-dashoffset')) is None:
            return False
        if 'stroke-dasharray' in node.attrib:
            if not _paint_dasharray(node.get('stroke-dasharray')):
                return False
        ancestors = _paint_ancestor_context(node, parents, root)
        if ancestors is None:
            return False
        source_nodes.update([node, *ancestors])
        reference = re.fullmatch(r'url\(#([A-Za-z_][A-Za-z0-9_.-]*)\)', node.get('marker-end') or '')
        marker = by_id.get(reference.group(1)) if reference else None
        if marker is None or _paint_independent_marker(marker, parents, root) is None:
            return False
    source_ids = {node.get('id') for node in source_nodes if node.get('id')}
    return _paint_consumers_unambiguous(nodes, by_id, source_ids)


def validate_programs(programs,issues,images,prior_executed=None,*,capabilities=None):
    from ..capabilities import normalize_capabilities,reject_disabled_program
    policy=normalize_capabilities(capabilities)
    for program in programs:
        reject_disabled_program(program,policy)
        if not policy['code_methods'] and isinstance(program.get('source_code'),str):
            from .sandbox import validate_stdlib_source
            validate_stdlib_source(program['source_code'])
    if not isinstance(programs,list) or not isinstance(issues,list):raise ValueError('programs and issues must be arrays')
    issue_map={i['id']:i for i in issues};last_order={};scope={};issue_sets={}
    result_ids={p.get('id') for p in programs if isinstance(p,dict) and isinstance(p.get('id'),str)}
    sources={im:Path(v['svg']).read_text() for im,v in images.items()}
    roots={im:ET.fromstring(source) for im,source in sources.items()}
    seen,touched=_prior_executed(prior_executed,images,roots)
    for im,v in images.items():
        if digest(v['svg'])!=v['revision']:raise ValueError('input SVG revision changed')
        validate(roots[im])
    for p in programs:
        pid=p.get('id');im=p.get('image_id')
        if not isinstance(pid,str) or not pid or pid in seen:raise ValueError('program identity must be unique')
        if im not in images or p.get('base_revision')!=images[im]['revision']:raise ValueError('program base revision mismatch')
        if p.get('phase') not in ('preconstructor','reconstructor'):raise ValueError('unknown constructor phase')
        deps=p.get('depends_on',[])
        if not isinstance(deps,list) or any(d not in seen or seen[d]['image_id']!=im for d in deps):raise ValueError('dependencies must be previous same-image programs')
        trigger=p.get('when')
        if trigger is not None:
            if not isinstance(trigger,dict) or trigger.get('program') not in deps or trigger.get('status') not in ('failed','blocked','changed_unverified','executed_no_change'):raise ValueError('conditional trigger must name a preceding same-image dependency and supported execution status')
        refs=p.get('issue_ids')
        if not isinstance(refs,list) or not refs or any(r not in issue_map or issue_map[r]['image_id']!=im for r in refs):raise ValueError('unknown issue reference')
        selected=[issue_map[r] for r in refs]
        categories=[i.get('category') for i in selected]
        if any(c not in ('A','B','C','D','E','F','S1','S2','S3','S4') for c in categories):raise ValueError('unknown issue category')
        if policy['code_methods'] and 'S1' in categories and not (_has_cuboid_replace(p) or _existing_image_photo_replace(p,selected,roots[im])):raise ValueError('regular solid must be replaced with SP cuboid or lattice')
        if policy['code_methods'] and 'D' in categories and not (_has_arrow(p) or _marked_line_endpoint_repair(p,selected,roots[im]) or _marked_cubic_fill_removal(p,selected,roots[im],sources[im])):raise ValueError('arrow must be rebuilt with SP arrow')
        if set(categories) in ({'D'}, {'S2'}):
            p['depends_on']=[]
            p.pop('when',None)
            deps=[]
        ranks=[ord(c)-ord('A') for c in categories if len(c)==1]
        if ranks:
            # Inspection priority is distinct from execution dependency order.
            last_order[im]=max(ranks)
        target_ids=p.get('target_ids')
        if not isinstance(target_ids,list) or not target_ids or any(not isinstance(t,str) for t in target_ids):raise ValueError('explicit target_ids required')
        allowed={t for i in selected for t in i.get('target_ids',[])+i.get('neighbor_ids',[])}
        allowed=descendants(roots[im],list(allowed))
        destructive=descendants(roots[im],list({t for i in selected for t in i.get('target_ids',[])}))
        if p.get('route')=='module_program':
            existing_ids={n.get('id') for n in roots[im].iter() if n.get('id')}
            if not set(target_ids)<=existing_ids:raise ValueError('declared target is unknown current object')
            p['compiled_scope']=_compile_typed_scope(p,roots[im])
            objects=descendants(roots[im],p['compiled_scope']['existing_write_ids'])
            destructive=objects
        else:
            p.pop('compiled_scope',None)
            if not set(target_ids)<=allowed:raise ValueError('target outside issue scope')
            objects=descendants(roots[im],target_ids)
        ancestors=set(deps)
        for dep in deps:ancestors.update(seen[dep]['_ancestors'])
        for old,old_targets in touched.get(im,[]):
            if objects & old_targets and old not in ancestors:raise ValueError('same-object programs require explicit dependency')
        touched.setdefault(im,[]).append((pid,objects))
        read_scope={n.get('id') for n in roots[im].iter() if n.get('id')}
        read_refs=set()
        normalize_relations(p,selected)
        rules=p.get('relations',[])
        if not isinstance(rules,list):raise ValueError('relations must be an array')
        for rule in rules:
            if isinstance(rule,dict) and not rule.get('predicate') and rule.get('kind') in ('contain','separate','legal_overlap'):
                rule['predicate']=rule['kind']
            if not isinstance(rule,dict) or rule.get('predicate') not in ('contain','separate','legal_overlap'):raise ValueError('unsupported relation')
            if not isinstance(rule.get('id'),str) or not rule['id'].strip():raise ValueError('relation requires id')
            missing=[name for name in (rule.get('subject_id'),rule.get('object_id')) if name not in read_scope]
            if missing:raise ValueError('relation references unknown current object: '+', '.join(map(str,missing)))
            read_refs.update((rule['subject_id'],rule['object_id']))
            if not isinstance(rule.get('reference_evidence'),str) or not rule['reference_evidence'].strip():raise ValueError('relation requires original evidence')
        convergence_refs=_measurement_references(p.get('convergence',{}))
        if not convergence_refs<=read_scope:raise ValueError('convergence measurement references unknown current object')
        read_refs.update(convergence_refs)
        validate_contract(p,selected,read_scope,objects,capabilities=policy,source_root=roots[im],source_text=sources[im])
        for check in p.get('convergence',{}).get('alignment_checks',[]):
            refs=check.get('target_ids',[])+check.get('reference_ids',[])
            if not set(refs)<=read_scope:raise ValueError('alignment check references unknown current object')
            read_refs.update(refs)
        if p.get('route')=='generated_python':
            if not set(target_ids)<=destructive:raise ValueError('generated replacement cannot target a mere neighbor')
            if not isinstance(p.get('source_code'),str) or not p['source_code'].strip():raise ValueError('source_code required')
        elif p.get('route')=='module_program':
            ops=p.get('args',{}).get('operations')
            if not isinstance(ops,list) or (not ops and not p.get('convergence',{}).get('repairs')):raise ValueError('module operations or convergence repairs required')
            created=set();existing={n.get('id') for n in roots[im].iter() if n.get('id')}
            for op in _walk_operations(ops):
                crop_gate(op,images[im]['original'])
                operation_id=op.get('id')
                if operation_id is not None:
                    if not isinstance(operation_id,str) or not operation_id or operation_id in result_ids:raise ValueError('operation result identity collides with another operation or program')
                    result_ids.add(operation_id)
                if op.get('method') not in MUTATIONS|{'sample_colors','measure','check_tp','bp_program'}:raise ValueError('unsupported module method')
                if not isinstance(op.get('args'),dict) or not isinstance(op.get('target_ids'),list):raise ValueError('operation args and target_ids required')
                if not set(op['target_ids'])<=((read_scope if op['method'] in ('measure','check_tp') else objects)|created):raise ValueError('operation outside declared transaction scope')
                expression_refs=set() if op['method']=='bp_program' else _measurement_references(op.get('args',{}))
                if not expression_refs<=read_scope|created:raise ValueError('measurement references unknown current object')
                read_refs.update(expression_refs)
                if op['method'] in ('measure','check_tp'):read_refs.update(op['target_ids'])
                if op['method'] in ('sp_replace','sp_photo','bp_remove') and not set(op['target_ids'])<=destructive|created:raise ValueError('destructive operation cannot target a mere neighbor')
                for name in ('parent_id','before_id','after_id'):
                    value=op['args'].get(name)
                    if value == '@parent' and name=='parent_id':
                        if set(op['target_ids'])&created:raise ValueError('new objects require explicit parent anchor')
                        parents={child:parent for parent in roots[im].iter() for child in parent}
                        by={n.get('id'):n for n in roots[im].iter() if n.get('id')}
                        selected_parents={parents.get(by[t]) for t in op['target_ids']}
                        if len(selected_parents)!=1 or None in selected_parents:raise ValueError('parent anchor requires one common existing container')
                    elif value is not None and value not in objects|created:raise ValueError('insertion anchor outside scope')
                if op['method']=='bp_add':
                    try:fragment=ET.fromstring('<g>'+op['args'].get('svg','')+'</g>')
                    except ET.ParseError as exc:raise ValueError('invalid insertion fragment') from exc
                    nodes=list(fragment.iter())[1:];fresh=[n.get('id') for n in nodes]
                    if not fresh or any(not i for i in fresh) or len(set(fresh))!=len(fresh) or set(fresh)&(existing|created):
                        raise ValueError('new SVG IDs must be explicit and unique')
                    created.update(fresh)
                if op['method'] in ('sp_photo','sample_colors'):
                    location=op.get('source_location',p.get('source_location',{}))
                    if not isinstance(location,dict) or location.get('basis')!='original_semantic' or not isinstance(location.get('description'),str) or not location['description'].strip():raise ValueError('independent original semantic location required')
                    boxes=[op['args'].get('source_crop')] if op['method']=='sp_photo' else op['args'].get('regions')
                    if not isinstance(boxes,list) or not boxes:raise ValueError('original source requires literal boxes')
                    for box in boxes:
                        if not isinstance(box,list) or len(box)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in box) or min(box[2:])<=0:raise ValueError('original source requires literal finite xywh')
        else:raise ValueError('unsupported program route')
        p['read_only_references']=sorted(read_refs)
        seen[pid]=dict(p,_ancestors=ancestors);scope[pid]=objects;issue_sets[pid]=selected
    return issue_sets


def execute_programs(programs,issues,images,folder,prior_executed=None,*,capabilities=None):
    folder=Path(folder).resolve();folder.mkdir(parents=True,exist_ok=True)
    with (folder/'execution.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        from ..capabilities import freeze_policy,trace_context
        policy=freeze_policy(folder,capabilities)
        with trace_context(folder,policy,'repair_execution'):
            return _execute(programs,issues,images,folder,prior_executed,capabilities=policy)


def _rollback_paint_batch(state,images,paint_failures):
    from ..capabilities import trace_event
    state['paint_effect_batch_rollback']={'status':'rolled_back_to_input','failures':paint_failures,'discarded_images':deepcopy(state['images'])}
    state['images']={im:{k:v[k] for k in ('svg','png','revision','original')} for im,v in images.items()}
    state['aliases']={im:{} for im in images};state['results']={}
    for rec in state['rcd']:
        if rec['status'] in ('changed_unverified','executed_no_change'):
            rec.update(status_before_rollback=rec['status'],status='failed',rolled_back=True,after_revision=images[rec['image_id']]['revision'],error='paint-effect final audit failed; full batch rolled back to input')
            rec['final_scene_check']={'status':'unresolved','reason':'paint-effect full batch rollback'}
            if 'convergence' in rec:rec['convergence']['status']='rolled_back'
            if 'paint_effect_certificate' in rec:
                proof=rec['paint_effect_certificate'];proof['final_valid']=False
                if proof['status']!='invalidated':proof['status']='rolled_back'
    trace_event('common_runtime','paint_effect_batch_rollback','rolled_back_to_input',failures=paint_failures)


def _execute(programs,issues,images,folder,prior_executed=None,*,capabilities=None):
    from ..capabilities import normalize_capabilities,invoke,trace_event,capability_hash,set_trace_details
    policy=normalize_capabilities(capabilities)
    selected=validate_programs(programs,issues,images,prior_executed=prior_executed,capabilities=policy)
    signature=hashlib.sha256(json.dumps({'programs':programs,'issues':issues,'images':images,'capabilities':policy},sort_keys=True).encode()).hexdigest()
    path=folder/'state.json'
    if path.exists():
        state=json.loads(path.read_text())
        if state['signature']!=signature:raise ValueError('cannot resume a different execution plan')
        resume_failures=[]
        for im,data in state['images'].items():
            try:modified=digest(data['svg'])!=data['revision']
            except OSError:modified=True
            if modified:
                paint_ids=[p['id'] for p in programs if p['image_id']==im and paint_effect.required(p,selected[p['id']])]
                if not paint_ids:raise ValueError('checkpoint modified')
                resume_failures.extend({'program_id':pid,'error':'paint-effect checkpoint modified or missing on resume'} for pid in paint_ids)
        if resume_failures:
            for rec in state['rcd']:
                if rec['program_id'] in {f['program_id'] for f in resume_failures}:
                    rec.setdefault('paint_effect_certificate',{}).update(status='invalidated',final_valid=False,error='checkpoint modified or missing on resume')
            _rollback_paint_batch(state,images,resume_failures)
        if state.get('paint_effect_batch_rollback'):
            _atomic_json(path,state)
            result={k:state[k] for k in ('images','rcd','aliases')};result['visual_acceptance']='pending'
            _atomic_json(folder/'result.json',result)
            return result
    else:
        state={'signature':signature,'images':{im:{k:v[k] for k in ('svg','png','revision','original')} for im,v in images.items()},'aliases':{im:{} for im in images},'rcd':[],'results':{}}
    done={r['program_id']:r for r in state['rcd']}
    for record in prior_executed or []:
        pid=record.get('program_id') or record.get('id')
        if pid and pid not in done:done[pid]=record
    for index,p in enumerate(programs):
        pid=p['id'];im=p['image_id']
        if pid in done:continue
        current=state['images'][im]
        set_trace_details(program_id=pid,issue_ids=p['issue_ids'],before_revision=current['revision'],program_sha256=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest())
        record={'program_id':pid,'issue_ids':p['issue_ids'],'image_id':im,'phase':p['phase'],'route':p['route'],'before_revision':current['revision'],'after_revision':current['revision'],'target_ids':p['target_ids'],'rcd_predescription':p.get('rcd_predescription',''),'visual_acceptance':'pending','read_only_references':p.get('read_only_references',[]),'compiled_scope':deepcopy(p.get('compiled_scope')),'effective_target_ids':_execution_targets(p)}
        record['host_normalizations']=deepcopy(p.get('host_normalizations',[]))
        trigger=p.get('when');trigger_matched=True
        if trigger:
            actual=done[trigger['program']]['status'];trigger_matched=actual==trigger['status']
            record['trigger']={'program':trigger['program'],'expected_status':trigger['status'],'actual_status':actual,'matched':trigger_matched}
        if not trigger_matched:
            record.update(status='skipped_condition',reason='declared execution-status condition did not match')
        elif any(done[d]['status'] not in ('changed_unverified','executed_no_change') for d in p.get('depends_on',[]) if not trigger or d!=trigger['program']):
            record.update(status='blocked',error='dependency did not execute')
        else:
            try:
                source=Path(current['svg']).read_text()
                before=ET.fromstring(source);trial=deepcopy(before)
                paint_only=paint_effect.required(p,selected[pid])
                if paint_only and (digest(current['svg'])!=current['revision'] or not paint_effect.eligible(p,selected[pid],before,source)):
                    raise ValueError('current paint-effect predicate/source revision failed')
                if paint_only and any(_resolve_id(t,state['aliases'][im])!=t for t in p['target_ids']):
                    raise ValueError('current paint-effect target alias changed')
                local_results=deepcopy(state['results'])
                aliases=deepcopy(state['aliases'][im]);work=folder/f'program-{index:04d}';work.mkdir(exist_ok=True)
                rules=p.get('relations',[])
                initial=invoke('common_guard',_relation_report,before,rules,aliases) if rules else None
                if p['route']=='generated_python':
                    attempt=work/'sandbox'
                    if attempt.exists():
                        # Crash before transaction commit: preserve old attempt, execute in a fresh isolated folder.
                        n=1
                        while (work/f'sandbox-{n}').exists():n+=1
                        attempt=work/f'sandbox-{n}'
                    snapshot_ids=sorted({_resolve_id(t,aliases) for q in selected[pid] for t in q.get('target_ids',[])+q.get('neighbor_ids',[])}|{_resolve_id(t,aliases) for t in p.get('read_only_references',[])})
                    tp_snapshot=None
                    if policy['code_methods']:
                        tp_snapshot=invoke('code_intervention',measure_tight,trial,snapshot_ids)
                        tp_snapshot['revision']=current['revision']
                    result=invoke('common_runtime',run_code,p['source_code'],current['svg'],attempt,current_tp=tp_snapshot,capabilities=policy)
                    record['tool_receipt']=result
                    for invocation in result.get('library_invocations',[]):
                        trace_event(invocation['category'],invocation['method'],invocation['status'],**{k:v for k,v in invocation.items() if k not in ('category','method','status')})
                    if result.get('status')!='executed':raise ValueError(result.get('error','sandbox execution failed'))
                    trial=ET.fromstring(Path(result['svg']).read_text());assert_target_scope(before,trial,[_resolve_id(t,aliases) for t in p['target_ids']])
                    old_images={n.get('href') or n.get('{http://www.w3.org/1999/xlink}href') for n in before.iter() if n.tag.rsplit('}',1)[-1]=='image'}
                    if any((n.get('href') or n.get('{http://www.w3.org/1999/xlink}href')) not in old_images for n in trial.iter() if n.tag.rsplit('}',1)[-1]=='image'):
                        raise ValueError('generated raster insertion requires audited sp_photo route')
                    record['source_code_sha256']=hashlib.sha256(p['source_code'].encode()).hexdigest()
                else:
                    group=selected[pid]
                    issue={'id':pid,'category':group[0]['category'],'target_ids':_execution_targets(p),'neighbor_ids':list({t for q in group for t in q.get('neighbor_ids',[])}),'description':' / '.join(q.get('description','') for q in group),'original_evidence':' / '.join(str(q.get('original_evidence','')) for q in group)}
                    results=[];actual=[]
                    issue['relations']=rules
                    ops=p['args']['operations']
                    # Sampling/measurement are host read-only capabilities; all mutations share the trial transaction.
                    executable = [{'method':'bp_program','target_ids':_execution_targets(p),'args':{'operations':ops}}] if len(ops)>1 and all(op['method'] in MUTATIONS and not op.get('id') for op in ops) else ops
                    for op_index,op in enumerate(executable):
                        step=dict(op)
                        result,args,reports=invoke('code_intervention',_perform,trial,step,issue,images[im]['original'],work/f'op-{op_index}',aliases,local_results,trace_method=step['method'])
                        if op.get('id'):local_results[op['id']]=deepcopy(result)
                        results.append(result);actual.append(args)
                    result=results[0] if len(ops)==1 else {'operations':results};record['actual_parameters']=actual
                if paint_only:
                    paint_effect.prove_transition(p,selected[pid],before,trial,source)
                if any(q['category'] in ('E','F') for q in selected[pid]):
                    issue={'id':pid,'category':selected[pid][0]['category'],'target_ids':_execution_targets(p),'neighbor_ids':list({t for q in selected[pid] for t in q.get('neighbor_ids',[])}),'description':' / '.join(q.get('description','') for q in selected[pid]),'original_evidence':' / '.join(str(q.get('original_evidence','')) for q in selected[pid])}
                    record['convergence']=invoke('common_guard',converge,trial,p,issue,images[im]['original'],work,aliases,local_results,capabilities=policy,paint_effect=paint_only)
                validate(trial)
                if rules:
                    post=invoke('common_guard',_relation_report,trial,rules,aliases)
                    focus={_resolve_id(t,aliases) for t in _execution_targets(p)}
                    live={n.get('id') for n in trial.iter() if n.get('id')}
                    focus.update(descendants(trial,list(focus & live)))
                    target_rules=[r for r in rules if {_resolve_id(r['subject_id'],aliases),_resolve_id(r['object_id'],aliases)} & focus]
                    record['tp_check']=invoke('common_guard',_relation_report,trial,target_rules,aliases)
                    record['neighbor_check']=compare_reports(initial,post)
                    record['relation_check']=post
                    if record['neighbor_check']['new_alarm_ids'] or record['neighbor_check']['missing_relation_ids']:raise ValueError('new neighbor TP alarm; transaction rolled back')
                else:
                    record['tp_check']={'status':'not_assessed','reason':'no declared original-justified relations'}
                    record['neighbor_check']={'status':'not_assessed','reason':'no declared original-justified relations'}
                if paint_only:
                    paint_effect.prove_transition(p,selected[pid],before,trial,source)
                checkpoint,measurement=write_checkpoint(trial,folder/'checkpoints',index)
                if paint_only:
                    record['paint_effect_certificate']=paint_effect.certificate(p,selected[pid],current['svg'],checkpoint['svg'],current['revision'],checkpoint['revision'])
                checkpoint['original']=images[im]['original']
                record.update(status='changed_unverified' if ET.tostring(before)!=ET.tostring(trial) else 'executed_no_change',after_revision=checkpoint['revision'],measurement=measurement)
                state['images'][im]=checkpoint;state['aliases'][im]=aliases;local_results[pid]=result;state['results']=local_results
            except Exception as exc:
                record.update(status='failed',error=str(exc),rolled_back=True)
        trace_event('common_runtime','program_transaction',record['status'],program_id=pid,issue_ids=p['issue_ids'],before_revision=record['before_revision'],after_revision=record['after_revision'],program_sha256=hashlib.sha256(json.dumps(p,sort_keys=True).encode()).hexdigest())
        state['rcd'].append(record);done[pid]=record;_atomic_json(path,state)
    # Earlier convergence can be invalidated by later edits. Audit the final scene.
    paint_failures=[]
    for p in programs:
        rec=next(r for r in state['rcd'] if r['program_id']==p['id'])
        if rec['status'] not in ('changed_unverified','executed_no_change') or not any(q['category'] in ('E','F') for q in selected[p['id']]):continue
        audit=deepcopy(p);audit['convergence']['repairs']=[];audit['convergence']['max_iterations']=2
        try:
            final_image=state['images'][p['image_id']]
            paint_only=paint_effect.required(p,selected[p['id']])
            if paint_only:
                proof=rec['paint_effect_certificate']
                proof.update(paint_effect.audit(p,selected[p['id']],proof,final_image['svg'],final_image['revision']))
            final_root=ET.fromstring(Path(final_image['svg']).read_text())
            rec['final_scene_check']=invoke('common_guard',converge,final_root,audit,{},images[p['image_id']]['original'],folder/'final-audit',state['aliases'][p['image_id']],{},capabilities=policy,paint_effect=paint_only)
        except Exception as exc:
            rec['final_scene_check']={'status':'unresolved','error':str(exc)}
            rec['convergence']['status']='invalidated_by_later_edit'
            if paint_effect.required(p,selected[p['id']]):
                rec.setdefault('paint_effect_certificate',{}).update(status='invalidated',final_valid=False,error=str(exc))
                paint_failures.append({'program_id':p['id'],'error':str(exc)})
    if paint_failures:
        _rollback_paint_batch(state,images,paint_failures)
    _atomic_json(path,state)
    result={k:state[k] for k in ('images','rcd','aliases')};result['visual_acceptance']='pending'
    _atomic_json(folder/'result.json',result)
    return result
