"""Real Windows-capable IO, request locking, rendering and offline chain checks."""
import copy
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import xml.etree.ElementTree as ET

from PIL import Image
import pytest

from figfox_plus.state import PLUS_ROOT, write_json


def test_concurrent_requests_are_not_double_sent(tmp_path):
    code = '''
import sys
from pathlib import Path
from figfox_plus.providers import request_once
root = Path(sys.argv[1])
def send():
    with (root/'sent.txt').open('a', encoding='utf-8') as handle: handle.write('sent\\n')
try:
    request_once('deepseek','one-request',root/'ledger.jsonl',send,{'deepseek':1})
except ValueError:
    pass
'''
    env = {**os.environ, 'PYTHONPATH': str(PLUS_ROOT/'src')}
    workers = [subprocess.Popen([sys.executable, '-c', code, str(tmp_path)], env=env) for _ in range(4)]
    assert [p.wait(timeout=30) for p in workers] == [0]*4
    assert (tmp_path/'sent.txt').read_text(encoding='utf-8') == 'sent\n'
    rows = [json.loads(line) for line in (tmp_path/'ledger.jsonl').read_text(encoding='utf-8').splitlines()]
    assert [row['event'] for row in rows] == ['sending', 'ok']


def test_utf8_roundtrip_and_credentials(tmp_path, monkeypatch):
    from figfox_plus import providers
    target = tmp_path/'中文'/ 'evidence.json'
    write_json(target, {'label': '中文 α → 😀'})
    assert json.loads(target.read_text(encoding='utf-8'))['label'] == '中文 α → 😀'
    monkeypatch.setattr(providers, 'PLUS_ROOT', tmp_path)
    monkeypatch.delenv('FIGFOX_TEST_KEY', raising=False)
    (tmp_path/'.env').write_text('FIGFOX_TEST_KEY="local"\n', encoding='utf-8-sig')
    assert providers.load_key('FIGFOX_TEST_KEY') == 'local'
    monkeypatch.setenv('FIGFOX_TEST_KEY', 'environment')
    assert providers.load_key('FIGFOX_TEST_KEY') == 'environment'


def test_cv_unicode_path(tmp_path):
    from figfox_plus.image_io import imread
    target = tmp_path/'中文 图.png'
    Image.new('RGB', (8, 4), 'red').save(target)
    pixels = imread(target)
    assert pixels.shape == (4, 8, 3)
    assert list(pixels[0, 0]) == [0, 0, 255]


def test_active_prompt_pack_is_english():
    from figfox_plus.native.review_problem_first_v13.methods import build_method_pack
    from figfox_plus.native.review_problem_first_v13.orchestrator import PROMPT, PROGRAM_CONTRACT
    from figfox_plus.native.review_problem_first_v13.lean_inspection import REPAIR_PROMPT
    from figfox_plus.native.review_problem_first_v13.followup import PROMPT as FOLLOWUP
    from figfox_plus.sp.catalog import manual
    values = [PROMPT, PROGRAM_CONTRACT, REPAIR_PROMPT, FOLLOWUP, manual(),
              (PLUS_ROOT/'prompts/first_native.md').read_text(encoding='utf-8'),
              json.dumps(build_method_pack(), ensure_ascii=False)]
    assert all(re.search(r'[\u4e00-\u9fff]', value) is None for value in values)


@pytest.mark.integration
@pytest.mark.parametrize('route', ['module_program', 'generated_python', 'followup'])
@pytest.mark.parametrize('omit_repair_issues', [False, True])
def test_original_to_repaired_render_with_captured_english_requests(tmp_path, monkeypatch, route, omit_repair_issues):
    """Only SAM/model responses are fixtures; all geometry, crops and execution are real."""
    from figfox_plus.native import chain, pipeline
    from figfox_plus.native.review_problem_first_v13 import orchestrator
    from figfox_plus.native.review_problem_first_v13.lean_inspection import CATEGORIES
    from figfox_plus.native.review_problem_first_v13.inspection_contract import inspection_regions
    from figfox_plus.native.document import parse, measure

    work = tmp_path/'中文 path'
    work.mkdir()
    original = work/'原图.png'
    svg = '<svg xmlns="http://www.w3.org/2000/svg" width="180" height="100" viewBox="0 0 180 100"><rect id="frame" x="4" y="4" width="170" height="90" fill="white" stroke="black"/><text id="label" x="20" y="50" font-size="18">x1</text></svg>'
    measure(parse(svg), original)
    prompts = []
    monkeypatch.setattr(pipeline, 'prepare_assets', lambda *a, **k: {'assets': [], 'status': {'sam': 'ok'}})
    def first_send(prompt, *args, **kwargs):
        prompts.append(prompt)
        return svg
    monkeypatch.setattr(chain, 'call_gpt55', first_send)
    calls = []
    category = 'F' if route == 'followup' else 'B'
    issue = {'id': 'B1', 'image_id': 'fixture', 'category': category,
             'description': 'Synthetic text repair for execution testing.',
             'original_evidence': 'Fixture expects x2.', 'current_evidence': 'Fixture currently says x1.',
             'target_ids': ['label'], 'neighbor_ids': [], 'decision': 'confirmed'}

    def review(task, **kwargs):
        schedule = json.loads((task/'schedule.json').read_text(encoding='utf-8'))
        revision = json.loads((task/'inputs.json').read_text(encoding='utf-8'))['images']['fixture']['current_revision']
        region = inspection_regions(schedule)[0]['region']
        def sender(messages, tools, folder, **options):
            calls.append(copy.deepcopy(messages))
            if len(calls)==1:assert messages[0]['content'].startswith('This is the first request.')
            if len(calls)==2:
                assert messages[0] == calls[0][0]
                assert messages[:len(calls[0])] == calls[0]
                assert messages[-1]['content'].startswith('This is the second request.')
            # The fixture has English source content, so any CJK here is a prompt leak.
            assert re.search(r'[\u4e00-\u9fff]', json.dumps(messages, ensure_ascii=False)) is None
            assert re.search(r'[\u4e00-\u9fff]', json.dumps(tools, ensure_ascii=False)) is None
            if len(calls) == 1:
                plan = {'compact_category_sweeps': [
                    {'category': cat, 'whole_image_observation': 'Synthetic full-image observation.',
                     'svg_observation': 'The fixture SVG contains a frame and a text label.',
                     'candidates': ([{'region': region, 'original_evidence': 'Fixture expects x2.',
                        'current_evidence': 'Label currently says x1.', 'decision': 'confirmed', 'issue_ids': ['B1']}]
                        if cat == category else [])} for cat in CATEGORIES],
                    'issues': [issue], 'programs': [], 'prior_issue_reviews': []}
            else:
                plan = {'issues': [issue], 'programs': [{
                    'id': 'repair_label', 'issue_ids': ['B1'], 'image_id': 'fixture',
                    'base_revision': revision, 'phase': 'reconstructor', 'route': 'module_program',
                    'target_ids': ['label'], 'depends_on': [], 'rcd_predescription': 'Replace fixture text.',
                    'args': {'operations': [{'method': 'bp_patch', 'target_ids': ['label'],
                                            'args': {'text': 'x2'}}]}}], 'prior_issue_reviews': []}
                if route == 'generated_python':
                    program = plan['programs'][0]
                    program.pop('args')
                    program.update(route=route, source_code='import xml.etree.ElementTree as ET\ntree=ET.parse(INPUT_SVG)\ntree.find(".//*[@id=\'label\']").text="x2"\ntree.write(OUTPUT_SVG, encoding="unicode")')
                elif route == 'followup':
                    if len(calls) == 2:
                        plan['programs'] = []  # An unlanded priority issue opens exactly one follow-up.
                    else:
                        plan['programs'][0].update(
                            relations=[{'id': 'inside', 'predicate': 'contain', 'subject_id': 'label',
                                        'object_id': 'frame', 'padding': 2,
                                        'reference_evidence': 'The fixture label belongs inside the frame.'}],
                            convergence={'max_iterations': 6, 'alignment_checks': [], 'repairs': []})
                if omit_repair_issues:plan.pop('issues')
            return {'role': 'assistant', 'content': json.dumps(plan)}
        return orchestrator.run(task, sender=sender, **kwargs)
    monkeypatch.setattr(chain, 'review_run', review)
    out = chain.run_chain(original, work/'result', image_id='fixture', rerun_authorization='offline-fixture')
    result = json.loads((out/'review/fixture/result.json').read_text(encoding='utf-8'))
    assert len(calls) == (3 if route == 'followup' else 2) and len(prompts) == 1
    assert re.search(r'[\u4e00-\u9fff]', prompts[0]) is None
    assert result['coverage']['records_complete'], result['coverage']
    if route == 'followup':
        assert result['followup']['rcd'][0]['status'] == 'changed_unverified', result
        state = json.loads((out/'review/fixture-followup/execution/state.json').read_text(encoding='utf-8'))
        final = state['images']['fixture']
    else:
        assert result['rcd'][0]['status'] == 'changed_unverified', result
        final = result['images']['fixture']
    assert ET.parse(final['svg']).find('.//*[@id="label"]').text == 'x2'
    assert Path(final['png']).is_file()
    assert result['followup']['opened'] is (route == 'followup')
    assert result['visual_passed'] is False
    if omit_repair_issues:
        assert result['last_feedback']['response_metadata']['issues_binding']['issue_ids'] == ['B1']


@pytest.mark.integration
@pytest.mark.parametrize('code', [
    'import socket\nsocket.socket()',
    'import os\nos.fork()',
    'import subprocess\nsubprocess.run(["/bin/true"])',
    'open("/job/input.svg", "w").write("overwritten")',
    'open("/methods/figfox_plus/__init__.py", "w").write("overwritten")',
    '__HOST_CANARY__',
    'allocation = bytearray(600*1024*1024)',
])
def test_generated_code_is_isolated(tmp_path, code):
    from figfox_plus.native.review_problem_first_v13.sandbox import run_code
    source = tmp_path/'input.svg'
    source.write_text('<svg xmlns="http://www.w3.org/2000/svg"/>', encoding='utf-8')
    if code == '__HOST_CANARY__':
        canary = tmp_path/'host-secret.txt'
        canary.write_text('host-only canary', encoding='utf-8')
        if os.name == 'nt':
            wsl = ['wsl']
            if os.environ.get('FIGFOX_WSL_DISTRO'):
                wsl += ['--distribution', os.environ['FIGFOX_WSL_DISTRO']]
            wsl += ['--exec']
            linux_path = subprocess.run(wsl+['wslpath', '-a', '-u', str(canary)],
                                        capture_output=True, text=True, encoding='utf-8', check=True).stdout.strip()
            subprocess.run(wsl+['test', '-r', linux_path], check=True)
        else:
            linux_path = str(canary.resolve())
            assert canary.is_file()
        code = f'open({linux_path!r}, encoding="utf-8").read()'
    result = run_code(code, source, tmp_path/'sandbox')
    assert result['status'] == 'failed', result
    assert result['error'] == 'execution_failed', result
    assert not (tmp_path/'sandbox/generated.svg').exists()


@pytest.mark.integration
def test_generated_code_timeout_and_unicode(tmp_path):
    from figfox_plus.native.review_problem_first_v13.sandbox import run_code
    source = tmp_path/'input.svg'
    source.write_text('<svg xmlns="http://www.w3.org/2000/svg"><text id="label">中文 α 😀</text></svg>', encoding='utf-8')
    code = 'import os\nassert not os.environ.get("OPENAI_API_KEY")\nfrom figfox_plus.sp.geometry import construct\nimport xml.etree.ElementTree as ET\nET.parse(INPUT_SVG).write(OUTPUT_SVG, encoding="unicode")'
    result = run_code(code, source, tmp_path/'roundtrip')
    assert result['status'] == 'executed', result
    assert '中文 α 😀' in Path(result['svg']).read_text(encoding='utf-8')
    result = run_code('while True: pass', source, tmp_path/'timeout', timeout=1)
    assert result['status'] == 'failed'
    assert result['error'] in ('execution_timeout', 'execution_failed')
