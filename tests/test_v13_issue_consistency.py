"""Repair echoes cannot erase confirmed discovery without supported reinspection."""
from copy import deepcopy
import hashlib
import json

import pytest

from figfox_plus.native.review_problem_first_v13.followup import open_issues, reconcile_followup
from figfox_plus.native.review_problem_first_v13.issues import effective_issue_rows


def issue(category='F'):
    return {'id': 'issue-1', 'image_id': 'sample', 'category': category,
            'decision': 'confirmed', 'description': 'An observed source mismatch.',
            'original_evidence': 'The original objects are separated.',
            'current_evidence': 'The current objects overlap.',
            'target_ids': ['a'], 'neighbor_ids': ['b']}


@pytest.mark.parametrize('category', ['A', 'B', 'C', 'D', 'E', 'F', 'S2', 'S3', 'S4'])
@pytest.mark.parametrize('decision', ['preserved', 'uncertain', 'duplicate'])
def test_repair_echo_cannot_downgrade_confirmed_non_s1(category, decision):
    original = issue(category)
    echo = {**original, 'decision': decision,
            'source_review': {'classification': 'planar', 'evidence': 'A source review.'}}
    history = [original, echo]
    saved = deepcopy(history)
    assert effective_issue_rows(history) == [original]
    assert history == saved


@pytest.mark.parametrize('category', ['F', 'E', 'S1', 'S2'])
def test_repair_echo_cannot_change_category_to_bypass_followup(category):
    original = issue(category)
    echo = {**original, 'category': 'C'}
    assert [row['id'] for row in open_issues({'issues': [original, echo], 'rcd': []})] == ['issue-1']


def test_unsupported_downgrade_keeps_missing_repair_unresolved():
    original = issue()
    echo = {**original, 'decision': 'preserved'}
    result = {'status': 'emergency_unresolved', 'coverage': {'records_complete': True},
              'issues': [original, echo], 'images': {}, 'rcd': [],
              'followup': {'status': 'completed', 'issue_ids': ['issue-1']}}
    assert [row['id'] for row in open_issues(result)] == ['issue-1']
    final = reconcile_followup(result, {'images': {}, 'rcd': []})
    assert final['status'] == 'emergency_unresolved'
    assert final['emergency_unresolved'] == ['issue-1']
    assert final['effective_issues'] == [original]


def test_confirmed_echo_and_new_detection_remain_usable():
    original = issue()
    echo = {**original, 'current_evidence': 'The current overlap is still visible.'}
    newly_confirmed = {**issue('S2'), 'id': 'issue-2'}
    uncertain = {**newly_confirmed, 'decision': 'uncertain'}
    assert effective_issue_rows([original, echo, uncertain, newly_confirmed]) == [echo, newly_confirmed]


@pytest.mark.parametrize('decision,classification', [('preserved', 'planar'), ('uncertain', 'uncertain')])
def test_explicit_s1_source_reclassification_remains_allowed(decision, classification):
    original = issue('S1')
    echo = {**original, 'decision': decision,
            'source_review': {'classification': classification,
                              'evidence': 'Reinspected original pixels: depth is not established.'}}
    assert effective_issue_rows([original, echo]) == [echo]
    assert open_issues({'issues': [original, echo], 'rcd': []}) == []


def test_partial_execution_and_preflight_rejection_keep_one_issue_open():
    original = issue('S2')
    good = {'program_id': 'good', 'issue_ids': ['issue-1'], 'status': 'changed_unverified'}
    rejected = {'program_id': 'bad', 'issue_ids': ['issue-1'], 'status': 'rejected_before_execution'}
    result = {'issues': [original], 'rcd': [good], 'rejected_programs': [rejected]}
    assert [row['id'] for row in open_issues(result)] == ['issue-1']
    assert result['rcd'] == [good]


def test_successful_followup_supersedes_old_rejection_without_reopening_issue():
    original = issue('S2')
    rejected = {'program_id': 'bad', 'issue_ids': ['issue-1'], 'status': 'rejected_before_execution'}
    result = {'status': 'emergency_unresolved', 'coverage': {'records_complete': True},
              'issues': [original], 'images': {}, 'rcd': [], 'rejected_programs': [rejected],
              'followup': {'status': 'completed', 'issue_ids': ['issue-1']}}
    committed = {'program_id': 'fixed', 'issue_ids': ['issue-1'], 'status': 'changed_unverified'}
    final = reconcile_followup(result, {'images': {}, 'rcd': [committed]})
    assert final['status'] == 'visual_review_pending'
    assert final['emergency_unresolved'] == []
    assert final['rejected_programs'] == [rejected]
    assert open_issues(final) == []


def test_followup_for_another_issue_retains_mixed_receipt_failure():
    original = issue('S2')
    other = {**original, 'id': 'issue-2'}
    good = {'program_id': 'good', 'issue_ids': ['issue-1'], 'status': 'changed_unverified'}
    rejected = {'program_id': 'bad', 'issue_ids': ['issue-1'], 'status': 'rejected_before_execution'}
    result = {'status': 'emergency_unresolved', 'coverage': {'records_complete': True},
              'issues': [original, other], 'images': {}, 'rcd': [good], 'rejected_programs': [rejected],
              'followup': {'status': 'completed', 'issue_ids': ['issue-2']}}
    committed = {'program_id': 'fixed', 'issue_ids': ['issue-2'], 'status': 'changed_unverified'}
    final = reconcile_followup(result, {'images': {}, 'rcd': [committed]})
    assert final['status'] == 'emergency_unresolved'
    assert final['emergency_unresolved'] == ['issue-1']
    assert [row['id'] for row in open_issues(final)] == ['issue-1']


@pytest.mark.integration
def test_followup_neighbor_edit_invalidates_prior_separation_on_final_svg(tmp_path):
    from figfox_plus.native.document import measure, parse
    from figfox_plus.native.review_problem_first_v13.followup import _audit_prior_geometry
    from figfox_plus.native.review_problem_first_v13.programs import execute_programs
    from figfox_plus.state import write_json

    svg, png = tmp_path / 'input.svg', tmp_path / 'input.png'
    svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="100" height="80">'
                   '<rect id="frame" width="100" height="80" fill="white"/>'
                   '<rect id="a" x="5" y="20" width="20" height="20" fill="red"/>'
                   '<rect id="b" x="40" y="20" width="20" height="20" fill="blue"/></svg>', encoding='utf-8')
    measure(parse(svg.read_text(encoding='utf-8')), png)
    images = {'sample': {'svg': str(svg), 'png': str(png), 'original': str(png),
                         'revision': hashlib.sha256(svg.read_bytes()).hexdigest()}}
    issues = [issue(), {**issue(), 'id': 'issue-2', 'target_ids': ['b'], 'neighbor_ids': ['frame']}]

    def program(ident, ref, target, x, relation, revision):
        return {'id': ident, 'issue_ids': [ref], 'image_id': 'sample', 'base_revision': revision,
                'phase': 'reconstructor', 'route': 'module_program', 'target_ids': [target],
                'depends_on': [], 'rcd_predescription': 'Preserve the source relation.',
                'args': {'operations': [{'method': 'bp_patch', 'target_ids': [target],
                                         'args': {'attributes': {'x': str(x)}}}]},
                'relations': [relation], 'convergence': {'max_iterations': 2, 'repairs': []}}

    first = program('first', 'issue-1', 'a', 5,
                    {'id': 'apart', 'predicate': 'separate', 'subject_id': 'a', 'object_id': 'b',
                     'min_gap': 1, 'reference_evidence': 'Original objects are separated.'}, images['sample']['revision'])
    root = tmp_path / 'review'
    before = execute_programs([first], issues, images, root / 'phase-2/execution')
    write_json(root / 'phase-2/normalized-programs.json', [first])
    assert before['rcd'][0]['final_scene_check']['status'] == 'measured_converged'
    current = {key: dict(value, original=str(png)) for key, value in before['images'].items()}
    second = program('second', 'issue-2', 'b', 10,
                     {'id': 'inside', 'predicate': 'contain', 'subject_id': 'b', 'object_id': 'frame',
                      'padding': 1, 'reference_evidence': 'Original b is inside the frame.'}, current['sample']['revision'])
    after = execute_programs([second], issues, current, tmp_path / 'followup/execution')
    assert after['rcd'][0]['final_scene_check']['status'] == 'measured_converged'
    result = {'status': 'emergency_unresolved', 'coverage': {'records_complete': True},
              'issues': issues, 'images': current, 'rcd': before['rcd'],
              'followup': {'status': 'completed', 'issue_ids': ['issue-2']}}
    saved = json.dumps(after, sort_keys=True)
    checks = _audit_prior_geometry(root, result, after, {'issue-2'})
    result['followup']['prior_scene_checks'] = checks
    final = reconcile_followup(result, after)
    assert final['status'] == 'emergency_unresolved'
    assert final['emergency_unresolved'] == ['issue-1']
    assert checks['first']['status'] == 'unresolved'
    assert checks['first']['history'][0]['failed'] == ['apart']
    assert checks['first']['revision'] == after['images']['sample']['revision']
    assert result['rcd'][0]['final_scene_check']['status'] == 'measured_converged'
    assert json.dumps(after, sort_keys=True) == saved
