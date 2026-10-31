import unittest,copy
from bounded_verifier_binding import bind_region_coverage_conservatively,bind_uncertain_adjudications
class CoverageTest(unittest.TestCase):
 def test_unknown_unresolved_region_never_becomes_certified_coverage(self):
  report={'examined_regions':['a','invented','a'],'unresolved_regions':['unknown'],'unresolved_ids':['real defect']};before=copy.deepcopy(report)
  out,audit=bind_region_coverage_conservatively(report,[{'frame_id':'a'},{'frame_id':'b'}]);self.assertEqual(report,before);self.assertEqual(out['examined_regions'],['a']);self.assertEqual(out['unresolved_regions'],['a','b']);self.assertEqual(out['unresolved_ids'],['real defect']);self.assertTrue(audit)
 def test_wrong_slot_resolution_cannot_override_actual_uncertainty(self):
  actual={'id':'u','decision':'uncertain','evidence':'still uncertain'}
  out,audit=bind_uncertain_adjudications({'resolved_ids':['u'],'not_required':[],'uncertainty_reviews':[actual]},{'required':[],'uncertain':[{'id':'u'}]})
  self.assertEqual(out['resolved_ids'],[]);self.assertEqual(out['uncertainty_reviews'],[actual]);self.assertTrue(audit)

 def test_explicit_frame_object_reference_does_not_infer_region(self):
  raw={'examined_regions':[{'frame_id':'a','pair':'frame-000-pair.png'}],'unresolved_regions':[]}
  out,audit=bind_region_coverage_conservatively(raw,[{'frame_id':'a'}]);self.assertEqual(out['examined_regions'],['a']);self.assertEqual(audit[0]['actual_model_objects'],raw['examined_regions'])
  with self.assertRaises(ValueError):bind_region_coverage_conservatively({'examined_regions':[{'name':'guessed'}],'unresolved_regions':[]},[{'frame_id':'a'}])
