import unittest,copy
from bounded_plan_binding import bind
class PlanBindingTests(unittest.TestCase):
 def test_provenance_and_unambiguous_nonobject_echo_are_not_quality_fields(self):
  finding={'id':'main:a','source_issue_id':'a','source_role':'main','decision':'confirmed','category':'C','description':'same defect','target_ids':['shape']}
  echo={k:v for k,v in finding.items() if k not in ('source_role','source_issue_id')};echo['container_id']='a'
  plan={'issues':[echo],'programs':[]};original=copy.deepcopy(plan)
  effective,audit=bind(plan,[finding],{'shape'})
  self.assertEqual(effective['issues'],[finding]);self.assertEqual(plan,original);self.assertTrue(audit)
 def test_quality_or_geometry_changes_fail_closed(self):
  f={'id':'main:a','source_issue_id':'a','source_role':'main','decision':'confirmed','category':'C','description':'actual defect','target_ids':['shape']}
  for key,value in [('decision','uncertain'),('description','different'),('target_ids',['other']),('container_id','actual_container')]:
   row={**f,key:value}
   with self.assertRaises(ValueError):bind({'issues':[row],'programs':[]},[f],{'shape','actual_container'})
 def test_id_only_reference_schema_binds_exact_frozen_queue(self):
  f={'id':'semantic:a','source_issue_id':'a','source_role':'semantic','decision':'uncertain','category':'C','target_ids':['shape']}
  result,_=bind({'issue_ids':['semantic:a'],'programs':[]},[f],{'shape'})
  self.assertEqual(result['issues'],[f])
  with self.assertRaises(ValueError):bind({'issue_ids':[],'programs':[]},[f],{'shape'})
 def test_id_reference_namespace_migration_keeps_exact_source_finding(self):
  f={'id':'semantic:m','source_issue_id':'m','source_role':'semantic','decision':'confirmed','target_ids':['shape']}
  plan={'issue_ids':['main:m'],'programs':[{'issue_ids':['main:m']}],'unresolved_reasons':[{'issue_id':'main:m','reason':'actual model reason'}]}
  result,_=bind(plan,[f],{'shape'})
  self.assertEqual(result['issues'],[f]);self.assertEqual(result['programs'][0]['issue_ids'],['semantic:m']);self.assertEqual(result['unresolved_reasons'][0]['reason'],'actual model reason')
 def test_colon_in_actual_source_id_is_not_stripped(self):
  f={'id':'semantic:uncertain:proposal:p','source_issue_id':'uncertain:proposal:p','decision':'uncertain'}
  result,_=bind({'issue_ids':['uncertain:proposal:p'],'programs':[]},[f],set())
  self.assertEqual(result['issues'],[f])
 def test_schema_lowered_actual_review_remains_unplanned_not_resolved(self):
  tracked=[{'id':'main:r','source_issue_id':'r','decision':'confirmed'},{'id':'semantic:model-review:p','source_issue_id':'model-review:p','decision':'uncertain','description':'actual model review'}]
  plan={'issue_ids':['main:r'],'programs':[],'unresolved_reasons':[]}
  result,_=bind(plan,tracked,set())
  self.assertEqual(result['issues'],tracked);self.assertEqual(result['programs'],[]);self.assertNotIn('resolved_ids',result)

 def test_actual_same_call_new_uncertainty_can_remain_unplanned_without_new_program(self):
  tracked=[{'id':'main:r','source_issue_id':'r','decision':'confirmed'},{'id':'semantic:semantic:new-u','source_issue_id':'semantic:new-u','decision':'uncertain','description':'actual same-call uncertainty'}]
  raw={'issue_ids':['main:r'],'programs':[],'unresolved_reasons':[]}
  value,ops=bind(raw,tracked,set(),additional_unplanned_source_ids=['semantic:new-u'])
  self.assertEqual(value['issues'],tracked);self.assertEqual(value['programs'],[]);self.assertEqual(value['unresolved_reasons'],[]);self.assertEqual(raw['issue_ids'],['main:r']);self.assertTrue(ops)
  with self.assertRaises(ValueError):bind(raw,tracked,set(),additional_unplanned_source_ids=['not-actual'])

 def test_constructor_envelope_alias_does_not_allow_geometry_or_scope_changes(self):
  from bounded_plan_binding import same_data_constructor_envelope_intent as same
  a={'id':'actual','target_ids':['t'],'args':{'kind':'formula','data':{'tex':'actual formula','x':1}}};b={'id':'actual','target_ids':['t'],'args':{'kind':'data','data':{'kind':'formula','tex':'actual formula','x':1}}}
  self.assertTrue(same(a,b));self.assertEqual(a['args']['kind'],'formula')
  self.assertFalse(same(a,{**b,'target_ids':['other']}));self.assertFalse(same(a,{**b,'args':{'kind':'data','data':{'kind':'formula','tex':'changed formula','x':1}}}))
  outer=lambda spec:{'id':'actual','args':{'method':'sp_replace','target_ids':['t'],'args':{**spec,'measurement_viewport':[1,2,3,4],'mode':'contain'}}}
  self.assertTrue(same(outer(a['args']),outer(b['args'])))
  changed=outer(b['args']);changed['args']['args']['measurement_viewport']=[2,2,3,4];self.assertFalse(same(outer(a['args']),changed))
