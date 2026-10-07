import copy
import json
import pytest

from figfox_plus.native.document import parse
from figfox_plus.native.review_problem_first_v13.context_tables import model_line_facts, expand_line_facts, compact_traced_assets
from figfox_plus.native.review_problem_first_v13.orchestrator import _plan
from figfox_plus.native.tight_tp import measure_tight
from figfox_plus.native.sam_replace import apply_replacements


def test_html_entities_are_xml_safe_without_double_decoding():
    repairs=[]
    root=parse('<svg><text>A&nbsp;B &copy; &amp;nbsp; &NotEqualTilde;</text><desc><![CDATA[&nbsp;]]></desc></svg>',repairs=repairs)
    assert root[0].text=='A\u00a0B © &nbsp; ≂̸'
    assert root[1].text=='&nbsp;'
    assert repairs==[{'kind':'html_named_entity_to_numeric','count':3}]


def test_repair_turn_may_repeat_inspection_without_erasing_coverage():
    message={'content':'{"compact_category_sweeps": [], "issues": [], "programs": []}'}
    plan,_=_plan(message,review_only=True)
    assert '_inspection_envelope_error' not in plan
    missing,_=_plan({'content':'{"issues":[],"programs":[]}'},review_only=False)
    assert missing['_inspection_envelope_error']


def test_missing_relation_audit_ids_are_supplied_without_guessing_links():
    program={'relations':[{'predicate':'contain','subject_id':'text','object_id':'box','padding':1}],
             'convergence':{'max_iterations':6}}
    message={'content':json.dumps({'issues':[],'programs':[program]})}
    plan,_=_plan(message,review_only=True)
    repeated,_=_plan(message,review_only=True)
    assert plan['programs'][0]['relations']==repeated['programs'][0]['relations']
    normalized=plan['programs'][0]['relations'][0].copy();normalized.pop('id')
    assert normalized==program['relations'][0]
    assert plan['programs'][0]['host_normalizations'][0]['kind']=='unreferenced_relation_id'
    program['convergence']['repairs']=[{'check_id':'missing'}]
    plan,_=_plan({'content':json.dumps({'issues':[],'programs':[program]})},review_only=True)
    assert 'id' not in plan['programs'][0]['relations'][0]


def test_check_only_references_do_not_invent_corrective_actions():
    program={'relations':[{'id':'r','predicate':'contain','subject_id':'a','object_id':'b','padding':1}],
        'convergence':{'max_iterations':6,'repairs':[{'check_id':'r'}]}}
    plan,_=_plan({'content':json.dumps({'issues':[],'programs':[program]})},review_only=True)
    normalized=plan['programs'][0]
    assert normalized['relations']==program['relations']
    assert normalized['convergence']['repairs']==[]
    assert normalized['host_normalizations'][0]['kind']=='remove_check_only_repair_reference'


def test_bounded_pairs_keep_all_objects_and_audit_omissions():
    facts={'objects':[{'object_id':str(i)} for i in range(40)],'unsupported':[],
           'relation_candidates':[{'object_ids':[str(i),str(j)],'endpoint_distances':{'distance':abs(i-j)}} for i in range(40) for j in range(i+1,40)]}
    original=copy.deepcopy(facts)
    packed=model_line_facts(facts,80)
    result=expand_line_facts(packed)
    assert facts==original
    assert result['objects']==facts['objects']
    assert len(result['relation_candidates'])==80
    assert {i for pair in result['relation_candidates'] for i in pair['object_ids']}=={str(i) for i in range(40)}
    assert result['relation_candidate_selection']['omitted_count']==700


def test_large_canvas_adapts_measurement_grid_without_resizing_geometry():
    root=parse('<svg xmlns="http://www.w3.org/2000/svg" width="2882" height="882" viewBox="0 0 2882 882"><rect id="r" x="100" y="200" width="30" height="40"/></svg>')
    result=measure_tight(root,['r'],max_pixels=2_000_000)
    assert result['canvas']['width']==2882
    assert result['raster_dimensions'][0]*result['raster_dimensions'][1]<=2_000_000
    assert result['effective_sample_scale']<4
    bounds=result['objects']['r']['tight_bbox']
    assert bounds['left']==pytest.approx(100,abs=2)
    assert bounds['bottom']==pytest.approx(240,abs=2)


def test_traced_asset_context_keeps_owner_and_real_arrow_geometry():
    paths=''.join('<path d="M0 0 L1 1 Z"/>' for _ in range(120))
    svg='<svg><g id="map"><g desc="Created with imagetracer.js version 1.2.6">'+paths+'</g></g><path id="arrow" d="M10 20 L30 40"/></svg>'
    context,omitted=compact_traced_assets(svg)
    assert len(omitted)==120 and len(context)<500
    assert 'id="map"' in context and 'd="M10 20 L30 40"' in context
    assert svg.count('<path')==121
    facts={'objects':[{'object_id':key} for key in sorted(omitted)]+[{'object_id':'arrow'}],
           'relation_candidates':[],'unsupported':[{'object_id':key} for key in omitted]}
    result=expand_line_facts(model_line_facts(facts,omit_ids=omitted))
    assert result['objects']==[{'object_id':'arrow'}] and result['unsupported']==[]
    assert result['opaque_asset_evidence']['omitted_object_count']==120


def test_sam_replacement_preserves_explicit_overlay_and_ancestor_transform():
    root=parse('<svg><g id="draft" transform="translate(20 30)" opacity="0.5"><rect id="old" width="20" height="30"/>'
        '<g transform="scale(2)"><path id="grid" d="M0 0 L10 10"/><path id="unwanted" d="M0 1 L2 3"/></g></g>'
        '<image id="replacement" href="data:image/png;base64,AA==" data-plus-replaces="draft" data-plus-keeps="grid"/></svg>')
    report=apply_replacements(root)
    assert report[0]['pruned_draft_ids']==['draft']
    assert report[0]['removed_draft_ids']==[]
    assert root[0].get('transform')=='translate(20 30)' and root[0].get('opacity')=='0.5'
    assert root[0][0].get('transform')=='scale(2)' and root[0][0][0].get('id')=='grid'
    assert {n.get('id') for n in root.iter()}.isdisjoint({'old','unwanted'})


def test_distant_constructor_viewport_uses_bounded_sampling():
    from figfox_plus.native.sp_v2 import measure_construction_adaptive
    element=parse('<svg><g id="shape"><rect x="0" y="0" width="20" height="30"/></g></svg>')[0]
    result=measure_construction_adaptive(element,{'left':2826,'top':1140,'right':2914,'bottom':1282})
    assert result['sample_scale']<4
    assert result['tight_bbox']['left']==pytest.approx(0,abs=1)
    assert result['tight_bbox']['bottom']==pytest.approx(30,abs=1)
