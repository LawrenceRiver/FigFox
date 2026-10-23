"""Capability guards exercise actual validation and sandbox entry points."""
import hashlib
import json
from pathlib import Path
import pytest
from figfox_plus.native.review_problem_first_v13 import programs, sandbox, methods

OFF={'version':'capabilities-v1','sam':False,'code_methods':False}
SVG='<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect id="a" x="1" y="1" width="20" height="20"/></svg>'
CODE='import xml.etree.ElementTree as ET\ntree=ET.parse(INPUT_SVG)\ntree.getroot()[0].set("fill","blue")\ntree.write(OUTPUT_SVG,encoding="unicode")\n'

def fixture(tmp_path,category='S1'):
    path=tmp_path/'input.svg';path.write_text(SVG)
    images={'im':{'svg':str(path),'revision':hashlib.sha256(path.read_bytes()).hexdigest(),'original':str(tmp_path/'original.png'),'png':str(tmp_path/'preview.png')}}
    issue={'id':'i','image_id':'im','category':category,'target_ids':['a'],'neighbor_ids':[],'description':'synthetic repair','original_evidence':'synthetic original','current_evidence':'synthetic current'}
    p={'id':'p','issue_ids':['i'],'image_id':'im','base_revision':images['im']['revision'],'phase':'reconstructor','route':'generated_python','target_ids':['a'],'depends_on':[],'source_code':CODE}
    return images,issue,p

@pytest.mark.parametrize('category',['S1','D'])
def test_off_s1_d_accept_real_stdlib_program(tmp_path,category):
    images,issue,p=fixture(tmp_path,category)
    assert programs.validate_programs([p],[issue],images,capabilities=OFF)['p']==[issue]

@pytest.mark.parametrize('extra',[{'route':'module_program','args':{'operations':[{'method':'bp_program','args':{'operations':[{'method':'sp_replace'}]}}]}}, {'convergence':{'repairs':[{'method':'tp_align'}]}}, {'args':{'fallback':{'method':'sp_photo'}}}])
def test_off_nested_methods_and_repairs_are_rejected(tmp_path,extra):
    images,issue,p=fixture(tmp_path);p.update(extra)
    with pytest.raises(ValueError,match='disabled'):
        programs.validate_programs([p],[issue],images,capabilities=OFF)


def test_method_pack_off_has_no_library_sources_or_tp():
    pack=methods.build_method_pack(capabilities=OFF)
    assert pack['sources']=={} and pack['constructors']==[]
    assert 'CURRENT_TP' not in json.dumps(pack)
    assert '$measure' not in json.dumps(pack)


def test_stdlib_sandbox_off_executes_visible_edit_without_mount(tmp_path):
    images,issue,p=fixture(tmp_path)
    receipt=sandbox.run_code(CODE,images['im']['svg'],tmp_path/'sandbox',capabilities=OFF,current_tp={'secret':123})
    assert receipt['status']=='executed',receipt
    assert 'blue' in Path(receipt['svg']).read_text()
    assert receipt['mounted_method_directories']==[]
    assert receipt['current_tp_exposed'] is False
    assert receipt['python_flags']==['-I','-S']

@pytest.mark.parametrize('code',['import figfox_plus','import numpy','import importlib; importlib.import_module("figfox_plus")','open("/tmp/figfox_plus/native/tp_v2.py").read()','import os as x; x.open("/tmp/file",0)','getattr(__builtins__, "__import__")("figfox_plus")'])
def test_off_import_and_source_read_guards(tmp_path,code):
    images,issue,p=fixture(tmp_path)
    receipt=sandbox.run_code(code,images['im']['svg'],tmp_path/'sandbox',capabilities=OFF)
    assert receipt['status']=='failed'
    assert 'disabled' in receipt['error']


def prepared_bundle(tmp_path):
    from PIL import Image
    import xml.etree.ElementTree as ET
    from figfox_plus.native.pipeline import stage
    from figfox_plus.native.chain import bundle_from_stage
    original=tmp_path/'original.png';Image.new('RGB',(100,100),'white').save(original)
    stage(ET.fromstring(SVG),original,tmp_path/'stage-0')
    return bundle_from_stage(tmp_path,original,'im')


def test_off_review_projection_and_frozen_resume(tmp_path,monkeypatch):
    from figfox_plus.native.review_problem_first_v13 import orchestrator,upstream_arrows
    bundle=prepared_bundle(tmp_path)
    monkeypatch.setattr(upstream_arrows,'freeze_arrow_evidence',lambda *a,**k:pytest.fail('SAM-off evidence opened'))
    task=tmp_path/'review'
    orchestrator.prepare(bundle,task,capabilities=OFF)
    messages=json.loads((task/'messages.json').read_text())
    texts='\n'.join(m['content'] if isinstance(m['content'],str) else '\n'.join(i.get('text','') for i in m['content']) for m in messages)
    for key in ('"current_tp"','current_diagnostics','current_line_facts','CURRENT_TP','def cuboid','current_line_alignment_candidates'):
        assert key not in texts
    assert 'current_svg' in texts and '1/2' in texts
    with pytest.raises(ValueError,match='frozen'):
        orchestrator.run(task,capabilities=dict(OFF,code_methods=True),sender=lambda *a,**k:pytest.fail('sender called'))


def test_off_full_review_followup_returns_terminal_committed_svg(tmp_path):
    from figfox_plus.native.review_problem_first_v13 import orchestrator
    bundle=prepared_bundle(tmp_path);task=tmp_path/'review'
    orchestrator.prepare(bundle,task,capabilities=OFF)
    images,issue,p=fixture(tmp_path)
    issue.update(decision='confirmed',description='synthetic wrong shape',original_evidence='synthetic original',current_evidence='synthetic current')
    p['base_revision']=bundle['images']['im']['current_revision']
    calls=[]
    def sender(messages,tools,folder,**kwargs):
        calls.append(messages)
        return {'role':'assistant','content':json.dumps({'issues':[issue],'programs':[p] if len(calls)==3 else []})}
    result=orchestrator.run(task,sender=sender,capabilities=OFF)
    assert len(calls)==3
    assert result['followup']['opened']
    terminal=result['images']['im']
    assert 'blue' in Path(terminal['svg']).read_text()
    assert terminal['revision']==hashlib.sha256(Path(terminal['svg']).read_bytes()).hexdigest()
    assert terminal==result['followup']['images']['im']
    assert result['visual_passed'] is False
    events=[json.loads(line) for path in task.parent.rglob('invocation-trace.jsonl') for line in path.read_text().splitlines()]
    assert not [e for e in events if e['category']=='code_intervention' and e['status']=='started']
    assert [e for e in events if e['method']=='program_transaction' and e['status']=='changed_unverified']

@pytest.mark.parametrize('category',['E','F'])
@pytest.mark.parametrize('correct',[True,False])
def test_off_readonly_geometry_guards_accept_or_rollback(tmp_path,category,correct):
    from PIL import Image
    images,issue,p=fixture(tmp_path,category)
    source=Path(images['im']['svg'])
    source.write_text(SVG.replace('</svg>','<rect id="b" x="30" y="40" width="20" height="20"/></svg>'))
    images['im']['revision']=hashlib.sha256(source.read_bytes()).hexdigest();p['base_revision']=images['im']['revision']
    Image.new('RGB',(100,100),'white').save(images['im']['original'])
    issue['neighbor_ids']=['b'];p['source_code']=CODE
    if category=='E':
        p['source_code']=CODE.replace('set("fill","blue")', 'set("y","'+('40' if correct else '10')+'")')
        p['convergence']={'max_iterations':6,'repairs':[],'alignment_checks':[{'id':'align','target_ids':['a'],'reference_ids':['b'],'mode':'top','tolerance':.5,'reference_evidence':'synthetic aligned tops'}]}
    else:
        p['source_code']=CODE.replace('set("fill","blue")','set("x","'+('1' if correct else '30')+'")')
        p['source_code']=p['source_code'].replace('tree.write','tree.getroot()[0].set("y","40")\ntree.write')
        p['relations']=[{'id':'apart','predicate':'separate','subject_id':'a','object_id':'b','min_gap':2,'reference_evidence':'synthetic separate rectangles'}]
        p['convergence']={'max_iterations':6,'repairs':[],'alignment_checks':[]}
    result=programs.execute_programs([p],[issue],images,tmp_path/'execute',capabilities=OFF)
    row=result['rcd'][0]
    if correct:
        assert row['status']=='changed_unverified',row
        assert row['final_scene_check']['status']=='measured_converged'
    else:
        assert row['status']=='failed' and row['rolled_back']
        assert result['images']['im']['revision']==images['im']['revision']


def test_off_scope_violation_rolls_back_actual_sandbox_edit(tmp_path):
    images,issue,p=fixture(tmp_path,'D')
    p['source_code']=CODE.replace('tree.getroot()[0].set("fill","blue")','tree.getroot().set("width","200")')
    result=programs.execute_programs([p],[issue],images,tmp_path/'execute',capabilities=OFF)
    assert result['rcd'][0]['rolled_back']
    assert result['images']['im']['revision']==images['im']['revision']


def test_sam_binding_is_independent_of_code_methods(tmp_path,monkeypatch):
    from PIL import Image
    from figfox_plus.native import pipeline
    original=tmp_path/'original.png';Image.new('RGB',(100,100),'white').save(original)
    asset=tmp_path/'asset.png';Image.new('RGB',(20,20),'green').save(asset)
    sam={'status':{'sam':'ok'},'source_hash':hashlib.sha256(original.read_bytes()).hexdigest(),'mock':True,'assets':[{'id':'asset_test','role':'picture','source_crop':[1,1,20,20],'path':str(asset),'source_hash':hashlib.sha256(original.read_bytes()).hexdigest(),'asset_hash':hashlib.sha256(asset.read_bytes()).hexdigest()}]}
    monkeypatch.setattr(pipeline,'sp_element',lambda *a,**k:pytest.fail('SP called'))
    monkeypatch.setattr(pipeline,'execute',lambda *a,**k:pytest.fail('code helpers called'))
    response=SVG.replace('</svg>','<image id="replacement" href="asset_test" x="1" y="1" width="20" height="20" data-plus-replaces="a"/></svg>')
    root=pipeline.first(original,tmp_path,send=lambda *a:response,sam=sam,capabilities=dict(OFF,sam=True))
    assert not any(n.get('id')=='a' for n in root.iter())
    assert any(n.get('href','').startswith('data:image/png;base64,') for n in root.iter())
    events=[json.loads(l) for l in (tmp_path/'invocation-trace.jsonl').read_text().splitlines()]
    assert any(e['category']=='sam_intervention' and e['status']=='completed' for e in events)
    assert not any(e['category']=='code_intervention' for e in events)


def test_first_rejects_tampered_sam_asset_before_sender(tmp_path):
    from PIL import Image
    from figfox_plus.native import pipeline
    original=tmp_path/'original.png';Image.new('RGB',(10,10)).save(original)
    sam={'status':{'sam':'ok'},'source_hash':'wrong','assets':[]}
    with pytest.raises(ValueError,match='SAM.*hash'):
        pipeline.first(original,tmp_path,sam=sam,capabilities=dict(OFF,sam=True),send=lambda *a:pytest.fail('sender reached'))


def test_off_runtime_audit_blocks_xml_parser_path_alias(tmp_path):
    images,issue,p=fixture(tmp_path)
    code=CODE.replace('ET.parse(INPUT_SVG)','ET.parse("/Users/lawrenceriver/Desktop/7月/plus/src/figfox_plus/native/tp_v2.py")')
    receipt=sandbox.run_code(code,images['im']['svg'],tmp_path/'sandbox',capabilities=OFF)
    assert receipt['status']=='failed'
    assert 'disabled file access' in receipt['log']


def test_on_module_method_has_actual_named_trace(tmp_path):
    from PIL import Image
    images,issue,p=fixture(tmp_path,'B');Image.new('RGB',(100,100)).save(images['im']['original'])
    p.update(route='module_program',args={'operations':[{'method':'bp_patch','target_ids':['a'],'args':{'attributes':{'fill':'blue'}}}]});p.pop('source_code')
    result=programs.execute_programs([p],[issue],images,tmp_path/'execute',capabilities=dict(OFF,code_methods=True))
    assert result['rcd'][0]['status']=='changed_unverified'
    rows=[json.loads(l) for l in (tmp_path/'execute/invocation-trace.jsonl').read_text().splitlines()]
    starts=[r for r in rows if r['category']=='code_intervention' and r['status']=='started']
    assert any(r['method']=='bp_patch' and r['before_revision'] and r['program_id']=='p' for r in starts)

@pytest.mark.parametrize('category',['S1','D'])
def test_off_constructs_actual_geometry_and_renders(tmp_path,category):
    from PIL import Image
    import xml.etree.ElementTree as ET
    images,issue,p=fixture(tmp_path,category);Image.new('RGB',(100,100),'white').save(images['im']['original'])
    shapes=([('polygon','front',{'points':'15,35 40,30 40,60 15,65','fill':'#a7c78d'}),('polygon','top',{'points':'15,35 25,20 50,15 40,30','fill':'#d3e4c4'}),('polygon','side',{'points':'40,30 50,15 50,45 40,60','fill':'#789765'})] if category=='S1' else [('path','shaft',{'d':'M10 40 L60 40','stroke':'black','stroke-width':'2','fill':'none'}),('polygon','head',{'points':'60,40 50,35 50,45','fill':'black'})])
    p['source_code']='import xml.etree.ElementTree as ET\ntree=ET.parse(INPUT_SVG)\nnode=tree.getroot()[0]\nnode.tag="{http://www.w3.org/2000/svg}g"\nnode.attrib.clear()\nnode.set("id","a")\n'
    for tag,ident,attrs in shapes:
        p['source_code']+='ET.SubElement(node,'+repr('{http://www.w3.org/2000/svg}'+tag)+','+repr(dict(attrs,id=ident))+')\n'
    p['source_code']+='tree.write(OUTPUT_SVG,encoding="unicode")\n'
    result=programs.execute_programs([p],[issue],images,tmp_path/'execute',capabilities=OFF)
    assert result['rcd'][0]['status']=='changed_unverified',result['rcd']
    root=ET.parse(result['images']['im']['svg']).getroot()
    assert len(root[0])==len(shapes)
    with Image.open(result['images']['im']['png']) as image:
        assert image.convert('RGB').getextrema() != ((255,255),(255,255),(255,255))


def test_on_first_sp_crop_color_actual_invocations(tmp_path):
    from PIL import Image
    from figfox_plus.native import pipeline
    original=tmp_path/'original.png';Image.new('RGB',(100,100),(20,90,150)).save(original)
    spec=json.dumps({'kind':'geometry','data':{'shape':'cuboid','origin':[10,30],'u':[20,-5],'v':[0,20],'depth':[10,-10]}})
    response='<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><g id="cube" data-plus-sp=\''+spec+'\'/><g id="crop" data-plus-crop="60,60,10,10" data-plus-representation="raster"/><rect id="color" x="70" y="70" width="5" height="5" data-plus-color=\'{"fill":[80,80,5,5]}\'/></svg>'
    root=pipeline.first(original,tmp_path,send=lambda *a:response,capabilities=dict(OFF,code_methods=True))
    assert not any(any(k in n.attrib for k in ('data-plus-sp','data-plus-crop','data-plus-color')) for n in root.iter())
    events=[json.loads(l) for l in (tmp_path/'invocation-trace.jsonl').read_text().splitlines()]
    starts=[r['method'] for r in events if r['category']=='code_intervention' and r['status']=='started']
    assert 'asset' in starts and 'sample_color' in starts and any('sp_element' in r for r in starts)


def test_common_prompt_hashes_equal_all_four_policies():
    from figfox_plus.native.capability_prompts import block_hashes
    hashes=[block_hashes(dict(OFF,sam=sam,code_methods=code)) for sam in (False,True) for code in (False,True)]
    for key in ('common_quality','common_conditional_policy'):
        assert len({h[key] for h in hashes})==1
    assert len({h['availability_manifest'] for h in hashes})==4


def test_off_generated_cannot_leave_disabled_svg_declarations(tmp_path):
    images,issue,p=fixture(tmp_path,'D')
    p['source_code']=CODE.replace('set("fill","blue")','set("data-plus-sp",\'{"kind":"geometry","data":{}}\')')
    result=programs.execute_programs([p],[issue],images,tmp_path/'execute',capabilities=OFF)
    assert result['rcd'][0]['status']=='failed'
    assert result['rcd'][0]['rolled_back']


def test_sam_off_unbound_asset_reference_rejected(tmp_path):
    from PIL import Image
    from figfox_plus.native import pipeline
    original=tmp_path/'original.png';Image.new('RGB',(100,100)).save(original)
    with pytest.raises(ValueError,match='disabled|unbound'):
        pipeline.first(original,tmp_path,capabilities=OFF,send=lambda *a:SVG.replace('</svg>','<image id="unknown" href="asset_old"/></svg>'))


def test_on_generated_library_invocations_are_recorded(tmp_path):
    images,issue,p=fixture(tmp_path,'B')
    code='from figfox_plus.sp.geometry import cuboid\nfaces=cuboid({"origin":[10,30],"u":[20,-5],"v":[0,20],"depth":[10,-10]})\nassert len(faces)>1\n'+CODE
    receipt=sandbox.run_code(code,images['im']['svg'],tmp_path/'sandbox',capabilities=dict(OFF,code_methods=True))
    assert receipt['status']=='executed',receipt
    assert any(e['method'].endswith('.cuboid') and e['status']=='started' for e in receipt.get('library_invocations',[]))


def test_followup_failure_preserves_already_committed_image(tmp_path,monkeypatch):
    from figfox_plus.native.review_problem_first_v13 import orchestrator,followup
    from figfox_plus.native.review_problem_first_v13.scene import write_checkpoint
    import xml.etree.ElementTree as ET
    bundle=prepared_bundle(tmp_path);task=tmp_path/'review';orchestrator.prepare(bundle,task,capabilities=OFF)
    def partial(task_dir,out_dir,**kwargs):
        out=Path(out_dir);(out/'execution').mkdir(parents=True)
        state=json.loads((Path(task_dir)/'result.json').read_text())
        tree=ET.parse(state['images']['im']['svg']).getroot();tree[0].set('fill','blue')
        checkpoint,_=write_checkpoint(tree,out/'execution/checkpoints',0)
        checkpoint['original']=state['images']['im']['original']
        (out/'execution/state.json').write_text(json.dumps({'images':{'im':checkpoint},'rcd':[]}))
        raise ValueError('synthetic failure after committed checkpoint')
    monkeypatch.setattr(followup,'run_followup',partial)
    result=orchestrator.run(task,sender=lambda *a,**k:{'role':'assistant','content':json.dumps({'issues':[],'programs':[]})},capabilities=OFF)
    assert result['followup']['status']=='failed'
    assert 'blue' in Path(result['images']['im']['svg']).read_text()
    assert result['terminal_source']=='followup'
    assert result['visual_passed'] is False

@pytest.mark.parametrize('sam',[False,True])
@pytest.mark.parametrize('code',[False,True])
def test_four_assignments_freeze_in_prepare_and_project_context(tmp_path,sam,code):
    from figfox_plus.native.review_problem_first_v13 import orchestrator
    from figfox_plus.native.capabilities import load_policy,capability_hash
    assignment=dict(OFF,sam=sam,code_methods=code)
    task=tmp_path/'review';orchestrator.prepare(prepared_bundle(tmp_path),task,capabilities=assignment)
    assert load_policy(task)==assignment
    methods_pack=json.loads((task/'methods.json').read_text())
    assert methods_pack['capability_hash']==capability_hash(assignment)
    assert bool(methods_pack['constructors']) is code
    messages=json.loads((task/'messages.json').read_text())
    raw=json.dumps(messages)
    assert ('CURRENT_TP' in raw) is code
    assert ('current_diagnostics' in raw) is code
