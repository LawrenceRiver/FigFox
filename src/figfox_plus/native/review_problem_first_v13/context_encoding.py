"""Readable, reversible evidence encoding; never changes executor SVG files."""
from collections import Counter
from copy import deepcopy
import hashlib
import json
import re
from string import Formatter

from defusedxml import ElementTree as SafeXML
from defusedxml.common import DefusedXmlException

TAG = '$encoding'
VERSION = 'figfox-lossless-context-v1'
NUMBER = re.compile(r'[-+]?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?')
IDENTIFIER = re.compile(r'(.*?)(0|[1-9]\d*)')
INSTRUCTIONS = '''payload contains the COMPLETE original evidence, losslessly encoded, not a summary.
Expand $encoding wrappers before reading the original tables. integer_range is start+i*step for count entries. identifier_range prefixes each such integer with prefix. runs repeats each [value,count] pair; blocks concatenates its blocks in order. rows_as_columns transposes expanded columns back into count rows. record_columns makes each row a dictionary using keys, then expands any wrapper in that dictionary.
svg_templates reconstructs the exact SVG text: expand tables and order; each [table,row] in order selects templates[table], a string with automatic {} placeholders and escaped {{/}} literal braces; substitute the verbatim string parameters in tables[table][row], then concatenate fragments in order. No coordinates are rounded, simplified or removed. svg_d reads the d attribute of node in the same-message current_svg for source/revision; strip only when strip=true. @node:N is zero-based document order of SVG descendants, excluding the root. These references retain the original path data once in the complete SVG.
Keep all original/current images and whole-scene relationships in view. Input wrappers are read-only notation. Return ordinary JSON using the supplied output schema and original object IDs. Generated code must read the actual, unchanged INPUT_SVG; never write encoded input notation as an SVG or tool argument.'''


def json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON keys cannot be compacted losslessly')
        result[key] = value
    return result


def _reserved(value):
    if isinstance(value, dict):
        return TAG in value or any(_reserved(item) for item in value.values())
    return isinstance(value, list) and any(_reserved(item) for item in value)


def _range_blocks(values):
    blocks, literal, index = [], [], 0
    while index < len(values):
        match = IDENTIFIER.fullmatch(values[index]) if isinstance(values[index], str) else None
        length = 1
        prefix, kind = None, None
        if index + 1 < len(values) and type(values[index]) is int and type(values[index + 1]) is int:
            start, step = values[index], values[index + 1] - values[index]
            prefix, kind = '', 'integer_range'
        elif match and index + 1 < len(values) and isinstance(values[index + 1], str):
            following = IDENTIFIER.fullmatch(values[index + 1])
            if following and following[1] == match[1]:
                start, step = int(match[2]), int(following[2]) - int(match[2])
                prefix, kind = match[1], 'identifier_range'
        if kind:
            while index + length < len(values):
                item = values[index + length]; expected = start + length * step
                if kind == 'identifier_range': expected = prefix + str(expected)
                if type(item) is not type(expected) or item != expected: break
                length += 1
        if length >= 8:
            if literal:
                blocks.append(literal); literal = []
            block = {TAG: kind, 'start': start, 'step': step, 'count': length}
            if kind == 'identifier_range': block['prefix'] = prefix
            blocks.append(block)
            index += length
        else:
            literal.append(values[index]); index += 1
    if literal:
        blocks.append(literal)
    return {TAG: 'blocks', 'count': len(values), 'blocks': blocks}


PATH_ATTRIBUTE = re.compile(r'''(?<![\w:-])d\s*=\s*(["'])(.*?)\1''', re.DOTALL)


def _svg_fields(fragment, path_literals):
    if not path_literals:
        return [(number.start(), number.end()) for number in NUMBER.finditer(fragment)]
    fields, cursor = [], 0
    for path in PATH_ATTRIBUTE.finditer(fragment):
        start, end = path.span(2)
        fields.extend((cursor + number.start(), cursor + number.end())
                      for number in NUMBER.finditer(fragment[cursor:start]))
        if end > start: fields.append((start, end))
        cursor = end
    fields.extend((cursor + number.start(), cursor + number.end())
                  for number in NUMBER.finditer(fragment[cursor:]))
    return fields


def _svg_templates(svg, *, path_literals=False):
    templates, tables, indices, order = [], [], {}, []
    for fragment in re.findall(r'<[^>]*>|[^<]+|<', svg):
        pieces, parameters, end = [], [], 0
        for start, stop in _svg_fields(fragment, path_literals):
            pieces.extend([fragment[end:start].replace('{', '{{').replace('}', '}}'), '{}'])
            parameters.append(fragment[start:stop]); end = stop
        pieces.append(fragment[end:].replace('{', '{{').replace('}', '}}'))
        template = ''.join(pieces)
        if template not in indices:
            indices[template] = len(templates); templates.append(template); tables.append([])
        index = indices[template]
        order.append([index, len(tables[index])]); tables[index].append(parameters)
    return {TAG: 'svg_templates', 'templates': templates,
            'tables': [_pack(rows) for rows in tables], 'order': _pack(order)}


def _shape_blocks(values, ordinary):
    def shape(item):
        if isinstance(item, dict): return ('record', tuple(item))
        if isinstance(item, list): return ('row', len(item))
        return ('scalar', type(item))
    ranges, start = [], 0
    for index in range(1, len(values)):
        if shape(values[index]) != shape(values[start]):
            ranges.append((start, index)); start = index
    ranges.append((start, len(values)))
    if len(ranges) < 2 or not any(end-start >= 8 for start, end in ranges):
        return None
    # A literal outlier must not prevent its neighboring reference records from
    # sharing columns. Blocks retain every value and its original position.
    return {TAG: 'blocks', 'count': len(values),
            'blocks': [_pack(values[start:end]) if end-start >= 8 else ordinary[start:end]
                       for start, end in ranges]}


def _pack(value):
    if isinstance(value, dict):
        return {key: _pack(item) for key, item in value.items()}
    if isinstance(value, str) and len(value) > 20_000 and '<svg' in value[:1024] and '</svg' in value[-128:]:
        # Whole path parameters avoid quoting every coordinate separately. Both
        # candidates use the existing notation and restore the exact SVG text.
        candidate = min((_svg_templates(value), _svg_templates(value, path_literals=True)),
                        key=lambda item: len(json_text(item)))
        return candidate if len(json_text(candidate)) < len(json_text(value)) else value
    if not isinstance(value, list):
        return value
    ordinary = [_pack(item) for item in value]
    candidates = [ordinary]
    if len(value) >= 8:
        candidates.append(_range_blocks(value))
        blocks = _shape_blocks(value, ordinary)
        if blocks is not None: candidates.append(blocks)
        if all(isinstance(item, list) and len(item) == len(value[0]) for item in value):
            candidates.append({TAG: 'rows_as_columns', 'count': len(value),
                               'columns': [_pack(list(column)) for column in zip(*value)]})
        if all(isinstance(item, dict) and tuple(item) == tuple(value[0]) for item in value):
            keys = list(value[0])
            candidates.append({TAG: 'record_columns', 'count': len(value), 'keys': keys,
                               'columns': [_pack([item[key] for item in value]) for key in keys]})
        runs, previous = [], None
        for item, packed in zip(value, ordinary):
            key = json_text(item)  # bool/int/float and negative zero remain distinct.
            if runs and key == previous:
                runs[-1][1] += 1
            else:
                runs.append([packed, 1]); previous = key
        candidates.append({TAG: 'runs', 'count': len(value), 'runs': runs})
        if all(type(item) is int for item in value):
            start, step = value[0], value[1] - value[0]
            if all(item == start + index * step for index, item in enumerate(value)):
                candidates.append({TAG: 'integer_range', 'start': start, 'step': step, 'count': len(value)})
    return min(candidates, key=lambda item: len(json_text(item)))


def _svg_sources(payloads):
    sources = {}
    for value in payloads.values():
        root = value.get('payload') if is_packet(value) else value
        if not isinstance(root, dict) or not isinstance(root.get('image_id'), str) or 'current_svg' not in root:
            continue
        svg = _unpack(root['current_svg'], {})
        if not isinstance(svg, str):
            continue
        try:
            tree = SafeXML.fromstring(svg, forbid_dtd=True)
        except (SafeXML.ParseError, DefusedXmlException):
            continue
        nodes = list(tree.iter())[1:]
        if any(node.tag.rsplit('}', 1)[-1] in {'script', 'foreignObject', 'animate', 'animateMotion', 'animateTransform', 'set'} for node in nodes):
            continue  # Geometry measurement removes these nodes, changing @node indices.
        counts = Counter(node.get('id') for node in nodes if node.get('id'))
        lookup = {node.get('id') or '@node:' + str(index): node.attrib['d']
                  for index, node in enumerate(nodes) if 'd' in node.attrib and counts.get(node.get('id'), 0) <= 1}
        key = (root['image_id'], root.get('revision'))
        if key in sources and sources[key] != lookup:
            sources[key] = None
        elif key not in sources:
            sources[key] = lookup
    return sources


def _alias_paths(payload, sources):
    out = deepcopy(payload)
    fact_sets = out.get('current_line_facts', {})
    if not isinstance(fact_sets, dict):
        return out
    for image_id, facts in fact_sets.items():
        if not isinstance(facts, dict):
            continue
        revision = facts.get('current_revision')
        source = sources.get((image_id, revision))
        objects = facts.get('objects', {})
        if not source or not isinstance(objects, dict):
            continue
        for table in objects.get('tables', []):
            if not isinstance(table, dict):
                continue
            columns = table['columns']
            if 'object_id' not in columns or 'path_data' not in columns:
                continue
            node_index, path_index = columns.index('object_id'), columns.index('path_data')
            for row in table['rows']:
                node, value = row[node_index], row[path_index]
                original = source.get(node)
                if isinstance(value, str) and isinstance(original, str) and value in (original, original.strip()):
                    row[path_index] = {TAG: 'svg_d', 'source': image_id, 'revision': revision,
                                       'node': node, 'strip': value != original}
    return out


def _count(value):
    if type(value) is not int or not 0 <= value <= 2_000_000:
        raise ValueError('invalid evidence vector length')
    return value


def _format(template, parameters):
    output, index = [], 0
    for literal, field, spec, conversion in Formatter().parse(template):
        output.append(literal)
        if field is not None:
            if field != '' or spec or conversion or index >= len(parameters) or not isinstance(parameters[index], str):
                raise ValueError('invalid SVG text template')
            output.append(parameters[index]); index += 1
    if index != len(parameters):
        raise ValueError('invalid SVG template parameter count')
    return ''.join(output)


def _unpack(value, sources, budget=None):
    budget = [2_000_000, 48 * 1024 * 1024] if budget is None else budget
    budget[0] -= 1
    if isinstance(value, str):
        budget[1] -= len(value.encode('utf-8'))
    if min(budget) < 0:
        raise ValueError('evidence expansion limit')
    if isinstance(value, list):
        return [_unpack(item, sources, budget) for item in value]
    if not isinstance(value, dict):
        return value
    kind = value.get(TAG)
    if kind is None:
        return {key: _unpack(item, sources, budget) for key, item in value.items()}
    if kind == 'svg_d':
        result = sources[(value['source'], value['revision'])][value['node']]
        result = result.strip() if value['strip'] else result
        budget[1] -= len(result.encode('utf-8'))
        if budget[1] < 0: raise ValueError('evidence expansion limit')
        return result
    if kind in ('identifier_range', 'integer_range'):
        count = _count(value['count']); budget[0] -= count
        if type(value['start']) is not int or type(value['step']) is not int:
            raise ValueError('invalid evidence range')
        prefix = value['prefix'] if kind == 'identifier_range' else ''
        if not isinstance(prefix, str): raise ValueError('invalid evidence identifier prefix')
        width = max(len(str(value['start'])), len(str(value['start'] + max(0, count-1) * value['step'])))
        budget[1] -= count * (len(prefix.encode('utf-8')) + width)
        if budget[1] < 0: raise ValueError('evidence expansion limit')
        if budget[0] < 0: raise ValueError('evidence expansion limit')
        numbers = [value['start'] + index * value['step'] for index in range(count)]
        return [value['prefix'] + str(number) for number in numbers] if kind == 'identifier_range' else numbers
    if kind == 'runs':
        result = []
        for item, repetitions in value['runs']:
            repetitions = _count(repetitions)
            plain = _unpack(item, sources, budget)
            size = len(json_text(plain).encode('utf-8'))
            budget[0] -= repetitions; budget[1] -= size * max(0, repetitions - 1)
            if min(budget) < 0: raise ValueError('evidence expansion limit')
            result.extend(deepcopy(plain) for _ in range(repetitions))
    elif kind == 'blocks':
        result = [item for block in value['blocks'] for item in _unpack(block, sources, budget)]
    elif kind in ('rows_as_columns', 'record_columns'):
        count = _count(value['count'])
        budget[0] -= count
        if budget[0] < 0: raise ValueError('evidence expansion limit')
        columns = [_unpack(column, sources, budget) for column in value['columns']]
        if any(not isinstance(column, list) for column in columns): raise ValueError('invalid evidence column')
        if any(len(column) != count for column in columns): raise ValueError('invalid evidence column length')
        result = [list(row) for row in zip(*columns)] if columns else [[] for _ in range(count)]
        if kind == 'record_columns':
            if len(value['keys']) != len(columns) or len(set(value['keys'])) != len(columns):
                raise ValueError('invalid evidence record keys')
            result = [_unpack(dict(zip(value['keys'], row)), sources, budget) for row in result]
    elif kind == 'svg_templates':
        tables = [_unpack(table, sources, budget) for table in value['tables']]
        order = _unpack(value['order'], sources, budget)
        fragments = []
        for index, row in order:
            if (type(index) is not int or type(row) is not int or
                not 0 <= index < len(tables) or not 0 <= row < len(tables[index])):
                raise ValueError('invalid SVG template reference')
            fragment = _format(value['templates'][index], tables[index][row])
            budget[1] -= len(fragment.encode('utf-8'))
            if budget[1] < 0: raise ValueError('evidence expansion limit')
            fragments.append(fragment)
        return ''.join(fragments)
    else:
        raise ValueError('unknown evidence encoding')
    if len(result) != _count(value['count']): raise ValueError('invalid evidence record count')
    return result


def is_packet(value):
    return isinstance(value, dict) and value.get('encoding') == VERSION and set(value) == {'encoding', 'instructions', 'original_sha256', 'payload'}


def _payloads(content):
    result = {}
    for index, part in enumerate(content):
        if part.get('type') != 'text': continue
        try:
            value = json.loads(part.get('text', ''), object_pairs_hook=unique_object)
            if isinstance(value, (dict, list)):
                json_text(value)
                result[index] = value
        except (ValueError, TypeError):
            continue
    return result


def _restore(packet, sources):
    plain = _unpack(packet['payload'], sources)
    if hashlib.sha256(json_text(plain).encode('utf-8')).hexdigest() != packet['original_sha256']:
        raise ValueError('evidence restoration checksum mismatch')
    return plain


def restore_content(content):
    result = deepcopy(content); payloads = _payloads(content); sources = _svg_sources(payloads)
    for index, payload in payloads.items():
        if is_packet(payload):
            result[index]['text'] = json_text(_restore(payload, sources))
    return result


def compact_content(content, *, structural=False):
    result = deepcopy(content); payloads = _payloads(content); reductions = []
    sources = _svg_sources(payloads) if structural or any(is_packet(p) for p in payloads.values()) else {}
    for index, payload in payloads.items():
        original = content[index]['text']; compact = json_text(payload)
        if is_packet(payload):
            plain = _restore(payload, sources)
            reductions.append({'field': 'lossless_evidence_encoding', 'carried_forward': True,
                               'roundtrip_verified': True, 'original_sha256': payload['original_sha256'],
                               'decoded_bytes': len(json_text(plain).encode('utf-8'))})
            continue  # Keep an already encoded turn byte-for-byte for cache identity.
        if structural and isinstance(payload, dict) and len(compact.encode('utf-8')) >= 65536 and not _reserved(payload):
            packed = _pack(_alias_paths(payload, sources))
            packet = {'encoding': VERSION, 'instructions': INSTRUCTIONS,
                      'original_sha256': hashlib.sha256(compact.encode('utf-8')).hexdigest(), 'payload': packed}
            candidate = json_text(packet)
            if len(candidate.encode('utf-8')) < len(compact.encode('utf-8')) * 0.8:
                restored = _restore(packet, sources)
                if json_text(restored) != compact: raise ValueError('evidence roundtrip changed data')
                compact = candidate
                reductions.append({'field': 'lossless_evidence_encoding', 'roundtrip_verified': True,
                                   'original_sha256': packet['original_sha256'],
                                   'decoded_bytes': len(json_text(restored).encode('utf-8')),
                                   'bytes_saved': len(original.encode('utf-8')) - len(candidate.encode('utf-8'))})
        saved = len(original.encode('utf-8')) - len(compact.encode('utf-8'))
        if saved > 0:
            result[index]['text'] = compact
            if not is_packet(json.loads(compact)):
                reductions.append({'field': 'user_json_formatting', 'bytes_saved': saved,
                                   'all_fields_and_values_preserved': True})
    return result, reductions
