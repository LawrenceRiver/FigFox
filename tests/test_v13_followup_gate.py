"""The extra request opens only for priority issues that did not land."""
import pytest

from figfox_plus.native.review_problem_first_v13.followup import open_issues, reconcile_followup


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


def test_final_receipt_clears_stale_status_but_not_failed_history():
    result={'status':'emergency_unresolved','coverage':{'records_complete':True},
        'issues':[issue('F-1','F')],'images':{'sample':{'svg':'old.svg'}},
        'rcd':[{'issue_ids':['F-1'],'status':'failed'}],
        'followup':{'status':'completed'},'visual_passed':False}
    state={'images':{'sample':{'svg':'final.svg'}},'rcd':[{'issue_ids':['F-1'],
        'status':'changed_unverified','final_scene_check':{'status':'measured_converged'}}]}
    final=reconcile_followup(result,state)
    assert final['status']=='visual_review_pending'
    assert final['images']==state['images']
    assert final['rcd'][0]['status']=='failed'
    assert result['status']=='emergency_unresolved'
    assert final['visual_passed'] is False
    state['rcd'][0]['final_scene_check']['status']='unresolved'
    assert reconcile_followup(result,state)['status']=='emergency_unresolved'
    state['rcd'][0]['final_scene_check']['status']='measured_converged'
    state['rcd'].append({'issue_ids':['F-1'],'status':'failed'})
    assert reconcile_followup(result,state)['status']=='emergency_unresolved'


def test_rejection_does_not_invalidate_other_issue_or_reopen_it():
    result={'status':'emergency_unresolved','coverage':{'records_complete':True},
        'issues':[issue('F-1','F'),issue('F-2','F')], 'images':{'sample':{'svg':'old.svg'}},
        'rcd':[], 'followup':{'status':'completed','issue_ids':['F-1','F-2'],
        'rejected':['bad'],'rejected_programs':[{'program_id':'bad','issue_ids':['F-2'],
                                              'status':'rejected_before_execution'}]}}
    state={'images':{'sample':{'svg':'new.svg'}},'rcd':[{'program_id':'good','issue_ids':['F-1'],
        'status':'changed_unverified','final_scene_check':{'status':'measured_converged'}}]}
    final=reconcile_followup(result,state)
    assert final['emergency_unresolved']==['F-2']
    assert [i['id'] for i in open_issues(final)]==['F-2']
    final['followup']={'status':'completed','issue_ids':['F-2'],'rejected':[]}
    next_state={'images':{'sample':{'svg':'final.svg'}},'rcd':[{'issue_ids':['F-2'],
        'status':'changed_unverified','final_scene_check':{'status':'measured_converged'}}]}
    assert reconcile_followup(final,next_state)['status']=='visual_review_pending'


def test_same_issue_partial_success_does_not_mask_rejected_program():
    result={'issues':[issue('S2-1','S2')], 'rcd':[
        {'issue_ids':['S2-1'],'status':'changed_unverified'},
        {'issue_ids':['S2-1'],'status':'failed'}]}
    assert [i['id'] for i in open_issues(result)]==['S2-1']


@pytest.mark.parametrize('category,allowed', [('F',True), ('E',True), ('S1',True), ('S2',True),
                                             ('B',False), ('A',False), ('D',False)])
def test_automatic_followup_keeps_upstream_priority_categories(category, allowed):
    result = {'issues':[issue('unresolved',category)], 'rcd':[]}
    assert bool(open_issues(result)) is allowed


def test_followup_crops_use_latest_render_not_bundle_snapshot(tmp_path,monkeypatch):
    import json
    import pytest
    from PIL import Image
    from figfox_plus.native.review_problem_first_v13 import orchestrator,followup
    root=tmp_path/'review';root.mkdir();out=tmp_path/'next'
    latest=tmp_path/'latest.png';Image.new('RGB',(12,10),'blue').save(latest)
    stale=tmp_path/'stale.png';Image.new('RGB',(6,5),'red').save(stale)
    svg=tmp_path/'latest.svg';svg.write_text('<svg/>')
    result={'issues':[issue('F-1','F')],'rcd':[],
            'images':{'sample':{'svg':str(svg),'png':str(latest),'revision':'latest'}}}
    pair={'pair_id':'frame','display_mapping':{'current':[2,3,8,8]},
          'original_asset':{'path':str(stale)},'current_asset':{'path':str(stale),'asset_id':'crop'}}
    data={'result':result,'inputs':{'images':{'sample':{'original_png':{'path':str(stale)},'crop_pairs':[pair]}}},
          'schedule':{},'methods':{}}
    for name,value in data.items():(root/(name+'.json')).write_text(json.dumps(value))
    monkeypatch.setattr(orchestrator,'_image',lambda asset:[])
    monkeypatch.setattr(orchestrator,'_tools_for',lambda *a,**k:[])
    def stop(*a,**k):raise RuntimeError('no paid call')
    with pytest.raises(RuntimeError,match='no paid call'):
        followup.run_followup(root,out,sender=stop)
    with Image.open(out/'current-crop-000.png') as actual:
        assert actual.size==(6,5) and actual.getpixel((0,0))==(0,0,255)
    assert json.loads((out/'current-crops.json').read_text())[0]['revision']=='latest'
