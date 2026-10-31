import unittest,copy
from bounded_verifier_binding import reject_impossible_resolution_credit
class CreditTest(unittest.TestCase):
 def test_unchanged_cannot_gain_positive_credit_or_false_positive_judgment(self):
  report={'resolved_ids':['real'],'unresolved_ids':[],'not_required':[],'uncertainty_reviews':[{'id':'u','decision':'resolved','evidence':'actual unsupported model claim'}]};before=copy.deepcopy(report)
  result,audit=reject_impossible_resolution_credit(report,{'revision':'same'},{'revision':'same'});self.assertEqual(report,before);self.assertEqual(result['unresolved_ids'],['real']);self.assertEqual(result['not_required'],[]);self.assertEqual(result['uncertainty_reviews'],[]);self.assertTrue(audit)
  self.assertEqual(reject_impossible_resolution_credit(report,{'revision':'before'},{'revision':'changed'})[0],report)
