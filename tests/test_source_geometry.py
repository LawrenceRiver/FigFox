import copy
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
import pytest

from figfox_plus.native import chain, pipeline
from figfox_plus.native.review_problem_first_v13 import orchestrator
from figfox_plus.native.review_problem_first_v13.followup import open_issues, reconcile_followup
from figfox_plus.native.review_problem_first_v13.inspection_contract import inspection_regions
from figfox_plus.native.review_problem_first_v13.issues import effective_issue_rows
from figfox_plus.native.review_problem_first_v13.lean_inspection import CATEGORIES
from figfox_plus.native.review_problem_first_v13.programs import execute_programs
from figfox_plus.native.review_problem_first_v13.replay import select_valid_programs
from figfox_plus.native.review_problem_first_v13.source_geometry import check_source_geometry, SourceGeometryUnverified


FRONT = [[20, 40], [80, 40], [80, 90], [20, 90]]
TOP = [[20, 40], [80, 40], [96, 26], [36, 26]]
SVG = ('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="110" viewBox="0 0 120 110">'
       '<rect id="body" x="20" y="40" width="60" height="50" fill="#dedede" stroke="black"/>'
       '<text id="label" x="12" y="104" font-size="10">x1</text></svg>')


def source(path, kind='outline'):
    image = Image.new('RGB', (120, 110), 'white')
    draw = ImageDraw.Draw(image)
    if kind != 'planar':
        draw.polygon([tuple(p) for p in TOP], fill='#aaaabb', outline='black' if kind == 'outline' else None)
        draw.polygon([(80,40),(80,90),(96,76),(96,26)], fill='#8b8b98',
                     outline='black' if kind == 'outline' else None)
    draw.polygon([tuple(p) for p in FRONT], fill='#dedede', outline='black' if kind != 'fill' else None)
    draw.text((12, 94), 'x1', fill='black')
    image.save(path)


def evidence():
    return {'basis': 'original_pixels', 'classification': 'cuboid',
            'evidence': 'The original block has a front face and a top face sharing its upper edge.',
            'front_face': copy.deepcopy(FRONT), 'adjacent_face': copy.deepcopy(TOP)}


def fixture(tmp_path, kind='outline'):
    tmp_path.mkdir(parents=True, exist_ok=True)
    svg = tmp_path / 'input.svg'
    svg.write_text(SVG, encoding='utf-8')
    current = tmp_path / 'current.png'
    original = tmp_path / 'original.png'
    source(current, 'planar')
    source(original, kind)
    return {'sample': {'svg': str(svg), 'png': str(current), 'original': str(original),
                       'revision': hashlib.sha256(svg.read_bytes()).hexdigest()}}


def issue(ident='S1-1', category='S1', target='body', image_id='sample'):
    return {'id': ident, 'image_id': image_id, 'category': category, 'decision': 'confirmed',
            'description': 'Missing depth' if category == 'S1' else 'Incorrect subscript',
            'original_evidence': 'Original object structure.', 'current_evidence': 'Current structure differs.',
            'target_ids': [target], 'neighbor_ids': []}


def geometry(images, proof=True):
    im = next(iter(images))
    op = {'method': 'sp_replace', 'target_ids': ['body'], 'args': {
        'kind': 'geometry', 'data': {'shape': 'cuboid', 'origin': [20,40], 'u': [60,0], 'v': [0,50],
                                     'depth': [16,-14], 'stroke': 'black', 'stroke_width': 1,
                                     'colors': {'front': '#dedede','top': '#aaaabb','right': '#8b8b98'}},
        'measurement_viewport': {'left': 0,'top': 0,'right': 120,'bottom': 110},
        'target_tp': {'left': 20,'top': 26,'right': 96,'bottom': 90}, 'mode': 'contain',
        'parent_id': None, 'before_id': '', 'after_id': None}}
    if proof:
        op['source_geometry'] = evidence()
    return {'id': 'solid', 'image_id': im, 'issue_ids': ['S1-1'], 'base_revision': images[im]['revision'],
            'phase': 'reconstructor', 'route': 'module_program', 'target_ids': ['body'],
            'depends_on': None, 'when': None, 'relations': None, 'args': {'operations': [op]}}


def text_program(images):
    im = next(iter(images))
    return {'id': 'formula', 'image_id': im, 'issue_ids': ['B-1'], 'base_revision': images[im]['revision'],
            'phase': 'reconstructor', 'route': 'module_program', 'target_ids': ['label'],
            'args': {'operations': [{'method': 'bp_patch','target_ids': ['label'],
                                     'args': {'text': 'x₁','parent_id': None}}]}}


@pytest.mark.parametrize('kind', ['outline', 'fill'])
@pytest.mark.parametrize('shape', ['cuboid', 'lattice'])
def test_real_depth_is_allowed_even_when_current_body_is_rectangular(tmp_path, kind, shape):
    images = fixture(tmp_path, kind)
    raw = geometry(images)
    raw['args']['operations'][0]['args']['data']['shape'] = shape
    if shape == 'lattice':
        raw['args']['operations'][0]['args']['data']['divisions'] = [1, 2, 1]
    accepted, rejected = select_valid_programs([raw], [issue()], images)
    assert not rejected and len(accepted) == 1
    assert accepted[0]['source_geometry_checks'][0]['status'] == 'edges_supported'
    assert accepted[0]['source_geometry_checks'][0]['visual_acceptance'] == 'pending'
    assert raw['args']['operations'][0]['args']['parent_id'] is None
    assert 'parent_id' not in accepted[0]['args']['operations'][0]['args']


@pytest.mark.parametrize('proof', [True, False])
def test_planar_source_cannot_gain_invented_depth(tmp_path, proof):
    images = fixture(tmp_path, 'planar')
    raw = geometry(images, proof)
    raw['source_geometry_checks'] = [{'status':'edges_supported','source_sha256':'forged-host-receipt'}]
    before = Path(images['sample']['svg']).read_bytes()
    accepted, rejected = select_valid_programs([raw], [issue()], images)
    assert not accepted and rejected[0]['status'] == 'deferred_source_geometry'
    assert rejected[0]['original_preserved'] is True
    assert rejected[0]['automatic_network_retry'] is False
    assert Path(images['sample']['svg']).read_bytes() == before
    if proof:
        assert 'lack original-pixel support' in rejected[0]['error']
        assert rejected[0]['source_geometry_check']['source_sha256'] == hashlib.sha256(
            Path(images['sample']['original']).read_bytes()).hexdigest()


def test_two_planar_grid_cells_cannot_prove_depth(tmp_path):
    images = fixture(tmp_path, 'planar')
    with Image.open(images['sample']['original']) as image:
        ImageDraw.Draw(image).rectangle((80, 40, 110, 90), fill='#aaaabb', outline='black')
        image.save(images['sample']['original'])
    raw = geometry(images)
    raw['args']['operations'][0]['source_geometry']['adjacent_face'] = [[80,40],[80,90],[110,90],[110,40]]
    with pytest.raises(SourceGeometryUnverified, match='planar divisions'):
        check_source_geometry(raw, images['sample']['original'])


def test_nearby_horizontal_borders_cannot_substitute_for_diagonal_depth(tmp_path):
    images = fixture(tmp_path, 'planar')
    with Image.open(images['sample']['original']) as image:
        draw=ImageDraw.Draw(image)
        draw.line([(10,31),(110,31)],fill='black',width=5)
        draw.line([(20,40),(80,40)],fill='black',width=5)
        image.save(images['sample']['original'])
    raw=geometry(images)
    raw['args']['operations'][0]['source_geometry']['adjacent_face']=[[20,40],[80,40],[91,31],[31,31]]
    accepted,rejected=select_valid_programs([raw],[issue()],images)
    assert not accepted and rejected[0]['status']=='deferred_source_geometry'
    assert 'declared directions' in rejected[0]['error']


@pytest.mark.parametrize('bad', ['unknown_basis','uncertain','crossed','outside','nonfinite','overlapping','disconnected'])
def test_invalid_source_evidence_defers_locally(tmp_path, bad):
    images = fixture(tmp_path)
    raw = geometry(images)
    proof = raw['args']['operations'][0]['source_geometry']
    if bad == 'unknown_basis':proof['basis'] = 'current_tp'
    elif bad == 'uncertain':proof['classification'] = 'uncertain'
    elif bad == 'crossed':proof['front_face'][1],proof['front_face'][2] = proof['front_face'][2],proof['front_face'][1]
    elif bad == 'outside':proof['front_face'][0][0] = -2
    elif bad == 'nonfinite':proof['front_face'][0][0] = float('nan')
    elif bad == 'overlapping':proof['adjacent_face'] = [[20,40],[80,40],[96,54],[36,54]]
    else:proof['adjacent_face'] = [[22,35],[82,35],[98,21],[38,21]]
    accepted, rejected = select_valid_programs([raw], [issue()], images)
    assert not accepted and rejected[0]['status'] == 'deferred_source_geometry'


def test_nested_operations_and_cluster_members_all_need_source_proof(tmp_path):
    images = fixture(tmp_path)
    raw = geometry(images)
    op = raw['args']['operations'][0]
    data = op['args']['data']
    op['args']['data'] = {'shape': 'cluster', 'items': [copy.deepcopy(data), copy.deepcopy(data)]}
    op['source_geometry'] = [evidence(), None]
    raw['args']['operations'] = [{'method': 'bp_program','target_ids': ['body'],'args': {'operations': [op]}}]
    accepted, rejected = select_valid_programs([raw], [issue()], images)
    assert not accepted and rejected[0]['status'] == 'deferred_source_geometry'


@pytest.mark.parametrize('decision', ['uncertain', 'preserved'])
def test_unconfirmed_source_must_not_be_repaired_even_with_a_valid_face_claim(tmp_path, decision):
    images = fixture(tmp_path)
    row = issue()
    row['decision'] = decision
    accepted, rejected = select_valid_programs([geometry(images)], [row], images)
    assert not accepted and rejected[0]['status'] == 'deferred_source_geometry'


def test_unknown_anchor_is_not_silently_removed(tmp_path):
    images = fixture(tmp_path)
    raw = geometry(images)
    raw['args']['operations'][0]['args']['parent_id'] = 'missing-parent'
    accepted, rejected = select_valid_programs([raw], [issue()], images)
    assert not accepted and 'unknown' in rejected[0]['error']


def test_generated_code_cannot_bypass_the_typed_s1_source_guard(tmp_path):
    images=fixture(tmp_path)
    raw=geometry(images)
    raw.update(route='generated_python',source_code='raise RuntimeError("must not execute")')
    accepted,rejected=select_valid_programs([raw],[issue()],images)
    assert not accepted and rejected[0]['status'] == 'deferred_source_geometry'
    assert 'independent original-pixel face evidence' in rejected[0]['error']


def test_source_deferral_keeps_the_original_one_time_followup_eligibility():
    s, b = issue(), issue('B-1', 'B', 'label')
    deferred = {'program_id': 'solid','issue_ids': ['S1-1'], 'status': 'deferred_source_geometry',
                'automatic_followup_allowed': False}
    result = {'issues': [s,b], 'rcd': [], 'rejected_programs': [deferred]}
    assert [i['id'] for i in open_issues(result)] == ['S1-1']
    result['rejected_programs'][0]['issue_ids'].append('B-1')
    assert [i['id'] for i in open_issues(result)] == ['S1-1']


@pytest.mark.parametrize('decision,classification', [('preserved','planar'),('uncertain','uncertain')])
def test_detection_can_be_retracted_only_with_explicit_source_reinspection(decision, classification):
    original = issue()
    review = {**original, 'decision': decision}
    assert effective_issue_rows([original, review]) == [original]
    review['source_review'] = {'classification': classification,'evidence': 'Rechecked original: no reliable depth edges.'}
    assert effective_issue_rows([original, review]) == [review]
    assert original['decision'] == 'confirmed'
    assert not open_issues({'issues': [original, review], 'rcd': []})


def test_followup_can_preserve_a_false_detection_without_a_fake_execution():
    before = issue()
    after = {**before,'decision': 'preserved','source_review': {'classification': 'planar','evidence': 'Only a divided rectangle in original.'}}
    result = {'status': 'emergency_unresolved','issues': [before], 'rcd': [],'images': {},
              'coverage': {'records_complete': True},'followup': {'status': 'completed','issue_ids': ['S1-1'],
                                                                 'effective_issues': [after]}}
    final = reconcile_followup(result, {'images': {}, 'rcd': []})
    assert final['status'] == 'visual_review_pending' and not final['emergency_unresolved']
    assert final['visual_passed'] is False and not final['rcd']
    assert final['issues'][0]['decision'] == 'confirmed'


@pytest.mark.integration
def test_genuine_cuboid_constructs_and_renders_with_a_source_receipt(tmp_path):
    images = fixture(tmp_path / 'input')
    accepted, rejected = select_valid_programs([geometry(images)], [issue()], images)
    assert not rejected
    result = execute_programs(accepted, [issue()], images, tmp_path / 'execution')
    assert result['rcd'][0]['status'] == 'changed_unverified'
    assert result['rcd'][0]['source_geometry_checks'][0]['status'] == 'edges_supported'
    with Image.open(result['images']['sample']['png']) as rendered:
        assert rendered.size == (120,110)
        rendered.verify()


@pytest.mark.integration
@pytest.mark.parametrize('route', ['module_program', 'generated_python'])
def test_supported_s1_repairs_keep_native_and_generated_routes(tmp_path, route):
    images = fixture(tmp_path / 'input')
    raw = geometry(images)
    raw['source_geometry'] = evidence()
    raw['args'] = {'operations':[{'method':'bp_patch','target_ids':['body'], 'args':{'attributes':{'fill':'#999999'}}}]}
    if route == 'generated_python':
        raw['route'] = route
        raw.pop('args')
        raw['source_code'] = ('import xml.etree.ElementTree as ET\n'
            'tree = ET.parse(INPUT_SVG)\n'
            'for node in tree.getroot().iter():\n'
            '    if node.get("id") == "body": node.set("fill", "#999999")\n'
            'tree.write(OUTPUT_SVG, encoding="unicode")\n')
    accepted, rejected = select_valid_programs([raw], [issue()], images)
    assert not rejected and len(accepted) == 1
    result = execute_programs(accepted, [issue()], images, tmp_path / 'execution')
    assert result['rcd'][0]['status'] == 'changed_unverified'
    assert not result.get('candidate_only')
    assert next(n for n in ET.parse(result['images']['sample']['svg']).iter() if n.get('id') == 'body').get('fill') == '#999999'


@pytest.mark.integration
def test_low_contrast_depth_renders_a_candidate_without_losing_canonical_repairs(tmp_path):
    from figfox_plus.native.review_problem_first_v13.candidates import source_candidates
    images = fixture(tmp_path / 'input', 'fill')
    original = Path(images['sample']['original'])
    with Image.open(original) as image:
        image.point(lambda value: round(255 - (255-value)*.025)).save(original)
    raw = geometry(images)
    raw['candidate_only'] = True  # A model-supplied flag cannot bypass the canonical guard.
    programs = [raw, text_program(images)]
    issues = [issue(), issue('B-1','B','label')]
    before = Path(images['sample']['svg']).read_bytes()
    accepted, rejected = select_valid_programs(programs, issues, images)
    assert [p['id'] for p in accepted] == ['formula']
    candidates = source_candidates(programs, issues, images, tmp_path/'candidates', rejected)
    assert len(candidates) == 1 and candidates[0]['status'] == 'available'
    assert candidates[0]['automatically_adopted'] is False and candidates[0]['model_requests'] == 0
    with Image.open(candidates[0]['images']['sample']['png']) as image:
        assert image.size == (120,110)
        image.verify()
    assert Path(images['sample']['svg']).read_bytes() == before
    result = execute_programs(accepted, issues, images, tmp_path/'canonical')
    tree = ET.parse(result['images']['sample']['svg'])
    assert next(n for n in tree.iter() if n.get('id') == 'body').tag.endswith('rect')
    assert next(n for n in tree.iter() if n.get('id') == 'label').text == 'x₁'
    assert result['images']['sample']['svg'] != candidates[0]['images']['sample']['svg']


def test_candidate_cannot_bypass_planar_counterevidence_or_invalid_targets(tmp_path):
    from figfox_plus.native.review_problem_first_v13.candidates import source_candidates
    images = fixture(tmp_path)
    raw = geometry(images, proof=False)
    planar = {**issue(),'source_review':{'classification':'planar','evidence':'Original is a divided matrix.'}}
    accepted, rejected = select_valid_programs([raw], [planar], images, candidate_only=True)
    assert not accepted and source_candidates([raw],[planar],images,tmp_path/'planar',rejected) == []
    raw['target_ids'] = ['missing']
    accepted, rejected = select_valid_programs([raw],[issue()],images,candidate_only=True)
    assert not accepted and 'unknown current object' in rejected[0]['error']
    raw = geometry(images)
    raw['args']['operations'][0]['source_geometry']['classification'] = 'planar'
    accepted, rejected = select_valid_programs([raw],[issue()],images,candidate_only=True)
    assert not accepted and source_candidates([raw],[issue()],images,tmp_path/'explicit-planar-proof',rejected) == []


def test_candidate_failure_is_local_and_keeps_existing_output(tmp_path, monkeypatch):
    from figfox_plus.native.review_problem_first_v13 import candidates
    images = fixture(tmp_path)
    raw = geometry(images, proof=False)
    _, rejected = select_valid_programs([raw],[issue()],images)
    before = Path(images['sample']['svg']).read_bytes()
    def fail(*args, **kwargs):
        raise ValueError('synthetic candidate rendering failure')
    monkeypatch.setattr(candidates, 'execute_programs', fail)
    result = candidates.source_candidates([raw],[issue()],images,tmp_path/'candidate',rejected)
    assert result[0]['status'] == 'failed' and result[0]['images'] == {}
    assert Path(images['sample']['svg']).read_bytes() == before


@pytest.mark.integration
@pytest.mark.parametrize('disposition', ['deferred', 'preserved'])
def test_complete_chain_keeps_planar_body_and_executes_unrelated_repair(tmp_path, monkeypatch, disposition):
    images = fixture(tmp_path / 'input', 'planar')
    original = Path(images['sample']['original'])
    monkeypatch.setattr(pipeline,'prepare_assets',lambda *a,**k: {'assets': [],'status': {'sam': 'fixture'}})
    monkeypatch.setattr(chain,'call_gpt55',lambda *a,**k: SVG)
    calls = []

    def sender(messages, tools, root, **kw):
        calls.append(messages)
        assert len(calls) <= 3, 'Only the original one-time followup is allowed'
        inputs = json.loads((root/'inputs.json').read_text(encoding='utf-8'))
        image_id = next(iter(inputs['images']))
        rows = [issue(image_id=image_id), issue('B-1','B','label',image_id)]
        if len(calls) == 1:
            schedule = json.loads((root/'schedule.json').read_text(encoding='utf-8'))
            region = inspection_regions(schedule)[0]['region']
            sweeps = [{'category': c,'whole_image_observation': 'Compared original and current.',
                       'svg_observation': 'Read visible structure.', 'candidates': []} for c in CATEGORIES]
            for row in rows:
                sweep = next(s for s in sweeps if s['category'] == row['category'])
                sweep['candidates'].append({'region': region,'original_evidence': row['original_evidence'],
                                           'current_evidence': row['current_evidence'], 'decision': 'confirmed','issue_ids': [row['id']]})
            plan = {'compact_category_sweeps': sweeps,'issues': rows,'programs': []}
        elif len(calls) == 2:
            im = inputs['images'][image_id]
            current = {image_id: {'revision': im['current_revision']}}
            programs = [geometry(current, proof=False), text_program(current)]
            if disposition == 'preserved':
                rows[0].update(decision='preserved',source_review={'classification': 'planar','evidence': 'The original shows only planar cells and borders.'})
                programs.pop(0)
            plan = {'issues': rows,'programs': programs}
        else:
            assert 'followup' in root.name
            plan = {'issues': [rows[0]], 'programs': []}
        return {'role': 'assistant','content': json.dumps(plan, ensure_ascii=False)}

    out = tmp_path / 'run'
    chain.run_chain(original, out, image_id='sample', rerun_authorization='offline regression', review_sender=sender)
    result = json.loads((out/'review/sample/result.json').read_text(encoding='utf-8'))
    artifacts = json.loads((out/'artifacts.json').read_text(encoding='utf-8'))
    assert len(calls) == (3 if disposition == 'deferred' else 2)
    assert artifacts['artifact_status'] == 'available' and artifacts['visual_passed'] is False
    assert result['followup']['opened'] is (disposition == 'deferred')
    tree = ET.parse(out/'final.svg')
    body = next(n for n in tree.iter() if n.get('id') == 'body')
    assert body.tag.endswith('rect') and body.get('width') == '60'
    assert next(n for n in tree.iter() if n.get('id') == 'label').text == 'x₁'
    assert all(r['program_id'] != 'solid' for r in result['rcd'])
    assert result['status'] == ('source_verification_pending' if disposition == 'deferred' else 'visual_review_pending')
    assert result['issues'][0]['decision'] == 'confirmed'
    report=(out/'review/sample/index.html').read_text(encoding='utf-8')
    assert ('deferred_source_geometry' in report) if disposition=='deferred' else ('planar' in report)
    if disposition == 'deferred':
        assert result['repair_candidates'] == []
        assert not list(out.rglob('source-candidates'))
        assert '下载候选 SVG' not in report
    with Image.open(out/'final.png') as rendered:
        assert rendered.size == (120,110)
        rendered.verify()
