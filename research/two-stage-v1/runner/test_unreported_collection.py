import unittest,copy
from bounded_verifier_binding import complete_unreported_finding_collections
class UnreportedTest(unittest.TestCase):
 def test_missing_collection_never_certifies_absence_or_visual_pass(self):
  raw={'new_required_findings':[{'id':'actual reported defect'}],'unresolved_regions':[],'protected_regressions':[]};before=copy.deepcopy(raw)
  out,audit=complete_unreported_finding_collections(raw,[{'frame_id':'a'},{'frame_id':'b'}]);self.assertEqual(raw,before);self.assertEqual(out['new_required_findings'],raw['new_required_findings']);self.assertEqual(out['new_uncertain_findings'],[]);self.assertEqual(out['unresolved_regions'],['a','b']);self.assertTrue(audit)
  full={'new_required_findings':[],'new_uncertain_findings':[],'unresolved_regions':[]};self.assertEqual(complete_unreported_finding_collections(full,[]),(full,[]))
