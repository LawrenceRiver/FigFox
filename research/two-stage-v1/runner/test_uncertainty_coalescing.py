import unittest,copy
from bounded_verifier_binding import coalesce_uncertainty_reviews
class CoalesceTest(unittest.TestCase):
 def test_same_decision_actual_evidence_union_not_new_judgment(self):
  report={'uncertainty_reviews':[{'id':'a','decision':'uncertain','evidence':'actual one','target_ids':['real']},{'id':'a','decision':'uncertain','evidence':'actual two'}]};before=copy.deepcopy(report);out,audit=coalesce_uncertainty_reviews(report);self.assertEqual(report,before);self.assertEqual(out['uncertainty_reviews'],[{'id':'a','decision':'uncertain','evidence':'actual one\n\nactual two','target_ids':['real']}]);self.assertTrue(audit)
 def test_conflicting_decisions_cannot_silently_gain_positive_credit(self):
  out,audit=coalesce_uncertainty_reviews({'uncertainty_reviews':[{'id':'a','decision':'resolved','evidence':'one'},{'id':'a','decision':'uncertain','evidence':'two'}]});self.assertEqual(out['uncertainty_reviews'],[]);self.assertTrue(audit)
