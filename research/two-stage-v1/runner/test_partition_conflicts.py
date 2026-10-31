import unittest,copy
from bounded_verifier_binding import conservative_partition_conflicts
class PartitionConflictTest(unittest.TestCase):
 def test_conflicting_false_positive_and_unresolved_cannot_gain_pass(self):
  report={'resolved_ids':[],'unresolved_ids':['a'],'not_required':[{'id':'a','evidence':'actual contradictory model claim'}]};before=copy.deepcopy(report);out,audit=conservative_partition_conflicts(report);self.assertEqual(report,before);self.assertEqual(out['not_required'],[]);self.assertEqual(out['unresolved_ids'],['a']);self.assertTrue(audit)
