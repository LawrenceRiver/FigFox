import hashlib
import json

import pytest

from figfox_plus.native.review_json_syntax import parse_complete_json
from figfox_plus.native.review_problem_first_v13.orchestrator import _plan


def test_model_string_controls_preserve_evidence_code_values_and_original_reply():
    expected = {'compact_category_sweeps': [],
                'issues': [{'id': 'F-1', 'description': 'First line\n第二行\tkept'}],
                'programs': [{'source_code': 'x = 1\nprint(x)\n'}], 'prior_issue_reviews': [],
                'typed': [True, 1, 1.0, -0.0], 'escaped_literal': r'\n'}
    raw = json.dumps(expected, ensure_ascii=False).replace('First line\\n第二行\\tkept', 'First line\n第二行\tkept')
    message = {'role': 'assistant', 'content': raw, 'reasoning_content': 'Original reasoning'}
    plan, _ = _plan(message)
    assert {key: plan[key] for key in expected} == expected
    assert json.dumps(plan['typed']) == json.dumps(expected['typed'])
    assert message['content'] == raw and message['reasoning_content'] == 'Original reasoning'
    edits = plan['_syntax_edits']
    assert len(edits) == 2 and all(edit['kind'] == 'unescaped_string_control' for edit in edits)
    assert all(edit['source_sha256'] == hashlib.sha256(raw.encode('utf-8')).hexdigest() for edit in edits)


@pytest.mark.parametrize('raw', [
    '{"a":"first\nsecond"',
    '{"a":"first\nsecond"} trailing',
    '{"a":"first\nsecond"} {"b":1}',
    '{"a":"first\nsecond", "b":NaN}',
    '{"a":"first\nsecond", "b":Infinity}',
    '{"a":"first\nsecond" "b":1}',
    '{"a":1\x00}',
    '{"a":"first\nsecond", "b":"\\q"}',
])
def test_control_repair_never_completes_truncated_or_other_invalid_json(raw):
    with pytest.raises(ValueError): parse_complete_json(raw)


def test_correct_json_and_existing_delimiter_repair_keep_their_behavior():
    expected = {'evidence': 'line\nnext\tend', 'literal': r'\n'}
    plain = json.dumps(expected)
    assert parse_complete_json(plain) == (expected, [])
    decoded, edits = parse_complete_json('{"evidence"："clear"}')
    assert decoded == {'evidence': 'clear'}
    assert edits[0]['kind'] == 'parser_identified_fullwidth_delimiter'
