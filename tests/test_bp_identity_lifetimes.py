import copy
import hashlib
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image, ImageDraw
import pytest

from figfox_plus.native.document import parse, serialize, measure
from figfox_plus.native.review_problem_first_v13.programs import validate_programs, execute_programs


def fixture(tmp_path):
    root=parse('<svg xmlns="http://www.w3.org/2000/svg" width="80" height="60"><g id="container">'
        '<g id="panel"><rect id="panel_rect" x="20" y="20" width="30" height="20" fill="red"/></g>'
        '<rect id="backplate" x="5" y="5" width="70" height="50" fill="blue"/></g></svg>')
    svg=tmp_path/'scene.svg';svg.write_text(serialize(root),encoding='utf-8')
    png=tmp_path/'preview.png';measure(root,png)
    source=tmp_path/'original.png';im=Image.new('RGB',(80,60),'white')
    draw=ImageDraw.Draw(im);draw.rectangle((5,5,74,54),fill='blue');draw.rectangle((20,20,49,39),fill='red');im.save(source)
    revision=hashlib.sha256(svg.read_bytes()).hexdigest()
    images={'fixture':{'svg':str(svg),'png':str(png),'original':str(source),'revision':revision}}
    issue={'id':'paint','image_id':'fixture','category':'F','decision':'confirmed',
           'description':'The fixture foreground is covered by a later background.',
           'original_evidence':'Original fixture red panel appears in front of blue background.',
           'current_evidence':'Current fixture panel is painted first and covered.',
           'target_ids':['panel'],'neighbor_ids':['backplate','container']}
    fragment=ET.tostring(next(n for n in root.iter() if n.get('id')=='panel'),encoding='unicode')
    program={'id':'reorder','issue_ids':['paint'],'image_id':'fixture','base_revision':revision,
        'phase':'reconstructor','route':'module_program','target_ids':['panel'],'depends_on':[],
        'rcd_predescription':'Repair F paint order by removing the panel and reinserting it above the background.',
        'convergence':{'max_iterations':2,'repairs':[]},
        'relations':[{'id':'inside','predicate':'contain','subject_id':'panel','object_id':'backplate','padding':1,
            'reference_evidence':'Original fixture panel is wholly inside the background.'}],
        'args':{'operations':[{'method':'bp_remove','target_ids':['panel'],'args':{}},
            {'method':'bp_add','target_ids':['backplate'],'args':{'parent_id':'@parent','svg':fragment}}]}}
    return images,issue,program,svg,png


@pytest.mark.integration
@pytest.mark.parametrize('nested',[False,True])
def test_remove_then_add_reuses_only_removed_subtree_ids_and_reorders_real_pixels(tmp_path,nested):
    images,issue,program,svg,png=fixture(tmp_path)
    original_svg=svg.read_bytes()
    if nested:
        ops=program['args']['operations']
        program['args']['operations']=[{'method':'bp_program','target_ids':['panel','backplate'],'args':{'operations':ops}}]
    validate_programs([copy.deepcopy(program)],[issue],images)
    result=execute_programs([program],[issue],images,tmp_path/'execution')
    assert result['rcd'][0]['status']=='changed_unverified',result['rcd']
    assert svg.read_bytes()==original_svg
    with Image.open(png) as im:assert im.convert('RGB').getpixel((30,30))==(0,0,255)
    with Image.open(result['images']['fixture']['png']) as im:
        assert im.convert('RGB').getpixel((30,30))==(255,0,0)
        assert im.convert('RGB').getpixel((8,8))==(0,0,255)
    tree=ET.fromstring(Path(result['images']['fixture']['svg']).read_text(encoding='utf-8'))
    ids=[n.get('id') for n in tree.iter() if n.get('id')]
    assert len(ids)==len(set(ids)) and ids.count('panel')==1 and ids.count('panel_rect')==1


@pytest.mark.parametrize('condition',['no_removal','live_sibling_collision','duplicate_fragment_ids','removed_reference'])
def test_live_ids_and_unknown_references_still_reject_before_execution(tmp_path,condition):
    images,issue,program,svg,png=fixture(tmp_path)
    before=svg.read_bytes();ops=program['args']['operations']
    if condition=='no_removal':ops.pop(0)
    elif condition=='live_sibling_collision':ops[1]['args']['svg']='<g id="panel"><rect id="backplate" width="5" height="5"/></g>'
    elif condition=='duplicate_fragment_ids':ops[1]['args']['svg']='<g id="panel"><rect id="panel" width="5" height="5"/></g>'
    else:ops.insert(1,{'method':'measure','target_ids':['panel'],'args':{}})
    with pytest.raises(ValueError):validate_programs([program],[issue],images)
    assert svg.read_bytes()==before
