import unittest,tempfile
from pathlib import Path
from current_representation_binding import bind
class RepresentationTest(unittest.TestCase):
 def test_scoped_deleted_id_maps_only_exact_surviving_ancestor_no_quality_pass(self):
  with tempfile.TemporaryDirectory() as tmp:
   run=Path(tmp)/'run';(run/'checkpoint').mkdir(parents=True);candidate=run/'round-1/candidate';candidate.mkdir(parents=True)
   (run/'checkpoint/current.svg').write_text('<svg><g id="group"><rect id="removed"/></g></svg>');(candidate/'current.svg').write_text('<svg><g id="group"><image id="replacement"/></g></svg>')
   issue={'id':'actual','decision':'confirmed','target_ids':['removed'],'neighbor_ids':[],'current_evidence':'real unresolved defect'};state={'required':[issue],'uncertain':[]};report={'unresolved_ids':['actual']};snap={'candidate_folder':str(candidate),'native_result':{'rcd':[{'effective_target_ids':['removed'],'tool_receipt':{'status':'executed'}}]}}
   result,audit=bind(report,state,snap);self.assertEqual(result['unresolved_ids'],['actual']);self.assertEqual(result['current_bindings'][0]['target_ids'],['group']);self.assertNotIn('resolved_ids',result);self.assertTrue(audit);self.assertNotIn('current_bindings',report)
   snap['native_result']['rcd']=[]
   with self.assertRaises(ValueError):bind(report,state,snap)

 def test_deleted_target_cannot_certify_uncertainty_promotion(self):
  with tempfile.TemporaryDirectory() as tmp:
   run=Path(tmp)/'run';(run/'checkpoint').mkdir(parents=True);candidate=run/'round-1/candidate';candidate.mkdir(parents=True)
   (run/'checkpoint/current.svg').write_text('<svg><g id="g"><rect id="old"/></g></svg>');(candidate/'current.svg').write_text('<svg><g id="g"/></svg>')
   issue={'id':'u','decision':'uncertain','target_ids':['old'],'neighbor_ids':[],'current_evidence':'earlier uncertainty'}
   raw={'unresolved_ids':[],'uncertainty_reviews':[{'id':'u','decision':'confirmed','target_ids':['old'],'evidence':'actual model claim'}]}
   value,ops=bind(raw,{'required':[],'uncertain':[issue]},{'candidate_folder':str(candidate),'native_result':{'rcd':[{'effective_target_ids':['old'],'tool_receipt':{'status':'executed'}}]}})
   self.assertEqual(value['uncertainty_reviews'],[]);self.assertEqual(value['current_bindings'][0]['target_ids'],['g']);self.assertEqual(raw['uncertainty_reviews'][0]['decision'],'confirmed');self.assertEqual(len(ops),2)
