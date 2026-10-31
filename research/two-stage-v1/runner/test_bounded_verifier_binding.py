import unittest,copy
from bounded_verifier_binding import bind
class VerifierBindingTests(unittest.TestCase):
 def test_exact_hash_permutation_only_does_not_change_quality(self):
  snap={'revision':'r','evidence_hashes':{'current_png':'p','bounds':'b'}};raw={'revision':'r','evidence_hashes':{'current_png':'b','bounds':'p'},'unresolved_ids':['actual'],'protected_regressions':['actual regression']};before=copy.deepcopy(raw)
  effective,audit=bind(raw,snap);self.assertEqual(effective['evidence_hashes'],snap['evidence_hashes']);self.assertEqual(effective['unresolved_ids'],before['unresolved_ids']);self.assertEqual(raw,before);self.assertTrue(audit)
 def test_missing_unknown_or_stale_values_not_repaired(self):
  s={'revision':'r','evidence_hashes':{'a':'x','b':'y'}}
  for raw in [{'revision':'old','evidence_hashes':{'a':'x','b':'y'}},{'revision':'r','evidence_hashes':{'a':'x'}},{'revision':'r','evidence_hashes':{'a':'x','b':'invented'}}]:
   with self.assertRaises(ValueError):bind(raw,s)
 def test_attention_metadata_requires_same_actual_request_and_no_unknown_hash(self):
  from bounded_verifier_binding import bind_attention_ack
  expected={'candidate_receipt_sha256':'a'*64,'source_sha256':'b'*64,'policy_sha256':'c'*64,'before':{'revision':'d'*64,'evidence_hashes':{'x':'e'*64,'y':'f'*64}},'use':'attention_hint_only'}
  actual=copy.deepcopy(expected);actual['policy_sha256']='e'*64;actual['before']['evidence_hashes']['x']='c'*64
  raw={'connector_paint_ack':actual,'unresolved_ids':['actual defect']};proof={'exact_request_metadata_verified':True,'expected_ack':expected,'body_sha256':'request'}
  result,_=bind_attention_ack(raw,expected,proof);self.assertEqual(result['unresolved_ids'],raw['unresolved_ids']);self.assertEqual(result['connector_paint_ack'],expected);self.assertEqual(raw['connector_paint_ack'],actual)
  bad=copy.deepcopy(raw);bad['connector_paint_ack']['policy_sha256']='9'*64
  with self.assertRaises(ValueError):bind_attention_ack(bad,expected,proof)
  bad=copy.deepcopy(raw);bad['connector_paint_ack']['candidate_receipt_sha256']='9'*64
  with self.assertRaises(ValueError):bind_attention_ack(bad,expected,proof)
 def test_request_bound_machine_fields_do_not_accept_foreign_values(self):
  from bounded_verifier_binding import bind_from_same_request
  snapshot={'revision':'d'*64,'evidence_hashes':{'a':'e'*64,'b':'f'*64}}
  ack={'candidate_receipt_sha256':'a'*64,'source_sha256':'b'*64,'policy_sha256':'c'*64,'before':snapshot,'use':'attention_hint_only'}
  proof={'exact_request_metadata_verified':True,'expected_ack':ack,'expected_snapshot':snapshot,'body_sha256':'actual request'}
  raw={'revision':'d'*64,'evidence_hashes':{'a':'c'*64,'b':'f'*64},'connector_paint_ack':ack,'unresolved_ids':['actual failure']}
  result,_=bind_from_same_request(raw,snapshot,proof);self.assertEqual(result['evidence_hashes'],snapshot['evidence_hashes']);self.assertEqual(result['unresolved_ids'],raw['unresolved_ids'])
  with self.assertRaises(ValueError):bind_from_same_request({**raw,'evidence_hashes':{'a':'9'*64,'b':'f'*64}},snapshot,proof)

class UnresolvedUncertaintyTest(__import__('unittest').TestCase):
 def test_actual_unresolved_stays_uncertain_without_promotion(self):
  import bounded_verifier_binding as b
  original={'uncertainty_reviews':[{'id':'u','decision':'unresolved','evidence':'still unclear'}]}
  value,ops=b.omit_incomplete_noop_uncertainty_reviews(original,{'uncertain':[{'id':'u'}]})
  self.assertEqual(value['uncertainty_reviews'][0]['decision'],'uncertain');self.assertEqual(original['uncertainty_reviews'][0]['decision'],'unresolved');self.assertTrue(ops)

 def test_null_optional_promotion_container_is_absent_not_guessed(self):
  import bounded_verifier_binding as b
  original={'uncertainty_reviews':[{'id':'u','decision':'confirmed','container_id':None,'target_ids':['actual'],'evidence':'real evidence'}]}
  value,ops=b.omit_incomplete_noop_uncertainty_reviews(original,{'uncertain':[{'id':'u'}]})
  self.assertNotIn('container_id',value['uncertainty_reviews'][0]);self.assertEqual(value['uncertainty_reviews'][0]['decision'],'confirmed');self.assertIn('container_id',original['uncertainty_reviews'][0]);self.assertTrue(ops)

class UnreportedRequiredDispositionTest(__import__('unittest').TestCase):
 def test_existing_required_obligation_cannot_vanish_when_model_omits_it(self):
  import bounded_verifier_binding as b
  raw={'resolved_ids':[],'unresolved_ids':['a'],'not_required':[]}
  value,ops=b.conservative_partition_conflicts(raw,['a','missing'])
  self.assertEqual(value['unresolved_ids'],['a','missing']);self.assertEqual(raw['unresolved_ids'],['a']);self.assertEqual(value['resolved_ids'],[]);self.assertTrue(ops)
  with self.assertRaises(ValueError):b.conservative_partition_conflicts(raw,['other'])
