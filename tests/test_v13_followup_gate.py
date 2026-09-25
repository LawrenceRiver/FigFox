"""The extra request opens only for priority issues that did not land."""
from figfox_plus.native.review_problem_first_v13.followup import open_issues


def issue(ident, category):
    return {'id': ident, 'image_id': 'sample', 'category': category, 'decision': 'confirmed',
            'description': '待查', 'target_ids': ['a']}


def test_clear_receipt_does_not_open():
    result = {'issues': [issue('F-1', 'F'), issue('E-1', 'E'), issue('S1-1', 'S1'), issue('S2-1', 'S2'), issue('D-1', 'D')],
              'rcd': [
                  {'program_id': 'p1', 'issue_ids': ['F-1'], 'status': 'changed_unverified', 'final_scene_check': {'status': 'measured_converged'}},
                  {'program_id': 'p2', 'issue_ids': ['E-1'], 'status': 'changed_unverified', 'final_scene_check': {'status': 'measured_converged'}},
                  {'program_id': 'p3', 'issue_ids': ['S1-1'], 'status': 'changed_unverified'},
                  {'program_id': 'p4', 'issue_ids': ['S2-1'], 'status': 'changed_unverified'},
                  {'program_id': 'p5', 'issue_ids': ['D-1'], 'status': 'failed', 'error': 'arrow failed'},
              ]}
    assert open_issues(result) == []


def test_unlanded_overlap_alignment_geometry_and_photo_open_once_each():
    result = {'issues': [issue('F-1', 'F'), issue('F-2', 'F'), issue('E-1', 'E'), issue('S1-1', 'S1'), issue('S2-1', 'S2'), issue('S2-2', 'S2')],
              'rcd': [
                  {'program_id': 'pf', 'issue_ids': ['F-1'], 'status': 'failed', 'error': 'convergence limit reached'},
                  {'program_id': 'ok', 'issue_ids': ['F-2'], 'status': 'changed_unverified', 'final_scene_check': {'status': 'measured_converged'}},
                  {'program_id': 'pe', 'issue_ids': ['E-1'], 'status': 'changed_unverified', 'final_scene_check': {'status': 'unresolved'}},
                  {'program_id': 'ps', 'issue_ids': ['S1-1'], 'status': 'failed', 'error': 'construction TP is empty'},
                  {'program_id': 'photo-ok', 'issue_ids': ['S2-2'], 'status': 'changed_unverified'},
              ],
              'rejected_programs': [{'program_id': 'photo', 'issue_ids': ['S2-1'], 'status': 'rejected_before_execution', 'error': 'crop rejected'}]}
    opened = {row['id']: row['category'] for row in open_issues(result)}
    assert opened == {'F-1': 'F', 'E-1': 'E', 'S1-1': 'S1', 'S2-1': 'S2'}
