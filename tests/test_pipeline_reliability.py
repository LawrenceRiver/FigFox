import copy
import hashlib
import json
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from figfox_plus.native import chain, pipeline
from figfox_plus.native.artifacts import publish_latest
from figfox_plus.native.document import parse, serialize, measure
from figfox_plus.native.review_problem_first_v13 import orchestrator
from figfox_plus.native.review_problem_first_v13.lean_inspection import CATEGORIES
from figfox_plus.native.review_problem_first_v13.programs import execute_programs
from figfox_plus.native.review_problem_first_v13.replay import select_valid_programs
from figfox_plus.state import write_json


def pair(folder, color='red'):
    folder.mkdir(parents=True, exist_ok=True)
    svg = folder / 'scene.svg'
    svg.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="60" height="40"><rect id="box" width="60" height="40" fill="{color}"/></svg>', encoding='utf-8')
    png = folder / 'preview.png'
    Image.new('RGB', (60, 40), color).save(png)
    return {'svg': str(svg), 'png': str(png), 'revision': hashlib.sha256(svg.read_bytes()).hexdigest()}


def test_nested_viewports_cdata_and_common_xml_repairs_preserve_content():
    repairs = []
    source = ('<!-- <svg/> --><svg xmlns="http://www.w3.org/2000/svg">'
              '<defs><g id="shape"><rect width="4" height="5"/></g></defs>'
              '<svg x="12" y="13"><use xlink:href="#shape"/></svg>'
              '<desc><![CDATA[literal </svg>]]></desc><text>R&D\x00 &nbsp;</text></svg>')
    root = parse(source, repairs=repairs)
    assert root[1].get('x') == '12'
    assert root[1][0].get('{http://www.w3.org/1999/xlink}href') == '#shape'
    assert root[2].text == 'literal </svg>'
    assert root[3].text == 'R&D \u00a0'
    assert {r['kind'] for r in repairs} == {
        'declare_xlink_namespace', 'remove_invalid_xml_characters',
        'escape_bare_ampersand', 'html_named_entity_to_numeric'}
    assert len(parse('<svg/>')) == 0


@pytest.mark.parametrize('failure', ['broken_png', 'wrong_revision'])
def test_invalid_latest_checkpoint_falls_back_to_a_complete_pair(tmp_path, failure):
    baseline = pair(tmp_path / 'native-fixture/stage-0')
    latest = pair(tmp_path / 'trial', 'blue')
    if failure == 'broken_png':
        Path(latest['png']).write_bytes(b'not a PNG')
    else:
        latest['revision'] = 'wrong'
    write_json(tmp_path / 'review/sample/phase-2/execution/state.json', {'images': {'sample': latest}})
    before = {suffix: Path(baseline[suffix]).read_bytes() for suffix in ('svg', 'png')}
    result = publish_latest(tmp_path, 'sample', error={'type': 'TimeoutError'})
    assert result['artifact_status'] == 'available' and result['output_stage'] == 'baseline_only'
    assert result['review_status'] == 'failed' and result['visual_passed'] is False
    assert len(result['rejected_candidates']) == 1
    for suffix in ('svg', 'png'):
        assert (tmp_path / ('final.' + suffix)).read_bytes() == before[suffix]
        assert Path(baseline[suffix]).read_bytes() == before[suffix]


def test_partial_execution_checkpoint_survives_a_missing_review_result(tmp_path):
    pair(tmp_path / 'native-fixture/stage-0')
    updated = pair(tmp_path / 'accepted', 'blue')
    write_json(tmp_path / 'review/sample/phase-2/execution/state.json', {'images': {'sample': updated}})
    result = publish_latest(tmp_path, 'sample', error={'type': 'ConnectionError'})
    assert result['output_stage'] == 'review_checkpoint' and result['review_status'] == 'failed'
    assert (tmp_path / 'final.svg').read_bytes() == Path(updated['svg']).read_bytes()


def empty_inspection():
    return {'compact_category_sweeps': [
        {'category': category, 'whole_image_observation': 'The synthetic original/current pair has been inspected.',
         'svg_observation': 'The fixture contains visible drawing.', 'candidates': []}
        for category in CATEGORIES], 'issues': [], 'programs': []}


@pytest.mark.integration
@pytest.mark.parametrize('mode', ['complete', 'incomplete', 'transport_error', 'discovered', 'discovered_tool'])
def test_real_chain_keeps_outputs_despite_optional_parameters_or_review_failure(tmp_path, monkeypatch, mode):
    original = tmp_path / 'original.png'
    Image.new('RGB', (180, 100), 'white').save(original)
    svg = ('<svg xmlns="http://www.w3.org/2000/svg" width="180" height="100" viewBox="0 0 180 100">'
           '<rect id="frame" x="4" y="4" width="170" height="90" fill="white" stroke="black"/>'
           '<text id="label" x="20" y="50" data-plus-color=\'{"fill":[]}\' font-size="18">R&D</text>'
           '<g id="solid" data-plus-sp=\'{"kind":"unknown","data":{}}\'><circle cx="100" cy="50" r="8"/></g>'
           '<rect id="crop" x="130" y="40" width="10" height="10" data-plus-crop="not-a-box"/></svg>')
    monkeypatch.setattr(pipeline, 'prepare_assets', lambda *a, **k: {'assets': [], 'status': {'sam': 'fixture'}})
    monkeypatch.setattr(chain, 'call_gpt55', lambda *a, **k: svg)
    calls = []
    discovered = {'id': 'B-1', 'image_id': 'fixture', 'category': 'B', 'decision': 'uncertain',
                  'description': 'Check the fixture label against the original.',
                  'original_evidence': 'Original fixture pixels are supplied.',
                  'current_evidence': 'The current label is addressable in the SVG.',
                  'target_ids': ['label'], 'neighbor_ids': []}

    def sender(messages, tools, task, **kwargs):
        calls.append(copy.deepcopy(messages))
        if mode == 'transport_error':
            raise TimeoutError('synthetic review interruption')
        if mode.startswith('discovered'):
            if len(calls) == 1:
                from figfox_plus.native.review_problem_first_v13.inspection_contract import inspection_regions
                schedule = json.loads((task / 'schedule.json').read_text(encoding='utf-8'))
                region = inspection_regions(schedule)[0]['region']
                inspection = empty_inspection()
                inspection['issues'] = [discovered]
                sweep = next(s for s in inspection['compact_category_sweeps'] if s['category'] == 'B')
                sweep['candidates'] = [{'region': region, 'decision': 'uncertain', 'issue_ids': ['B-1'],
                                        'original_evidence': discovered['original_evidence'],
                                        'current_evidence': discovered['current_evidence']}]
                message = {'role': 'assistant', 'content': json.dumps(inspection),
                           'reasoning_content': 'saved discovery reasoning ' * 1000}
                if mode == 'discovered_tool':
                    message['content'] = ''
                    message['tool_calls'] = [{'id': 'discovery-call', 'type': 'function',
                        'function': {'name': tools[0]['function']['name'], 'arguments': json.dumps(inspection)}}]
                return message
            return {'role': 'assistant', 'content': json.dumps({'issues': [discovered], 'programs': []})}
        return {'role': 'assistant', 'content': json.dumps(empty_inspection() if mode == 'complete' else {'issues': [], 'programs': []})}

    out = tmp_path / 'run'
    if mode == 'transport_error':
        with pytest.raises(TimeoutError, match='synthetic review interruption'):
            chain.run_chain(original, out, image_id='fixture', rerun_authorization='fixture', review_sender=sender)
    else:
        chain.run_chain(original, out, image_id='fixture', rerun_authorization='fixture', review_sender=sender)
        assert len(calls) == 2
    artifacts = json.loads((out / 'artifacts.json').read_text(encoding='utf-8'))
    assert artifacts['artifact_status'] == 'available' and artifacts['visual_passed'] is False
    root = parse((out / 'final.svg').read_text(encoding='utf-8'))
    assert next(n for n in root.iter() if n.get('id') == 'label').text == 'R&D'
    assert next(n for n in root.iter() if n.get('id') == 'solid')[0].get('r') == '8'
    with Image.open(out / 'final.png') as image:
        assert image.size == (180, 100)
        image.verify()
    report = json.loads(next(out.glob('native-*/first-postprocessing.json')).read_text(encoding='utf-8'))
    assert report['deferred_count'] == 3
    if mode == 'transport_error':
        assert artifacts['review_status'] == 'failed'
    elif mode == 'incomplete':
        assert artifacts['review_status'] == 'inspection_incomplete'
    elif mode.startswith('discovered'):
        def evidence(request):
            return [message for message in request if message['role'] == 'user'
                    and isinstance(message.get('content'), list)]
        original_evidence = evidence(calls[0])
        assert len(original_evidence) > 2
        assert sum(part.get('type') == 'image_url' for message in original_evidence
                   for part in message['content']) >= 4
        assert evidence(calls[1]) == original_evidence
        assert calls[1][:len(calls[0])] == calls[0]
        assistant = next(message for message in calls[1] if message['role'] == 'assistant')
        assert assistant['reasoning_content'] == 'saved discovery reasoning ' * 1000
        assert calls[1][-1]['role'] == 'user'
        if mode == 'discovered_tool':
            receipt = next(message for message in calls[1] if message['role'] == 'tool')
            assert receipt['tool_call_id'] == assistant['tool_calls'][0]['id'] == 'discovery-call'
            assert json.loads(receipt['content'])['issues'][0]['id'] == 'B-1'
        assert artifacts['review_status'] == 'visual_review_pending'


def test_optional_runtime_defaults_do_not_weaken_visual_relations(tmp_path):
    baseline = pair(tmp_path)
    issue = {'id': 'F-1', 'image_id': 'sample', 'category': 'F', 'target_ids': ['box'],
             'neighbor_ids': [], 'original_evidence': 'The original requires clearance.'}
    program = {'id': 'p', 'image_id': 'sample', 'base_revision': baseline['revision'],
               'phase': 'reconstructor', 'route': 'module_program', 'target_ids': ['box'],
               'issue_ids': ['F-1'], 'depends_on': None, 'when': None,
               'args': {'operations': [{'method': 'bp_patch', 'target_ids': ['box'], 'args': {'attributes': {'fill': 'blue'}}}]},
               'relations': [{'id': 'r', 'predicate': 'contain', 'subject_id': 'box',
                              'object_id': 'box', 'padding': 1, 'reference_evidence': 'Original clearance.'}],
               'convergence': {'repairs': None, 'alignment_checks': None}}
    images = {'sample': {**baseline, 'original': baseline['png']}}
    accepted, rejected = select_valid_programs([program], [issue], images)
    assert not rejected and accepted[0]['convergence']['max_iterations'] == 6
    assert accepted[0]['relations'][0]['padding'] == 1
    assert program['depends_on'] is None
    program['relations'][0]['padding'] = 0
    accepted, rejected = select_valid_programs([program], [issue], images)
    assert not accepted and 'positive padding' in rejected[0]['error']


def convergence_anchor_case(tmp_path):
    root = parse('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="60">'
                 '<rect id="frame" x="5" y="5" width="110" height="50" fill="white" stroke="black"/>'
                 '<rect id="box" x="0" y="20" width="20" height="20" fill="red"/></svg>')
    svg, png, original = (tmp_path / name for name in ('scene.svg', 'preview.png', 'original.png'))
    svg.write_text(serialize(root), encoding='utf-8')
    measure(root, png)
    source = Image.new('RGB', (120, 60), 'white')
    draw = ImageDraw.Draw(source)
    draw.rectangle((5, 5, 114, 54), outline='black')
    draw.rectangle((15, 20, 34, 39), fill='red')
    source.save(original)
    revision = hashlib.sha256(svg.read_bytes()).hexdigest()
    images = {'sample': {'svg': str(svg), 'png': str(png), 'original': str(original), 'revision': revision}}
    issue = {'id': 'F-1', 'image_id': 'sample', 'category': 'F', 'decision': 'confirmed',
             'description': 'The box extends beyond its enclosing frame.',
             'target_ids': ['box'], 'neighbor_ids': ['frame'],
             'original_evidence': 'The source box has ten pixels of clearance inside the frame.',
             'current_evidence': 'The current box extends past the left frame edge.'}
    program = {'id': 'p', 'image_id': 'sample', 'base_revision': revision,
               'phase': 'reconstructor', 'route': 'module_program', 'target_ids': ['box'],
               'issue_ids': ['F-1'], 'depends_on': [],
               'args': {'operations': [{'method': 'measure', 'target_ids': ['box'], 'args': {}}]},
               'relations': [{'id': 'inside', 'predicate': 'contain', 'subject_id': 'box',
                              'object_id': 'frame', 'padding': 5, 'reference_evidence': issue['original_evidence']}],
               'convergence': {'repairs': [{'check_id': 'inside', 'method': 'tp_transform',
                   'target_ids': ['box'], 'source_location': None,
                   'args': {'world_matrix': [1, 0, 0, 1,
                       {'$calc': 'sub', 'values': [15, {'$measure': {'ids': ['box'], 'edge': 'left'}}]}, 0],
                       'parent_id': None, 'before_id': '', 'after_id': None}}]}}
    return images, issue, program


@pytest.mark.integration
def test_empty_optional_anchors_do_not_block_measured_convergence(tmp_path):
    images, issue, program = convergence_anchor_case(tmp_path)
    before = Path(images['sample']['svg']).read_bytes()
    accepted, rejected = select_valid_programs([program], [issue], images)
    assert not rejected, rejected
    repair = accepted[0]['convergence']['repairs'][0]
    assert all(key not in repair['args'] for key in ('parent_id', 'before_id', 'after_id'))
    assert 'source_location' not in repair
    assert repair['args']['world_matrix'] == program['convergence']['repairs'][0]['args']['world_matrix']
    assert program['convergence']['repairs'][0]['args']['parent_id'] is None
    result = execute_programs(accepted, [issue], images, tmp_path / 'execution')
    record = result['rcd'][0]
    assert record['status'] == 'changed_unverified', record
    assert record['final_scene_check']['status'] == 'measured_converged'
    assert record['convergence']['history'][0]['failed'] == ['inside']
    assert record['final_scene_check']['history'][-1]['failed'] == []
    with Image.open(result['images']['sample']['png']) as image:
        assert image.convert('RGB').getpixel((15, 30)) == (255, 0, 0)
        assert image.convert('RGB').getpixel((0, 30)) == (255, 255, 255)
    assert Path(images['sample']['svg']).read_bytes() == before


@pytest.mark.parametrize('anchor', ['parent_id', 'before_id', 'after_id'])
def test_nonempty_unknown_convergence_anchors_still_reject(tmp_path, anchor):
    images, issue, program = convergence_anchor_case(tmp_path)
    program['convergence']['repairs'][0]['args'][anchor] = 'unknown-container'
    accepted, rejected = select_valid_programs([program], [issue], images)
    assert not accepted and 'typed anchor references unknown' in rejected[0]['error']


@pytest.mark.integration
def test_default_chain_with_a_truncated_first_reply_never_opens_an_extra_model_stage(tmp_path, monkeypatch):
    from figfox_plus.native.first_recovery import recover_baseline
    original = tmp_path / 'original.png'
    Image.new('RGB', (24, 16), 'red').save(original)
    monkeypatch.setattr(pipeline, 'prepare_assets', lambda *a, **k: {'assets': [], 'status': {'sam': 'fixture'}})
    calls = []
    def gpt(prompt, images, folder, *args, **kwargs):
        calls.append(folder)
        folder.mkdir(parents=True, exist_ok=True)
        (folder/'response.txt').write_text('<svg><rect id="frame"', encoding='utf-8')
        return '<svg><rect id="frame"'
    def forbidden(*args, **kwargs):pytest.fail('the default chain cannot open an extra model request')
    def local_recovery(original, run, error, **kwargs):
        return recover_baseline(original, run, error, sender=forbidden, **kwargs)
    monkeypatch.setattr(chain, 'call_gpt55', gpt)
    monkeypatch.setattr(chain, 'recover_baseline', local_recovery)
    out = tmp_path/'run'
    with pytest.raises(ValueError, match='missing complete SVG'):
        chain.run_chain(original, out, image_id='fixture', rerun_authorization='offline regression', review_sender=forbidden)
    assert len(calls) == 1 and not list(out.rglob('first-recovery-attempt.json'))
    artifacts = json.loads((out/'artifacts.json').read_text(encoding='utf-8'))
    assert artifacts['artifact_status'] != 'available' and artifacts['review_status'] == 'failed'
    assert not (out/'final.svg').exists() and not (out/'final.png').exists()


@pytest.mark.integration
def test_first_render_fallback_preserves_draft_and_records_failure(tmp_path, monkeypatch):
    original = tmp_path / 'original.png'
    Image.new('RGB', (60, 40), 'red').save(original)
    draft = pair(tmp_path / 'draft')
    (tmp_path / 'first-draft.svg').write_bytes(Path(draft['svg']).read_bytes())
    trial = parse(Path(draft['svg']).read_text())
    trial.set('data-fixture-render-fails', 'true')
    native_measure = pipeline.measure

    def renderer(root, png):
        if root.get('data-fixture-render-fails'):
            raise ValueError('synthetic renderer rejection')
        return native_measure(root, png)

    monkeypatch.setattr(pipeline, 'measure', renderer)
    pipeline.stage(trial, original, tmp_path / 'stage-0')
    fallback = json.loads((tmp_path / 'stage-0/render-fallback.json').read_text())
    assert fallback['visual_passed'] is False and 'synthetic renderer rejection' in fallback['error']
    assert 'data-fixture-render-fails' not in (tmp_path / 'stage-0/scene.svg').read_text()
    assert (tmp_path / 'stage-0/preview.png').is_file()
