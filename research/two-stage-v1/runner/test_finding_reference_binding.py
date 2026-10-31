import unittest,copy
from bounded_verifier_binding import bind_exact_finding_references
class ReferenceTest(unittest.TestCase):
 def test_only_exact_unique_source_reference_changes_namespace(self):
  state={'required':[],'uncertain':[{'id':'semantic:raw','source_issue_id':'raw'}]};report={'resolved_ids':[],'unresolved_ids':[],'uncertainty_reviews':[{'id':'main:raw','decision':'confirmed','evidence':'actual visual judgment'}]};before=copy.deepcopy(report);out,audit=bind_exact_finding_references(report,state);self.assertEqual(report,before);self.assertEqual(out['uncertainty_reviews'][0],{**before['uncertainty_reviews'][0],'id':'semantic:raw'});self.assertTrue(audit)
  state['uncertain'].append({'id':'main:raw','source_issue_id':'raw'})
  self.assertEqual(bind_exact_finding_references({'uncertainty_reviews':[{'id':'raw','decision':'uncertain'}]},state)[0]['uncertainty_reviews'][0]['id'],'raw')
