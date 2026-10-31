import unittest
import bounded_native_profile as profile
class ProfileTests(unittest.TestCase):
 def test_disabled_profile_removes_only_empty_unrequested_metadata(self):
  report={'connector_paint_ack':None,'connector_visual_concerns':[],'unresolved_ids':['still-broken'],'protected_regressions':['regression']}
  effective,audit=profile.normalize(report,False)
  self.assertEqual(effective,{'unresolved_ids':['still-broken'],'protected_regressions':['regression']});self.assertIn('connector_paint_ack',report);self.assertTrue(audit)
  with self.assertRaises(ValueError):profile.normalize({'connector_visual_concerns':[{'actual':'concern'}]},False)
  self.assertEqual(profile.normalize(report,True)[0],report)

 def test_explicit_not_supplied_note_is_not_an_enabled_feature_ack(self):
  report={'connector_paint_ack':{'status':'not_supplied','reason':'No packet supplied'},'protected_regressions':['real regression']}
  result,audit=profile.normalize(report,False)
  self.assertEqual(result,{'protected_regressions':['real regression']});self.assertEqual(audit[0]['original_value'],report['connector_paint_ack'])
  with self.assertRaises(ValueError):profile.normalize({'connector_paint_ack':{'status':'not_supplied','reason':'no packet','packet_sha256':'foreign'}},False)
