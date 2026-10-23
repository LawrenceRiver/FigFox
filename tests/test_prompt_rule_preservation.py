"""Offline captures of actual first, DS2 and receipt-followup model payloads."""
import hashlib
import json
from pathlib import Path

import pytest
from PIL import Image
from figfox_plus.native import chain, pipeline
from figfox_plus.native.capability_prompts import block_hashes, blocks

SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect id="a" x="1" y="1" width="20" height="20" fill="red"/></svg>'
FIRST_RULES = (
    'Supplementary base frames (prioritize irregular shapes)',
    'After completing the content inside each base frame, refit inside the frame once',
    'Whole Section: Equipartition / Symmetry Basis',
    'use polylines (L/H/V)',
    'Use a single Q only when the corner itself',
    'If the original figure features a sweeping curve, keep C',
    'every object visible in the original figure must have an actual visible implementation',
    'gradients and opacity in the original figure cannot simply be treated as a single flat color',
    'Add data-plus-kind="frame" and stable IDs to all base frames and supplementary frames',
    'Original Figure Object - Constructed Element ID - SAM Asset ID',
    'do not delete the entire mixed group',
    'Do not center or stretch images individually',
)
REPAIR_RULES = (
    'For F, repair according to the identified reason',
    'do not shrink content into an overly small frame',
    'Move the element only when the identified issue is positional',
    'Ellipses and dashed lines must follow the row they belong to',
    'Both symmetric sides must be modified',
    'Move formulas as a whole unit, not individual glyphs',
    'Echo back issues as-is; do not add new issues',
    'Programs containing only D or only S2 must have depends_on as an empty array []',
    'Highest priority: zero tolerance for E (Alignment and Symmetry) and F (Overlap and Overflow)',
    'Passing two consecutive times is required for measured convergence',
)


@pytest.mark.parametrize('sam,code', [(False,False),(False,True),(True,False),(True,True)])
def test_actual_first_ds2_followup_preserve_validated_rules(tmp_path, monkeypatch, sam, code):
    original=tmp_path/'original.png'
    Image.new('RGB',(100,100),'white').save(original)
    policy={'version':'capabilities-v1','sam':sam,'code_methods':code}
    # Synthetic zero-assets SAM capability; never a real SAM/research result.
    monkeypatch.setattr(pipeline,'prepare_assets',lambda *a,**k: {
        'assets':[], 'status':{'sam':'ok'},
        'source_hash':hashlib.sha256(original.read_bytes()).hexdigest()})
    captured={'first':[], 'review':[]}
    def first_sender(prompt, images, folder, purpose):
        captured['first'].append((prompt,images))
        return SVG
    def review_sender(messages, tools, folder, **kwargs):
        captured['review'].append(json.loads(json.dumps(messages)))
        issue={'id':'synthetic-i','image_id':'case','category':'F','decision':'confirmed',
               'target_ids':['a'],'neighbor_ids':[], 'description':'synthetic overflow',
               'original_evidence':'synthetic original','current_evidence':'synthetic current'}
        return {'role':'assistant','content':json.dumps({'issues':[issue],'programs':[]})}
    chain.run_chain(original,tmp_path/'chain',image_id='case',rerun_authorization='synthetic-only',
                    capabilities=policy,first_sender=first_sender,review_sender=review_sender)
    assert len(captured['first'])==1 and len(captured['review'])==3
    first,images=captured['first'][0]
    assert images==[original]
    missing=[f'first: {rule}' for rule in FIRST_RULES if rule not in first]
    ds2=captured['review'][1][-1]['content']
    followup=captured['review'][2][0]['content']
    (tmp_path/'prompt-capture.json').write_text(json.dumps({
        'capabilities':policy,'block_hashes':block_hashes(policy),
        'first':first,'ds2':ds2,'followup':followup,'first_attachment_count':len(images),
        'review_call_count':len(captured['review'])},ensure_ascii=False,indent=2))
    for stage,prompt in [('DS2',ds2),('followup',followup)]:
        for rule in REPAIR_RULES:
            if rule not in prompt: missing.append(f'{stage}: {rule}')
    assert not missing, 'Actual captured payloads lost validated rules: ' + '; '.join(missing)
    assert 'Attachment order: original only; no SAM crops or overview board are attached.' in first
    for prompt in (ds2,followup):
        assert 'code_methods is false' in prompt
        assert 'repairs: []' in prompt
    for prompt in (first,ds2,followup):
        for key,value in blocks(policy).items():
            assert value in prompt, f'actual payload missing shared block {key}'
    if not code:
        for messages in captured['review']:
            serialized=json.dumps(messages)
            assert 'def cuboid' not in serialized
            assert 'CURRENT_TP' not in serialized


def test_all_four_cells_share_full_quality_and_conditional_policy():
    rows=[block_hashes({'version':'capabilities-v1','sam':s,'code_methods':c})
          for s in (False,True) for c in (False,True)]
    for key in ('common_quality','common_conditional_policy'):
        assert len({r[key] for r in rows})==1
    assert len({r['availability_manifest'] for r in rows})==4
    assert len(blocks(None)['common_quality'])>15000, 'full validated P4 rules were condensed'


def test_full_first_rules_have_only_traceable_applicability_adaptations():
    from figfox_plus.state import PLUS_ROOT
    from figfox_plus.native.capability_prompts import FIRST_RULE_ADAPTATIONS
    restored=blocks(None)['common_quality']
    for original,replacement in reversed(FIRST_RULE_ADAPTATIONS):
        assert restored.count(replacement)==1
        restored=restored.replace(replacement,original)
    assert restored==(PLUS_ROOT/'prompts/first_native.md').read_text()


def test_full_repair_contract_and_followup_rules_are_active():
    from figfox_plus.native.capability_prompts import repair_prompt
    from figfox_plus.native.review_problem_first_v13.lean_inspection import REPAIR_PROMPT
    from figfox_plus.native.review_problem_first_v13.orchestrator import PROGRAM_CONTRACT
    from figfox_plus.native.review_problem_first_v13.followup import PROMPT
    full=repair_prompt(None)
    assert REPAIR_PROMPT in full
    assert PROGRAM_CONTRACT in full
    followup=repair_prompt(None,followup=True)
    assert PROMPT.replace('route:module_program,target_ids','route:module_program|generated_python,target_ids').replace(
        'rcd_predescription,args,relations?','rcd_predescription,args?,source_code?,relations?') in followup
    for stage in (False,True):
        off=repair_prompt({'version':'capabilities-v1','sam':False,'code_methods':False},followup=stage)
        assert 'route:module_program|' not in off
        assert 'route:generated_python' in off



def test_actual_sam_attachment_manifest_lists_only_supplied_images(tmp_path):
    original=tmp_path/'original.png'
    crop=tmp_path/'crop.png'
    Image.new('RGB',(100,100),'white').save(original)
    Image.new('RGB',(10,10),'blue').save(crop)
    source_hash=hashlib.sha256(original.read_bytes()).hexdigest()
    asset={'id':'fixture-photo','role':'picture','path':str(crop),'source_crop':[10,10,10,10],
           'source_hash':source_hash,'asset_hash':hashlib.sha256(crop.read_bytes()).hexdigest()}
    captured=[]
    def sender(prompt, images, *args):
        captured.append((prompt,images))
        return SVG
    (tmp_path/'first').mkdir()
    pipeline.first(original,tmp_path/'first',send=sender,
                   sam={'assets':[asset],'status':{'sam':'ok'},'source_hash':source_hash},
                   capabilities={'version':'capabilities-v1','sam':True,'code_methods':False})
    prompt,images=captured[0]
    manifest=json.loads(prompt.split('Actual attachment manifest (in order): ')[1])
    assert manifest==['original','SAM picture crop fixture-photo','annotated overview P-board-01.png']
    assert len(images)==len(manifest)
    assert images[:2]==[original,crop]
