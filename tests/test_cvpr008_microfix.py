"""Repair continuation, declared dependencies and actionable failure receipts."""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path

from PIL import Image
import pytest

from figfox_plus.native.review_problem_first_v13.orchestrator import _plan
from figfox_plus.native.review_problem_first_v13.inspection import make_schedule
from figfox_plus.native.review_problem_first_v13.programs import execute_programs
from figfox_plus.native.review_problem_first_v13.replay import select_valid_programs


def scene(tmp_path):
    svg = tmp_path / 'scene.svg'
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60">'
                   '<g id="panel"><rect id="box" x="5" y="20" width="20" height="20" fill="red"/></g>'
                   '<rect id="neighbor" x="15" y="20" width="20" height="20" fill="blue"/>'
                   '<rect id="other" x="60" y="20" width="10" height="10" fill="yellow"/></svg>', encoding='utf-8')
    png = tmp_path / 'original.png'
    Image.new('RGB', (80, 60), 'white').save(png)
    return {'sample': {'svg': str(svg), 'png': str(png), 'original': str(png),
                       'revision': hashlib.sha256(svg.read_bytes()).hexdigest()}}


def issue(ident='S2-1', target='box', category='S2'):
    return {'id': ident, 'image_id': 'sample', 'category': category, 'decision': 'confirmed',
            'description': 'Repair the source-backed object.', 'original_evidence': 'The source object is distinct.',
            'current_evidence': 'The current object differs.', 'target_ids': [target], 'neighbor_ids': ['neighbor']}


def patch(images, ident='paint', ref='S2-1', target='box', color='green'):
    return {'id': ident, 'issue_ids': [ref], 'image_id': 'sample',
            'base_revision': images['sample']['revision'], 'phase': 'reconstructor',
            'route': 'module_program', 'target_ids': [target], 'depends_on': [],
            'rcd_predescription': 'Use the declared local patch.',
            'args': {'operations': [{'method': 'bp_patch', 'target_ids': [target],
                                     'args': {'attributes': {'fill': color}}}]}}


def message(payload, channel):
    raw = json.dumps(payload)
    if channel == 'tool':
        return {'tool_calls': [{'id': 'call-1', 'function': {'name': 'execute_review_program', 'arguments': raw}}]}
    return {'content': '```json\n' + raw + '\n```' if channel == 'fence' else raw}


@pytest.mark.parametrize('channel', ['content', 'fence', 'tool', 'strict_tool'])
def test_missing_repair_issues_reuse_validated_discovery_without_changing_reply(tmp_path, channel):
    images = scene(tmp_path)
    previous = [issue()]
    program = patch(images)
    payload = {'programs': [program]}
    if channel == 'strict_tool':
        payload = {'programs': [{'program_json': json.dumps(program)}], 'prior_issue_reviews': []}
    reply = message(payload, 'tool' if channel == 'strict_tool' else channel)
    saved = deepcopy(reply)
    assets = {'original_png': {'asset_id': 'original'}, 'current_png': {'asset_id': 'current'},
              'current_revision': images['sample']['revision'], 'crop_pairs': [{
                  'pair_id': 'crop', 'original_asset': {'asset_id': 'original-crop'},
                  'current_asset': {'asset_id': 'current-crop'}}]}
    plan, _ = _plan(reply, make_schedule({'images': {'sample': assets}}), review_only=True,
                    repair_context={'issues': previous, 'images': images})
    assert plan['issues'] == previous and plan['programs'][0]['args'] == program['args']
    assert plan['_response_metadata']['issues_binding']['source'] == 'previous_discovery'
    assert plan['_response_metadata']['issues_binding']['issue_ids'] == ['S2-1']
    assert reply == saved
    plan['issues'][0]['description'] = 'Modified copy'
    assert previous[0]['description'] == issue()['description']


def test_discovery_and_invalid_explicit_issues_stay_strict(tmp_path):
    images = scene(tmp_path)
    context = {'issues': [issue()], 'images': images}
    with pytest.raises(ValueError, match='missing issues'):
        _plan(message({'programs': []}, 'content'))
    for value in [None, {}, '']:
        with pytest.raises(ValueError, match='missing issues'):
            _plan(message({'issues': value, 'programs': []}, 'content'), repair_context=context)
    plan, _ = _plan(message({'issues': [], 'programs': []}, 'content'), repair_context=context)
    assert plan['issues'] == [] and 'issues_binding' not in plan['_response_metadata']


def test_unvalidated_previous_targets_never_become_repair_evidence(tmp_path):
    images = scene(tmp_path)
    previous = [issue(target='absent')]
    with pytest.raises(ValueError, match='unknown current SVG object'):
        _plan(message({'programs': []}, 'content'), repair_context={'issues': previous, 'images': images})


@pytest.mark.parametrize('bad_field,bad_value', [('issue_ids', ['invented']), ('image_id', 'other-image')])
def test_inherited_issues_cannot_bind_unknown_or_cross_image_programs(tmp_path, bad_field, bad_value):
    images = scene(tmp_path)
    good = patch(images)
    bad = patch(images, ident='bad')
    bad[bad_field] = bad_value
    plan, _ = _plan(message({'programs': [bad, good]}, 'content'),
                    repair_context={'issues': [issue()], 'images': images})
    accepted, rejected = select_valid_programs(plan['programs'], plan['issues'], images)
    assert [p['id'] for p in accepted] == ['paint']
    assert [p['program_id'] for p in rejected] == ['bad']


def test_shared_s2_group_keeps_declared_dependency_and_status_condition(tmp_path):
    images = scene(tmp_path)
    first = patch(images, ident='first')
    boundary = patch(images, ident='boundary', ref='S2-2', target='panel')
    boundary['depends_on'] = ['first']
    boundary['when'] = {'program': 'first', 'status': 'changed_unverified'}
    accepted, rejected = select_valid_programs([first, boundary], [issue(), issue('S2-2', 'panel')], images)
    assert not rejected
    assert accepted[1]['depends_on'] == ['first'] and accepted[1]['when'] == boundary['when']
    assert boundary['depends_on'] == ['first']


def test_missing_shared_dependency_is_not_invented_and_independent_work_survives(tmp_path):
    images = scene(tmp_path)
    programs = [patch(images, ident='first'), patch(images, ident='missing', ref='S2-2', target='panel'),
                patch(images, ident='independent', ref='S2-3', target='other')]
    accepted, rejected = select_valid_programs(programs, [issue(), issue('S2-2', 'panel'), issue('S2-3', 'other')], images)
    assert [p['id'] for p in accepted] == ['first', 'independent']
    assert rejected[0]['program_id'] == 'missing' and 'explicit dependency' in rejected[0]['error']


def test_dependencies_remain_transitive_across_saved_execution_rounds(tmp_path):
    images = scene(tmp_path)
    prior = [{'program_id': ident, 'image_id': 'sample', 'target_ids': ['box'], 'depends_on': deps,
              'status': 'changed_unverified'} for ident, deps in [('first', []), ('second', ['first']), ('third', ['second'])]]
    next_program = patch(images, ident='next')
    next_program['depends_on'] = ['third']
    accepted, rejected = select_valid_programs([next_program], [issue()], images, prior_executed=prior)
    assert not rejected and accepted[0]['depends_on'] == ['third']


def test_arrow_programs_keep_same_valid_scope_dependency_as_other_categories(tmp_path):
    images = scene(tmp_path)
    first = patch(images, ident='first')
    arrow = patch(images, ident='arrow', ref='D-1')
    arrow['depends_on'] = ['first']
    arrow['args']['operations'] = [{'method': 'sp_replace', 'target_ids': ['box'],
                                    'args': {'kind': 'arrow', 'data': {'start': [5, 20], 'end': [25, 20]}}}]
    accepted, rejected = select_valid_programs([first, arrow], [issue(), issue('D-1', category='D')], images)
    assert not rejected and accepted[1]['depends_on'] == ['first']


@pytest.mark.integration
def test_failed_relation_records_measurements_rolls_back_and_honors_s2_fallback(tmp_path):
    images = scene(tmp_path)
    before = Path(images['sample']['svg']).read_bytes()
    failed = patch(images, ident='failed', ref='F-1', color='purple')
    failed['relations'] = [{'id': 'apart', 'predicate': 'separate', 'subject_id': 'box',
                            'object_id': 'neighbor', 'min_gap': 1,
                            'reference_evidence': 'The source requires these boxes to be separated.'}]
    failed['convergence'] = {'max_iterations': 2, 'repairs': []}
    fallback = patch(images, ident='fallback', color='black')
    fallback['depends_on'] = ['failed']
    fallback['when'] = {'program': 'failed', 'status': 'failed'}
    independent = patch(images, ident='independent', ref='S2-3', target='other')
    issues = [issue('F-1', category='F'), issue(), issue('S2-3', 'other')]
    accepted, rejected = select_valid_programs([failed, fallback, independent], issues, images)
    assert not rejected
    result = execute_programs(accepted, issues, images, tmp_path / 'execution')
    receipt = result['rcd'][0]
    assert receipt['status'] == 'failed' and receipt['rolled_back']
    assert receipt['before_revision'] == receipt['after_revision']
    assert receipt['convergence']['status'] == 'unresolved'
    assert receipt['convergence']['history'][0]['failed'] == ['apart']
    relation = receipt['convergence']['history'][0]['checks'][0]['relations'][0]
    assert relation['status'] == 'violated' and relation['participants'] == ['box', 'neighbor']
    assert result['rcd'][1]['status'] == result['rcd'][2]['status'] == 'changed_unverified'
    assert result['rcd'][1]['trigger']['matched'] and result['rcd'][1]['depends_on'] == ['failed']
    final = Path(result['images']['sample']['svg']).read_text(encoding='utf-8')
    assert 'purple' not in final and 'black' in final
    assert Path(images['sample']['svg']).read_bytes() == before
    with Image.open(result['images']['sample']['png']) as image:
        image.load()
        assert image.convert('RGB').getpixel((65, 25)) == (0, 128, 0)


def test_followup_rejections_are_in_top_level_summary_with_stage_counts(tmp_path, monkeypatch):
    spec = importlib.util.spec_from_file_location('batch_cvpr008', Path(__file__).resolve().parents[1] / 'scripts/batch-experiment.py')
    batch = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(batch)
    case = tmp_path / 'case'
    case.mkdir()
    images = scene(case)
    review = case / 'run/review/sample'
    batch.write_json(case / 'case.json', {'id': 'sample', 'exit_code': 0})
    batch.write_json(review / 'result.json', {'status': 'emergency_unresolved', 'images': images,
        'issues': [], 'rcd': [], 'rejected_programs': [{'program_id': 'main-bad'}],
        'followup': {'status': 'completed', 'rcd': []}})
    batch.write_json(review.with_name('sample-followup') / 'program-preflight.json', {
        'rejected': [{'program_id': 'source-bad'}], 'shape_rejected': [{'program_id': 'shape-bad'}]})
    from figfox_plus.native import artifacts
    monkeypatch.setattr(artifacts, 'publish_latest', lambda *a, **k: {
        'outputs': images['sample'], 'artifact_status': 'available', 'output_stage': 'followup'})
    result = batch.collect_case(case)
    assert result['preflight_rejected_programs'] == 3
    assert result['main_preflight_rejected_programs'] == 1
    assert result['followup_preflight_rejected_programs'] == 2
