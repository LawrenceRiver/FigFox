import unittest, copy, json, tempfile
from pathlib import Path
try:
 from figfox_score.engine import evaluate, validate_input, validate_response, prepare_request, merge_response
except ImportError:
 evaluate = validate_input = validate_response = prepare_request = merge_response = None
ROOT=Path(__file__).resolve().parents[1]
class ScoreTests(unittest.TestCase):
 def setUp(self):
  self.assertIsNotNone(evaluate, '评分引擎尚未实现')
  self.d=json.loads((ROOT/'examples/input.json').read_text())
 def result(self, item, d=None):
  return next(x for x in evaluate(d or self.d, ROOT/'examples')['items'] if x['item_id']==item)
 def test_all_18(self): self.assertEqual(len(evaluate(self.d,ROOT/'examples')['items']),18)
 def test_no_formula_na(self): self.assertEqual(self.result('D02')['status'],'na')
 def test_unknown_visual(self): self.assertEqual(self.result('D10')['status'],'unknown')
 def test_translation(self):
  for o in self.d['candidate']['objects']: o['bbox'][0]+=600; o['bbox'][1]+=400
  self.assertEqual(self.result('D08')['status'],'pass')
 def test_uniform_scale(self):
  for o in self.d['candidate']['objects']: o['bbox']=[v*2 for v in o['bbox']]
  self.assertEqual(self.result('D08')['status'],'pass')
 def test_reverse_arrow(self):
  self.d['candidate']['edges'][0]['start']='b';self.d['candidate']['edges'][0]['end']='a'
  self.assertEqual(self.result('D05')['status'],'fail')
 def test_missing_layer(self):
  self.d['candidate']['objects'][0]['count']=2
  self.assertEqual(self.result('D04')['status'],'fail')
 def test_extra_edge(self):
  self.d['candidate']['edges'].append(dict(self.d['candidate']['edges'][0],id='extra'))
  self.assertEqual(self.result('D05')['metrics']['extra'],1)
 def test_parallel_edge_not_set(self):
  self.d['reference']['edges'].append(dict(self.d['reference']['edges'][0],id='e2'))
  self.assertEqual(self.result('D05')['metrics']['missing'],1)
 def test_duplicate_id_rejected(self):
  self.d['candidate']['edges'].append(self.d['candidate']['edges'][0])
  with self.assertRaises(ValueError): validate_input(self.d)
 def test_wrong_parent(self):
  self.d['candidate']['objects'][0]['parent']='b'
  self.assertEqual(self.result('D07')['status'],'fail')
 def test_unverified_manifest(self):
  self.d['semantic_evidence']['verified']=False
  self.assertEqual(self.result('D05')['status'],'unknown')
 def test_missing_output(self):
  self.d['candidate']['file']='absent.svg'; self.d['candidate']['output_confirmed_missing']=True
  self.assertEqual(self.result('D16')['status'],'fail')
 def test_missing_material(self):
  self.d['candidate']['file']='absent.svg'
  self.assertEqual(self.result('D16')['status'],'unknown')
 def test_bad_file(self):
  with tempfile.TemporaryDirectory() as tmp:
   Path(tmp,'bad.svg').write_text('<svg')
   self.d['candidate']['file']='bad.svg'
   self.assertEqual(self.result('D16',self.d)['status'],'unknown') # relative base is examples
   self.assertEqual(next(x for x in evaluate(self.d,Path(tmp))['items'] if x['item_id']=='D16')['status'],'fail')
 def test_no_edit_evidence(self):
  self.assertEqual(self.result('D13')['status'],'unknown');self.assertEqual(self.result('D16')['status'],'unknown')
 def test_whole_page_bitmap(self):
  self.d['candidate']['whole_page_bitmap']=True
  self.assertEqual(self.result('D15')['status'],'fail')
 def test_critical_not_averaged(self):
  self.d['candidate']['edges'][0]['end']='a'
  self.assertEqual(evaluate(self.d,ROOT/'examples')['usability'],'unusable')
 def test_unknown_field_rejected(self):
  self.d['oops']=3
  with self.assertRaises(ValueError): validate_input(self.d)
 def test_nonfinite_rejected(self):
  self.d['candidate']['objects'][0]['bbox'][0]=float('nan')
  with self.assertRaises(ValueError): validate_input(self.d)
 def test_invalid_model_rejected(self):
  with self.assertRaises(ValueError): validate_response({'findings':[{'item_id':'D99'}]},self.d)
 def test_mock_never_passes(self):
  req=prepare_request(self.d,ROOT/'examples'); response={'task_id':self.d['task_id'],'source':'mock','findings':[{'item_id':'D10','unit_id':'whole','status':'pass','evidence':['render'],'reason':'synthetic','severity':'none','repair_scope':'none','root_cause':'synthetic'}]}
  out=merge_response(evaluate(self.d,ROOT/'examples'),response,self.d)
  self.assertEqual(next(x for x in out['items'] if x['item_id']=='D10')['status'],'unknown')
 def test_root_dedup(self):
  self.d['candidate']['objects'][0]['count']=2
  out=evaluate(self.d,ROOT/'examples'); self.assertEqual(len({p['issue_id'] for p in out['issues']}),len(out['issues']))
 def test_method_conflict(self):
  self.d['source_conflict']=True
  self.assertEqual(evaluate(self.d,ROOT/'examples')['usability'],'pending_reference')
 def test_reversed_edge_one_root(self):
  self.d['candidate']['edges'][0]['start']='b';self.d['candidate']['edges'][0]['end']='a'
  out=evaluate(self.d,ROOT/'examples');self.assertEqual(len(out['issues']),1)
 def test_result_schema(self):
  from figfox_score.engine import check,strict_json
  check(evaluate(self.d,ROOT/'examples'),strict_json(ROOT/'schemas/result.schema.json'))
 def test_file_failure_overrides_missing_judge_scope(self):
  self.d['applicability']['D16']={'state':'unknown','reason':'judge lacks operation evidence','units':[]}
  self.d['candidate']['file']='absent.svg';self.d['candidate']['output_confirmed_missing']=True
  self.assertEqual(evaluate(self.d,ROOT/'examples')['usability'],'unusable')
 def test_human_review_resolves_visual_unknown(self):
  self.d['evidence']=[dict(item_id='D10',unit_id='whole',status='pass',evidence=['synthetic render review'],reason='reviewed fixture',severity='none',repair_scope='none',root_cause='readability',source='human',verified=True)]
  self.assertEqual(self.result('D10')['status'],'pass')
 def test_xml_entity_not_executed(self):
  from figfox_score.engine import file_probe
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp,'entity.svg');p.write_text('<!DOCTYPE svg [<!ENTITY x SYSTEM "file:///etc/passwd">]><svg>&x;</svg>')
   r=file_probe(p);self.assertEqual(r['status'],'unknown');self.assertIn('unsafe',r['reason'])
 def test_duplicate_json_key_rejected(self):
  from figfox_score.engine import strict_json
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp,'bad.json');p.write_text('{"a":1,"a":2}')
   with self.assertRaises(ValueError):strict_json(p)
 def test_core_na_cannot_hide_edges(self):
  self.d['applicability']['D05']={'state':'na','reason':'hide error','units':[]}
  with self.assertRaises(ValueError): validate_input(self.d)
 def test_human_conflict_keeps_critical_failure(self):
  self.d['candidate']['objects'][0]['count']=2
  self.d['evidence']=[dict(item_id='D04',unit_id='a',status='pass',evidence=['review'],reason='contradiction',severity='none',repair_scope='none',root_cause='count:a',source='human',verified=True)]
  self.assertEqual(evaluate(self.d,ROOT/'examples')['usability'],'unusable')
 def test_fake_verified_model_rejected(self):
  self.d['semantic_evidence']['source']='model'
  with self.assertRaises(ValueError): validate_input(self.d)
 def test_response_cannot_self_verify(self):
  response={'task_id':self.d['task_id'],'source':'model','findings':[dict(item_id='D10',unit_id='whole',status='pass',evidence=['render'],reason='checked',severity='none',repair_scope='none',root_cause='readable',verified=True)]}
  with self.assertRaises(ValueError): validate_response(response,self.d)
 def test_edit_ratio_by_type(self):
  self.d['edit_evidence']=[dict(object_id='a',source='human',verified=True,changed_actual_content=True,success=True,evidence=['actual edit clip'])]
  result=self.result('D13');self.assertEqual(result['metrics']['editable_by_type']['shape']['ratio'],0.5);self.assertEqual(result['status'],'unknown')
 def test_model_edit_not_verified(self):
  self.d['edit_evidence']=[dict(object_id='a',source='model',verified=False,changed_actual_content=True,success=True,evidence=['static image'])]
  self.assertEqual(self.result('D13')['status'],'unknown')
 def test_operation_verified_chain(self):
  self.d['operation_evidence']=[dict(software=self.d['display']['software'],version='test',source='human',verified=True,opened=True,modified=True,saved=True,reopened=True,preserved=True,evidence=['synthetic chain fixture'])]
  self.assertEqual(self.result('D16')['status'],'pass')
 def test_missing_unit_cannot_claim_usable(self):
  self.d['applicability']['D10']['units'].append(dict(id='extra_region',ref_ids=[],critical=False))
  self.assertEqual(self.result('D10')['coverage'],0)
 def test_distorted_layout(self):
  self.d['candidate']['objects'][0]['bbox'][2]*=2
  self.assertEqual(self.result('D08')['status'],'fail')
 def test_issue_linkage(self):
  self.d['candidate']['whole_page_bitmap']=True
  self.d['evidence']=[dict(item_id='D13',unit_id='a',status='fail',evidence=['whole page image'],reason='no edit',severity='critical',repair_scope='global',root_cause='whole-page-raster',source='human',verified=True)]
  out=evaluate(self.d,ROOT/'examples');self.assertEqual(len(out['issues']),1)
  self.assertIn('D15',out['issues'][0]['related_categories'])
 def test_container_cycle_rejected(self):
  self.d['candidate']['objects'][0]['parent']='b';self.d['candidate']['objects'][1]['parent']='a'
  with self.assertRaises(ValueError):validate_input(self.d)
 def test_score_not_model_allowed(self):
  response={'task_id':self.d['task_id'],'source':'model','findings':[dict(item_id='D10',unit_id='whole',status='pass',evidence=['render'],reason='checked',severity='none',repair_scope='none',root_cause='readable',score=4)]}
  with self.assertRaises(ValueError):validate_response(response,self.d)
if __name__=='__main__': unittest.main()
