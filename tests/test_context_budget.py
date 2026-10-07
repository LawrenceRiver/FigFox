import copy
import json

import pytest

from figfox_plus.native.review_problem_first_v13.context_budget import budget_request, ContextCapacityError, SAFETY_TOKENS
from figfox_plus.native.review_problem_first_v13.context_encoding import restore_content
from figfox_plus.native.review_problem_first_v13.transport import send


def test_explicit_cost_pressure_rejects_full_request_without_dropping_evidence():
    import hashlib
    code = 'def helper(x): return x\n' * 3000
    request = body({'method_pack': {'helpers': {'f': {'callable': 'pkg.helper', 'signature': '(x)'}},
                                  'sources': {'pkg.helper': {'code': code, 'sha256': hashlib.sha256(code.encode()).hexdigest()}}},
                    'current_diagnostics': ['derived'] * 20000,
                    'current_svg': '<svg><rect id="frame"/></svg>',
                    'current_tp': {'objects': {'frame': {'geometry_bbox': [0, 0, 10, 10]}}}},
                   images=['data:image/png;base64,original'])
    request['messages'].extend([{'role': 'user', 'content': [{'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,crop'}}]},
                                {'role': 'assistant', 'content': '', 'reasoning_content': 'keep me'},
                                {'role': 'user', 'content': 'keep final instruction'}])
    original = copy.deepcopy(request)
    bounded, audit = budget_request(request, input_token_limit=15000)
    assert audit['status'] == 'blocked_before_request' and audit['violations'] == ['input cost budget']
    assert bounded['max_tokens'] == 131072 and request == original
    parts = bounded['messages'][0]['content']
    assert parts[1] == request['messages'][0]['content'][1]
    payload = json.loads(restore_content(parts)[0]['text'])
    assert payload['current_svg'] == '<svg><rect id="frame"/></svg>'
    original_payload = json.loads(original['messages'][0]['content'][0]['text'])
    assert payload['method_pack']['helpers'] == original_payload['method_pack']['helpers']
    assert payload['method_pack']['sources']['pkg.helper']['sha256'] == hashlib.sha256(code.encode()).hexdigest()
    assert payload['method_pack']['sources']['pkg.helper']['code'] == code
    assert payload == original_payload
    assert bounded['messages'][1:] == request['messages'][1:]


def body(payload, *, images=()):
    return {'model': 'deepseek-flash', 'max_tokens': 131072,
            'messages': [{'role': 'user', 'content': [
                {'type': 'text', 'text': json.dumps(payload)},
                *[{'type': 'image_url', 'image_url': {'url': value, 'detail': 'original'}} for value in images],
            ]}]}


def test_dense_context_keeps_all_diagnostics_svg_methods_and_visual_inputs():
    request = body({'current_diagnostics': {'relation_candidates': ['derived hint'] * 150000},
                    'current_svg': '<svg><path id="curve" d="M0 0 L20 30"/></svg>',
                    'current_tp': {'objects': {'curve': {'geometry_bbox': {'left': 0, 'top': 0, 'right': 20, 'bottom': 30}}}}},
                   images=['data:image/png;base64,unchanged'])
    request['tools'] = [{'type': 'function', 'function': {'name': 'execute_review_program', 'parameters': {'type': 'object'}}}]
    original = copy.deepcopy(request)
    bounded, audit = budget_request(request)
    assert request == original
    assert audit['before']['input_token_upper_bound'] > audit['context_tokens']
    assert audit['status'] == 'ready'
    content = bounded['messages'][0]['content']
    view = json.loads(restore_content(content)[0]['text'])
    assert view['current_svg'] == json.loads(original['messages'][0]['content'][0]['text'])['current_svg']
    assert content[1] == original['messages'][0]['content'][1]
    assert bounded['tools'] == original['tools']
    assert view == json.loads(original['messages'][0]['content'][0]['text'])
    assert audit['after']['input_token_upper_bound'] < audit['before']['input_token_upper_bound']
    assert not audit['semantic_fields_removed']


def test_conservative_byte_estimate_does_not_block_or_shorten_a_request(tmp_path, monkeypatch):
    messages = body({'current_svg': '<svg><desc>' + 'x' * 1_200_000 + '</desc></svg>'})['messages']

    monkeypatch.delenv('FIGFOX_COST_LIMIT_USD', raising=False)
    monkeypatch.delenv('FIGFOX_COST_BUDGET_FILE', raising=False)
    sent = []
    class Response:
        headers = {'Content-Type':'application/json'}
        def __enter__(self):return self
        def __exit__(self,*args):return False
        def read(self):return json.dumps({'choices':[{'message':{'role':'assistant','content':'{}'},'finish_reason':'stop'}],
            'usage':{'prompt_tokens':1000,'completion_tokens':1000}}).encode()
    def http(request, timeout):
        sent.append(json.loads(request.data));return Response()
    send(messages, [], tmp_path / 'review', send_http=http)
    assert len(sent) == 1 and sent[0]['max_tokens'] == 393216
    assert json.loads(sent[0]['messages'][0]['content'][0]['text']) == json.loads(messages[0]['content'][0]['text'])
    audits = list((tmp_path / 'review').rglob('context-budget.json'))
    assert len(audits) == 1
    audit = json.loads(audits[0].read_text(encoding='utf-8'))
    assert audit['status'] == 'ready' and audit['warnings']


def test_visual_base64_is_not_counted_as_text_tokens_and_continuation_is_preserved():
    request = body({'current_diagnostics': ['optional'] * 130000},
                   images=['data:image/png;base64,' + 'A' * 2_000_000])
    previous = {'role': 'assistant', 'content': '',
                'reasoning_content': 'prior reasoning must remain intact',
                'tool_calls': [{'id': 'call-1', 'type': 'function', 'function': {'name': 'f', 'arguments': '{}'}}]}
    request['messages'].extend([previous, {'role': 'tool', 'tool_call_id': 'call-1', 'content': '{}'}])
    bounded, audit = budget_request(request)
    assert audit['status'] == 'ready' and audit['after']['image_token_reserve'] == 1024
    assert bounded['messages'][1:] == request['messages'][1:]
    assert json.loads(restore_content(bounded['messages'][0]['content'])[0]['text']) == json.loads(request['messages'][0]['content'][0]['text'])


def test_wire_json_escaping_does_not_falsely_block_a_fitting_svg():
    paths = ''.join(f'<path id="p{i}" d="M0 0 L20 30"/>' for i in range(2000))
    request = body({'current_svg': '<svg>' + paths + '</svg>'})
    actual_text_bytes = len(request['messages'][0]['content'][0]['text'].encode('utf-8'))
    limit = actual_text_bytes + request['max_tokens'] + SAFETY_TOKENS + 4096
    bounded, audit = budget_request(request, context_tokens=limit)
    assert audit['status'] == 'ready' and not audit['reductions']
    assert bounded == request


def test_opaque_tracing_paths_remain_in_the_model_view_alongside_its_arrow():
    tracing = ''.join('<path d="' + 'M0 0 L1 1 ' * 100 + '"/>' for _ in range(1500))
    svg = ('<svg><g id="asset"><g desc="Created with imagetracer.js version 1.2.6">'
           + tracing + '</g></g><path id="arrow" d="M10 20 L30 40"/></svg>')
    request = body({'current_svg': svg})
    bounded, audit = budget_request(request)
    assert audit['status'] == 'ready' and request['messages'][0]['content'][0]['text'] == json.dumps({'current_svg': svg})
    view = json.loads(restore_content(bounded['messages'][0]['content'])[0]['text'])
    assert 'id="asset"' in view['current_svg']
    assert 'id="arrow"' in view['current_svg'] and 'M10 20 L30 40' in view['current_svg']
    assert view['current_svg'] == svg
    assert audit['after']['input_token_upper_bound'] < audit['before']['input_token_upper_bound']


@pytest.mark.parametrize('kind', ['body', 'image_count'])
def test_provider_limits_are_checked_without_dropping_images(kind):
    request = body({}, images=['data:image/png;base64,' + 'A' * 1000] if kind == 'body' else ['data:image/png;base64,A'] * 601)
    bounded, audit = budget_request(request, body_bytes=500 if kind == 'body' else 48 * 1024 * 1024)
    assert audit['status'] == 'blocked_before_request'
    assert bounded['messages'] == request['messages']


@pytest.mark.parametrize('text', ['{"a":1,"a":2}', '{"a":NaN}'])
def test_ambiguous_json_is_retained_verbatim_under_estimated_pressure(text):
    request = body({})
    request['messages'][0]['content'][0]['text'] = text
    bounded, audit = budget_request(request, context_tokens=1)
    assert bounded == request and audit['status'] == 'ready' and audit['warnings']


def test_inline_file_images_are_visual_inputs_and_not_counted_as_base64_text():
    request = body({})
    part = {'type':'file','file_data':'data:image/png;base64,' + 'A'*2_000_000}
    request['messages'][0]['content'].append(part)
    bounded, audit = budget_request(request)
    assert audit['after']['image_count'] == 1 and audit['after']['text_token_upper_bound'] < 10000
    assert bounded == request


def test_known_image_limit_rejects_before_http_without_removing_evidence(tmp_path):
    messages = body({}, images=['data:image/png;base64,A'] * 601)['messages']
    with pytest.raises(ContextCapacityError, match='image count'):
        send(messages, [], tmp_path/'review',send_http=lambda *args,**kwargs:pytest.fail('known invalid request must not be sent'))
    assert not list((tmp_path/'review').rglob('attempt.json'))


def test_default_line_fact_encoding_preserves_every_relation_beyond_the_old_cutoff():
    from figfox_plus.native.review_problem_first_v13.context_tables import model_line_facts, expand_line_facts
    facts = {'objects':[{'object_id':'frame','tag':'path'}], 'unsupported':[],
             'relation_candidates':[{'kind':'endpoint_pair','object_ids':['frame','neighbor'],
                                     'endpoint_distances':{'distance':index}} for index in range(800)]}
    assert expand_line_facts(model_line_facts(facts)) == facts


def test_svg_model_text_preserves_dense_anonymous_tracing_paths():
    from figfox_plus.native.review_problem_first_v13.orchestrator import _svg_text
    svg = ('<svg><g desc="Created with imagetracer.js">' + '<path d="M1 2 L3 4"/>'*1500 + '</g></svg>')
    assert _svg_text(svg) == svg
