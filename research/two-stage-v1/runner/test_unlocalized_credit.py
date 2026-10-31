import unittest,copy
from bounded_verifier_binding import withhold_unlocalized_target_credit
class UnlocalizedTest(unittest.TestCase):
 def test_invalid_location_cannot_be_silently_counted_repaired(self):
  state={'required':[{'id':'a','unresolved_target_references':['ghost']}],'uncertain':[]};report={'resolved_ids':['a'],'unresolved_ids':[],'not_required':[]};before=copy.deepcopy(report)
  out,audit=withhold_unlocalized_target_credit(report,state);self.assertEqual(report,before);self.assertEqual(out['resolved_ids'],[]);self.assertEqual(out['unresolved_ids'],['a']);self.assertTrue(audit)
