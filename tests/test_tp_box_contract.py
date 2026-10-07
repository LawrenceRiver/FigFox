import copy
import hashlib
import xml.etree.ElementTree as ET

from PIL import Image, ImageDraw
import pytest

from figfox_plus.native.document import parse, serialize, measure
from figfox_plus.native.review_problem_first_v13.replay import canonicalize_program, select_valid_programs
from figfox_plus.native.review_problem_first_v13.programs import execute_programs


def test_nested_and_convergence_edge_arrays_preserve_values_expressions_and_source_rois():
    expression={'$measure':{'ids':['neighbor'],'edge':'right'}}
    program={'route':'module_program','args':{'operations':[{'method':'bp_program','args':{'operations':[
        {'method':'sp_photo','args':{'source_crop':[5,6,7,8],'target_tp':[1,2,expression,10]}},
        {'method':'sp_replace','args':{'measurement_viewport':[-2,-3,12,13],'target_tp':[1,2,9,10]}},
    ]}}]},'convergence':{'repairs':[{'method':'tp_fit','args':{'target_tp':[0,0,12,13]}}]}}
    original=copy.deepcopy(program)
    canonicalize_program(program)
    photo,shape=program['args']['operations'][0]['args']['operations']
    assert photo['args']['target_tp']=={'left':1,'top':2,'right':expression,'bottom':10}
    assert photo['args']['source_crop']==[5,6,7,8]
    assert shape['args']['measurement_viewport']=={'left':-2,'top':-3,'right':12,'bottom':13}
    assert program['convergence']['repairs'][0]['args']['target_tp']=={'left':0,'top':0,'right':12,'bottom':13}
    assert len(program['host_normalizations'])==4
    assert original['args']['operations'][0]['args']['operations'][0]['args']['target_tp'][2]==expression
    first=copy.deepcopy(program);canonicalize_program(program)
    assert program==first


@pytest.mark.parametrize('edges', [[1,2,3],[10,2,3,4],[1,4,3,2],[False,1,3,4],[1,2,float('nan'),4],[1,2,None,4]])
def test_invalid_box_geometry_is_never_filled_or_reinterpreted(edges):
    program={'route':'module_program','args':{'operations':[{'method':'tp_fit','args':{'target_tp':edges}}]}}
    with pytest.raises(ValueError):canonicalize_program(program)
    assert 'host_normalizations' not in program


@pytest.mark.integration
@pytest.mark.parametrize('method',['sp_replace','sp_photo'])
def test_edge_array_reply_executes_real_repair_with_valid_render_and_unchanged_neighbor(tmp_path,method):
    root=parse('<svg xmlns="http://www.w3.org/2000/svg" width="120" height="100" viewBox="0 0 120 100">'
               '<rect id="target" x="20" y="20" width="40" height="30" fill="orange"/>'
               '<circle id="neighbor" cx="100" cy="75" r="8" fill="blue"/></svg>')
    svg=tmp_path/'scene.svg';png=tmp_path/'preview.png'
    svg.write_text(serialize(root),encoding='utf-8');measure(root,png)
    source=tmp_path/'source.png';image=Image.new('RGB',(120,100),'white')
    ImageDraw.Draw(image).rectangle((2,2,21,15),fill='red');image.save(source)
    revision=hashlib.sha256(svg.read_bytes()).hexdigest()
    images={'fixture':{'svg':str(svg),'png':str(png),'original':str(source),'revision':revision}}
    issue={'id':'issue','image_id':'fixture','category':'D' if method=='sp_replace' else 'S2',
           'decision':'confirmed','description':'Synthetic replacement defect.',
           'original_evidence':'Independently located original fixture subject.',
           'current_evidence':'The fixture target is visible.','target_ids':['target'],'neighbor_ids':['neighbor']}
    args=({'kind':'arrow','data':{'waypoints':[[0,0],[30,0]],'head_length':5,'head_width':4,
             'stroke_width':2,'stroke':'black','route':'line'},
           'measurement_viewport':[-8,-8,38,8],'target_tp':[20,20,60,50],'mode':'contain'}
          if method=='sp_replace' else
          {'source_crop':[2,2,20,14],'target_tp':[20,20,60,50],'representation':'raster',
           'remove_background':False,'padding':0,'mode':'stretch',
           'crop_review':{'object_complete':True,'clipped':False,'full_object_xywh':[4,4,16,10],
                'edges_reviewed':{'left':True,'top':True,'right':True,'bottom':True},
                'evidence':'The complete fixture crop lies inside the supplied source ROI.'}})
    operation={'method':method,'target_ids':['target'],'args':args}
    if method=='sp_photo':operation['source_location']={'basis':'original_semantic','description':'The red fixture rectangle in the original source.'}
    program={'id':'repair','image_id':'fixture','base_revision':revision,'phase':'reconstructor',
             'route':'module_program','issue_ids':['issue'],'target_ids':['target'],'depends_on':[],
             'rcd_predescription':'Replace the fixture target.','args':{'operations':[operation]}}
    raw=copy.deepcopy(program)
    accepted,rejected=select_valid_programs([program],[issue],images)
    assert not rejected and len(accepted)==1 and program==raw
    result=execute_programs(accepted,[issue],images,tmp_path/'execution')
    assert result['rcd'][0]['status']=='changed_unverified',result['rcd'][0]
    final=parse(open(result['images']['fixture']['svg'],encoding='utf-8').read())
    before=next(n for n in root.iter() if n.get('id')=='neighbor')
    after=next(n for n in final.iter() if n.get('id')=='neighbor')
    assert ET.tostring(before)==ET.tostring(after)
    with Image.open(result['images']['fixture']['png']) as rendered:assert rendered.size==(120,100)
