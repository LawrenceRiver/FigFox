"""Capacity failures must be caught before spending an HTTP attempt."""
import json

import pytest

from figfox_plus.native.review_problem_first_v13.context_tables import compact_line_facts, expand_line_facts
from figfox_plus.native.review_problem_first_v13.transport import send, _message


def test_repeated_line_styles_are_lossless_and_not_sent_thousands_of_times():
    facts = {'objects': [
        {'object_id': f'node-{n}', 'style': {'stroke': 'rgb(208, 211, 206)', 'fill': 'rgb(208, 211, 206)',
         'stroke_width': '1px', 'display': 'inline', 'opacity': '0.470588'},
         'path_data': f'M {n} 0 L {n} 1 Z', 'markers': {'start': None, 'end': None}, 'reason': 'closed_contour'}
        for n in range(1000)], 'relation_candidates': [], 'unsupported': []}
    compact = compact_line_facts(facts)
    assert expand_line_facts(compact) == facts
    assert len(json.dumps(compact)) < len(json.dumps(facts)) * .5
    assert json.dumps(compact).count('0.470588') == 1


class Response:
    headers = {'Content-Type': 'application/json'}

    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self):
        return json.dumps({'choices': [{'message': {'role': 'assistant', 'content': 'ok'},
                                      'finish_reason': 'stop'}]}).encode()


def test_output_reservation_is_bounded_and_recorded(tmp_path):
    requests = []
    def http(request, timeout):
        requests.append(json.loads(request.data))
        return Response()
    messages = [{'role': 'user', 'content': 'Inspect the saved whole image.'}]
    assert send(messages, [], tmp_path, send_http=http)['content'] == 'ok'
    assert requests[0]['max_tokens'] == 64000
    budgets = list(tmp_path.glob('model-turns/*/context-budget.json'))
    assert len(budgets) == 1
    assert json.loads(budgets[0].read_text())['exact_token_count'] is False
    # Identical successful turns still use the saved response.
    send(messages, [], tmp_path, send_http=http)
    assert len(requests) == 1


def test_oversized_input_is_not_sent_or_charged(tmp_path):
    def http(*args, **kwargs): pytest.fail('over-capacity request reached HTTP')
    with pytest.raises(ValueError, match='input_capacity_exceeded'):
        send([{'role': 'user', 'content': 'x' * 2_200_000}], [], tmp_path, send_http=http)
    assert not (tmp_path / 'api-ledger.jsonl').exists()
    assert not list(tmp_path.glob('model-turns/*/attempt.json'))
    reports = list(tmp_path.glob('model-turns/*/context-budget.json'))
    assert json.loads(reports[0].read_text())['status'] == 'blocked_before_http'


def test_tools_and_continuation_also_count_towards_capacity(tmp_path):
    def http(*args, **kwargs): pytest.fail('oversized continuation reached HTTP')
    messages = [{'role': 'user', 'content': 'short'},
                {'role': 'assistant', 'content': '', 'reasoning_content': 'r' * 1_100_000,
                 'tool_calls': [{'id': 'c', 'type': 'function',
                                 'function': {'name': 'repair', 'arguments': 'a' * 800_000}}]}]
    tools = [{'type': 'function', 'function': {'name': 'repair', 'description': 'd' * 300_000}}]
    with pytest.raises(ValueError, match='input_capacity_exceeded'):
        send(messages, tools, tmp_path, send_http=http)


def test_incomplete_output_is_never_accepted():
    with pytest.raises(ValueError, match='incomplete model turn'):
        _message({'choices': [{'finish_reason': 'length',
                              'message': {'role': 'assistant', 'content': 'partial code'}}]})


def test_column_dictionaries_preserve_types_nested_distances_and_independent_records():
    record={'object_ids': ['a','b'], 'endpoint_distances':
            {'start_start':1.0,'start_end':2.5,'end_start':3,'end_end':4.0}, 'value':True}
    facts={'objects': [], 'relation_candidates': [dict(record) for _ in range(100)], 'unsupported': []}
    facts['relation_candidates'][0]['value']=1
    facts['relation_candidates'][1]['value']=1.0
    compact=compact_line_facts(facts)
    decoded=expand_line_facts(compact)
    assert decoded==facts
    assert [type(r['value']) for r in decoded['relation_candidates'][:3]]==[int,float,bool]
    decoded['relation_candidates'][0]['object_ids'].append('new')
    assert decoded['relation_candidates'][1]['object_ids']==['a','b']
    assert expand_line_facts(compact)==facts


def test_image_bytes_do_not_count_as_literal_text_and_output_is_not_silently_shrunk(monkeypatch):
    from figfox_plus.native.review_problem_first_v13.context_budget import plan_context
    messages=[{'role':'user','content':[{'type':'image_url','image_url':
                {'url':'data:image/png;base64,'+'a'*5_000_000}}]}]
    b=plan_context(messages,[])
    assert b['image_count']==1 and b['text_utf8_bytes']<1000
    monkeypatch.setenv('FLOW_DS_CONTEXT_TOKENS','80000')
    b=plan_context(messages,[])
    assert b['status']=='blocked_before_http' and b['max_output_tokens']==64000


def test_continuation_uses_provider_count_only_for_an_identical_prefix():
    from figfox_plus.native.review_problem_first_v13.context_budget import plan_context
    prefix=[{'role':'user','content':'dense SVG'*1000}]
    tools=[{'type':'function','function':{'name':'repair'}}]
    prior={'messages':prefix,'tools':tools,'prompt_tokens':600000}
    messages=prefix+[{'role':'assistant','content':'a'*100000},{'role':'user','content':'repair'}]
    b=plan_context(messages,tools,provider_prefixes=[prior])
    assert b['estimated_input_tokens']>=650000
    assert b['estimated_input_tokens']<670000
    assert b['provider_prefix_prompt_tokens']==600000 and b['max_output_tokens']==64000
    different=[{'role':'user','content':'different image'}]+messages[1:]
    b=plan_context(different,tools,provider_prefixes=[prior])
    assert 'provider_prefix_prompt_tokens' not in b
