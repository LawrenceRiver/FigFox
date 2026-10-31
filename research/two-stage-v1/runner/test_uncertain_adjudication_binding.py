import unittest,copy
from bounded_verifier_binding import bind_uncertain_adjudications
class BindingTest(unittest.TestCase):
 def test_preserve_actual_judgment_and_evidence_no_invention(self):
  report={'not_required':[{'id':'u','evidence':'actual model evidence'}],'unresolved_ids':['r']};before=copy.deepcopy(report)
  out,ops=bind_uncertain_adjudications(report,{'required':[{'id':'r'}],'uncertain':[{'id':'u'}]})
  self.assertEqual(report,before);self.assertEqual(out['not_required'],[]);self.assertEqual(out['uncertainty_reviews'],[{'id':'u','evidence':'actual model evidence','decision':'not_required'}]);self.assertEqual(out['unresolved_ids'],['r']);self.assertTrue(ops)
 def test_unknown_id_never_invented_and_duplicate_fails(self):
  out,_=bind_uncertain_adjudications({'not_required':[{'id':'foreign','evidence':'e'}]},{'required':[],'uncertain':[]});self.assertEqual(out['not_required'][0]['id'],'foreign')
  with self.assertRaises(ValueError):bind_uncertain_adjudications({'not_required':[{'id':'u','evidence':'e'}],'uncertainty_reviews':[{'id':'u'}]},{'required':[],'uncertain':[{'id':'u'}]})

 def test_duplicate_wrong_slot_cannot_override_explicit_uncertainty(self):
  review={'id':'u','decision':'uncertain','evidence':'retain uncertainty'}
  out,ops=bind_uncertain_adjudications({'not_required':[{'id':'u','evidence':'wrong slot opinion'}],'uncertainty_reviews':[review]},{'required':[],'uncertain':[{'id':'u'}]})
  self.assertEqual(out['uncertainty_reviews'],[review]);self.assertEqual(out['not_required'],[]);self.assertEqual(ops[0]['unapplied_wrong_slot_model_entry']['evidence'],'wrong slot opinion')

 def test_unresolved_uncertain_id_is_never_a_confirmed_partition_member(self):
  actual={'id':'u','decision':'confirmed','evidence':'actual model promotion'}
  result,ops=bind_uncertain_adjudications({'not_required':[],'unresolved_ids':['r','u','v'],'uncertainty_reviews':[actual]},{'required':[{'id':'r'}],'uncertain':[{'id':'u'},{'id':'v','description':'original uncertainty'}]})
  self.assertEqual(result['unresolved_ids'],['r']);self.assertEqual(result['uncertainty_reviews'][0],actual);self.assertEqual(result['uncertainty_reviews'][1]['decision'],'uncertain')
 def test_evidence_free_still_uncertain_cannot_promote_or_resolve(self):
  from bounded_verifier_binding import omit_incomplete_noop_uncertainty_reviews
  raw={'uncertainty_reviews':[{'id':'u','decision':'uncertain'},{'id':'v','decision':'confirmed'}]};state={'uncertain':[{'id':'u'},{'id':'v'}]}
  result,audit=omit_incomplete_noop_uncertainty_reviews(raw,state);self.assertEqual(result['uncertainty_reviews'],[{'id':'v','decision':'confirmed'}]);self.assertEqual(len(raw['uncertainty_reviews']),2);self.assertEqual(audit[0]['original_model_entry']['decision'],'uncertain')
