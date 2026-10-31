import unittest,copy
from proposal_review_shape_adapter import normalize
class ReviewShapeTest(unittest.TestCase):
 def test_actual_decision_and_evidence_remain_exact(self):
  raw={'id':'p','kind':'text_low_visible_ink','category':'text_low_visible_ink','decision':'uncertain','target_ids':['text'],'description':'actual uncertainty','original_evidence':'source evidence','current_evidence':'current evidence'};payload={'proposal_reviews':[raw],'new_semantic_issues':[],'plan':{'programs':[]}};before=copy.deepcopy(payload)
  result,audit=normalize(payload,{'proposals':[{'id':'p','kind':'text_low_visible_ink','target_ids':['text']}]})
  self.assertEqual(payload,before);finding=result['new_semantic_issues'][0];self.assertEqual(finding['decision'],'uncertain');self.assertEqual(finding['current_evidence'],raw['current_evidence']);self.assertEqual(result['plan'],payload['plan']);self.assertTrue(audit)
  with self.assertRaises(ValueError):normalize(payload,{'proposals':[{'id':'p','kind':'text_low_visible_ink','target_ids':['foreign']}]})

 def test_explicit_category_can_supply_identical_catalog_kind_without_duplicate_field(self):
  raw={'id':'p','category':'text_mask_overlap_group','decision':'confirmed','target_ids':['text'],'description':'actual observed overlap','original_evidence':'source','current_evidence':'current'}
  result,_=normalize({'proposal_reviews':[raw],'new_semantic_issues':[]},{'proposals':[{'id':'p','kind':'text_mask_overlap_group','target_ids':['text']}]})
  self.assertEqual(result['new_semantic_issues'][0]['category'],'F');self.assertNotIn('kind',raw)
  with self.assertRaises(ValueError):normalize({'proposal_reviews':[raw],'new_semantic_issues':[]},{'proposals':[{'id':'p','kind':'continuous_orthogonal_path','target_ids':['text']}]})
