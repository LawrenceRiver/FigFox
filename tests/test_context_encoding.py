import copy
import hashlib
import json

import pytest

from figfox_plus.native.review_problem_first_v13.context_budget import budget_request
from figfox_plus.native.review_problem_first_v13.context_tables import model_line_facts


def dense_request(count=512):
    paths, records = [], []
    style = {'fill': 'rgb(190, 194, 198)', 'stroke': 'rgb(190, 194, 198)',
             'opacity': '0.992157', 'stroke_width': '1px'}
    for index in range(count):
        x, y = index % 128, index // 128
        d = f'M {x}.5 {y} L {x}.5 {y+1} L {x}.5 {y} Z'
        paths.append(f'<path fill="rgb(190,194,198)" stroke="rgb(190,194,198)" opacity="0.9921568627450981" d="{d} " />')
        records.append({'object_id': f'@node:{index+1}', 'tag': 'path', 'measurement_status': 'unresolved',
                        'markers': {'start': None, 'mid': None, 'end': None}, 'world_start': None,
                        'world_end': None, 'style': style, 'arrow_semantics_confirmed': False,
                        'path_data': d, 'reason': 'closed_contour'})
    svg = '<svg xmlns="http://www.w3.org/2000/svg"><g desc="Created with imagetracer.js">' + ''.join(paths) + '</g></svg>'
    facts = {'current_revision': 'rev-1', 'objects': records, 'relation_candidates': [],
             'unsupported': [{'object_id': r['object_id'], 'reason': r['reason']} for r in records]}
    data = {'current_line_facts': {'dense': model_line_facts(facts)},
            'typed_values': {'bools': [True]*16, 'ints': [1]*16, 'floats': [1.0]*16,
                             'negative_zero': [-0.0]*16, 'nulls': [None]*16},
            'method_pack': {'sources': {'helper': {'code': 'def helper(x): return x\n'}}}}
    parts = [{'type': 'text', 'text': json.dumps(data, ensure_ascii=False)},
             {'type': 'text', 'text': json.dumps({'image_id': 'dense', 'revision': 'rev-1', 'current_svg': svg})},
             {'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,unchanged', 'detail': 'original'}}]
    return {'model': 'deepseek-flash', 'max_tokens': 393216,
            'messages': [{'role': 'system', 'content': 'Keep the original whole-image workflow.'},
                         {'role': 'user', 'content': parts},
                         {'role': 'assistant', 'content': '', 'reasoning_content': '完整保留历史推理',
                          'tool_calls': [{'id': 'call-1', 'type': 'function', 'function': {'name': 'review', 'arguments': '{}'}}]},
                         {'role': 'tool', 'tool_call_id': 'call-1', 'content': '{"issues":[]}'},
                         {'role': 'user', 'content': 'Keep the original repair instructions.'}],
            'tools': [{'type': 'function', 'function': {'name': 'review', 'parameters': {'type': 'object'}}}]}


def semantic_digest(request):
    result = copy.deepcopy(request)
    for message in result['messages']:
        if message.get('role') != 'user' or not isinstance(message.get('content'), list):
            continue
        for part in message['content']:
            if part.get('type') == 'text':
                try:
                    value = json.loads(part['text'])
                except ValueError:
                    continue
                part['text'] = json.dumps(value, ensure_ascii=False, separators=(',', ':'))
    canonical = json.dumps(result, ensure_ascii=False, separators=(',', ':'), sort_keys=True)
    return hashlib.sha256(canonical.encode('utf-8')).hexdigest()


def restored(request):
    from figfox_plus.native.review_problem_first_v13.context_encoding import restore_content
    result = copy.deepcopy(request)
    for message in result['messages']:
        if message.get('role') == 'user' and isinstance(message.get('content'), list):
            message['content'] = restore_content(message['content'])
    return result


def test_dense_request_shrinks_without_losing_paths_facts_types_or_history():
    request = dense_request(); original = copy.deepcopy(request)
    bounded, audit = budget_request(request, context_tokens=1000)
    # This fails on the old formatting-only protection before any decoder import.
    assert audit['after']['input_token_upper_bound'] < audit['before']['input_token_upper_bound'] * 0.55
    assert semantic_digest(restored(bounded)) == semantic_digest(original)
    assert request == original and bounded['max_tokens'] == original['max_tokens']
    assert bounded['tools'] == original['tools']
    assert bounded['messages'][0] == original['messages'][0]
    assert bounded['messages'][2:] == original['messages'][2:]
    assert bounded['messages'][1]['content'][2] == original['messages'][1]['content'][2]
    assert not audit['semantic_fields_removed']


def test_normal_request_keeps_original_input_format():
    request = dense_request(8)
    bounded, audit = budget_request(request)
    assert bounded == request and not audit['reductions']


def test_encoded_transport_is_idempotent_and_reuses_complete_reply(tmp_path, monkeypatch):
    from figfox_plus.native.review_problem_first_v13.transport import send
    request = dense_request(2048)
    monkeypatch.delenv('FIGFOX_COST_LIMIT_USD', raising=False)
    monkeypatch.delenv('FIGFOX_COST_BUDGET_FILE', raising=False)
    sent = []
    class Response:
        headers = {'Content-Type': 'application/json'}
        def __enter__(self): return self
        def __exit__(self, *args): return False
        def read(self):
            return json.dumps({'choices': [{'message': {'role': 'assistant', 'content': '{}'}, 'finish_reason': 'stop'}],
                               'usage': {'prompt_tokens': 1000, 'completion_tokens': 1000}}).encode()
    def http(req, timeout):
        sent.append(json.loads(req.data)); return Response()
    first = send(request['messages'], request['tools'], tmp_path/'review', send_http=http)
    second = send(request['messages'], request['tools'], tmp_path/'review', send_http=http)
    assert first == second and len(sent) == 1
    assert sent[0]['max_tokens'] == 393216
    bounded, _ = budget_request(sent[0]); assert bounded == sent[0]
    actual = restored(sent[0])
    assert semantic_digest({'messages': actual['messages'], 'tools': actual['tools']}) == semantic_digest(
        {'messages': request['messages'], 'tools': request['tools']})


def test_revision_mismatch_does_not_create_false_aliases():
    request = dense_request()
    part = request['messages'][1]['content'][1]
    source = json.loads(part['text']); source['revision'] = 'other-revision'
    part['text'] = json.dumps(source)
    bounded, _ = budget_request(request, context_tokens=1000)
    assert semantic_digest(restored(bounded)) == semantic_digest(request)
    assert 'svg_d' not in json.dumps(json.loads(bounded['messages'][1]['content'][0]['text'])['payload'])


def test_one_literal_path_retains_neighbors_and_context_savings():
    request = dense_request(2048)
    part = request['messages'][1]['content'][0]
    facts = json.loads(part['text'])
    table = facts['current_line_facts']['dense']['objects']['tables'][0]
    # This independently measured path intentionally differs from the SVG.
    # Preserve it literally without expanding thousands of valid neighbors.
    table['rows'][1024][table['columns'].index('path_data')] = 'M -0.0 +.5 L 1e-7 2.0000'
    part['text'] = json.dumps(facts, ensure_ascii=False)
    bounded, audit = budget_request(request, context_tokens=1000)
    assert len(bounded['messages'][1]['content'][0]['text']) < len(part['text']) * 0.2
    assert semantic_digest(restored(bounded)) == semantic_digest(request)
    assert bounded['messages'][2:] == request['messages'][2:]
    assert bounded['messages'][1]['content'][2] == request['messages'][1]['content'][2]
    assert bounded['max_tokens'] == 393216 and not audit['semantic_fields_removed']


def test_sparse_record_indices_preserve_order_and_scalar_types():
    from figfox_plus.native.review_problem_first_v13.context_encoding import _pack, _unpack, json_text
    values = list(range(1024)) + [None, True, 1.0, -0.0] + list(range(2048, 3072))
    encoded = _pack(values)
    assert len(json_text(encoded)) < 500
    assert json_text(_unpack(encoded, {})) == json_text(values)


@pytest.mark.parametrize('unsafe_source', ['duplicate_ids', 'active_nodes'])
def test_ambiguous_svg_sources_keep_literal_path_data(unsafe_source):
    request = dense_request()
    parts = request['messages'][1]['content']
    source = json.loads(parts[1]['text'])
    if unsafe_source == 'active_nodes':
        source['current_svg'] = source['current_svg'].replace('<g ', '<script/> <g ', 1)
    else:
        facts = json.loads(parts[0]['text'])
        table = facts['current_line_facts']['dense']['objects']['tables'][0]
        column = table['columns'].index('object_id')
        for row in table['rows']: row[column] = 'duplicate'
        parts[0]['text'] = json.dumps(facts)
        source['current_svg'] = source['current_svg'].replace('</svg>',
            '<path id="duplicate" d="M 0.5 0 L 0.5 1 L 0.5 0 Z"/>'
            '<path id="duplicate" d="M9 9 L10 10"/></svg>')
    parts[1]['text'] = json.dumps(source)
    bounded, _ = budget_request(request, context_tokens=1000)
    assert semantic_digest(restored(bounded)) == semantic_digest(request)
    assert 'svg_d' not in json.dumps(json.loads(bounded['messages'][1]['content'][0]['text'])['payload'])


def test_compaction_failure_preserves_message_and_does_not_block(monkeypatch):
    def failed(*args, **kwargs): raise ValueError('injected verification failure')
    monkeypatch.setattr('figfox_plus.native.review_problem_first_v13.context_budget.compact_content', failed)
    request = dense_request()
    bounded, audit = budget_request(request, context_tokens=1000)
    assert bounded == request and audit['status'] == 'ready'
    assert audit['reductions'][0]['original_message_preserved']


def test_corrupt_encoding_is_preserved_and_expansion_is_bounded():
    from figfox_plus.native.review_problem_first_v13.context_encoding import VERSION, _unpack
    request = dense_request()
    request['messages'][1]['content'][0]['text'] = json.dumps({
        'encoding': VERSION, 'instructions': '', 'original_sha256': 'wrong',
        'payload': {'$encoding': 'identifier_range', 'prefix': 'x'*1000, 'start': 0, 'step': 1, 'count': 2_000_000}})
    bounded, audit = budget_request(request, context_tokens=1)
    assert bounded == request and audit['status'] == 'ready'
    assert audit['reductions'][0]['original_message_preserved']
    with pytest.raises(ValueError, match='expansion limit'):
        _unpack(json.loads(request['messages'][1]['content'][0]['text'])['payload'], {})


def test_svg_markup_and_precision_restore_exactly():
    request = dense_request()
    part = request['messages'][1]['content'][1]; data = json.loads(part['text'])
    data['current_svg'] = data['current_svg'].replace('</svg>',
        '<text><![CDATA[中文 {literal} < 4.5 & 1e-7]]></text><path id="precise" d="M -0.0 +.5 L 1e-7 2.0000"/></svg>')
    part['text'] = json.dumps(data, ensure_ascii=False)
    bounded, _ = budget_request(request, context_tokens=1000)
    output = restored(bounded)
    assert semantic_digest(output) == semantic_digest(request)
    assert json.loads(output['messages'][1]['content'][1]['text'])['current_svg'] == data['current_svg']


@pytest.mark.parametrize('quote', ['"', "'"])
def test_long_path_parameters_remain_verbatim_in_existing_svg_notation(quote):
    from figfox_plus.native.review_problem_first_v13.context_encoding import _svg_templates, _unpack
    path = 'M -0.0 +.5 ' + ' '.join(f'C {i}.0000 {i+1}e-7 {i+2}.5 {i+3} {i+4} {i+5}' for i in range(32)) + ' Z'
    svg = f'<svg xmlns="http://www.w3.org/2000/svg"><path id="p-12" stroke-width="1.5000" d={quote}{path}{quote}/></svg>'
    packed = _svg_templates(svg, path_literals=True)
    assert _unpack(packed, {}) == svg
    rows = [row for table in packed['tables'] for row in _unpack(table, {})]
    assert any(path in row for row in rows)
    assert any('1.5000' in row for row in rows)


def test_path_literal_templates_preserve_empty_attributes_and_literal_braces():
    from figfox_plus.native.review_problem_first_v13.context_encoding import _svg_templates, _unpack
    svg = '<svg><path d="" data-d="4.5000"/><text dx="1.000" desc="{literal}">1e-7</text><path d="M 0 1\nL 2 3 Z"/></svg>'
    assert _unpack(_svg_templates(svg, path_literals=True), {}) == svg


def test_reserved_codec_keys_are_kept_as_literal_data():
    request = dense_request()
    part = request['messages'][1]['content'][0]; data = json.loads(part['text'])
    data['literal'] = {'$encoding': 'identifier_range', 'start': 3, 'count': 10}
    part['text'] = json.dumps(data)
    bounded, _ = budget_request(request, context_tokens=1000)
    assert json.loads(bounded['messages'][1]['content'][0]['text']) == data
