import json,tempfile,unittest
from pathlib import Path
from planner_execution_evidence import build
class PlannerEvidenceTests(unittest.TestCase):
 def test_exact_measured_geometry_topology_and_existing_source_without_inferred_crop(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'inputs').mkdir();checkpoint=root/'checkpoint';checkpoint.mkdir()
   (root/'inputs/original.png').write_bytes(b'original-fixture')
   (checkpoint/'current.svg').write_text('<svg xmlns="http://www.w3.org/2000/svg"><g id="group"><path id="target" d="M1 2L3 4"/><rect id="sibling" x="7"/></g><rect id="other"/></svg>')
   bounds={'canvas':{'width':20,'height':10},'objects':{'target':{'parent_id':'group','world':[1,0,0,1,0,0],'geometry_bbox':{'left':1,'top':2,'right':3,'bottom':4},'bounds_complete':True},'group':{'geometry_bbox':{'left':1,'top':2,'right':7,'bottom':9}},'sibling':{},'other':{}}}
   (checkpoint/'bounds.json').write_text(json.dumps(bounds));state={'capabilities':{'code_methods':True},'required':[{'target_ids':['group','target'],'neighbor_ids':[],'container_id':'group'}],'uncertain':[]}
   result=build(root,checkpoint,state)
   self.assertEqual(result['native_measured_bounds']['objects']['target']['geometry_bbox'],bounds['objects']['target']['geometry_bbox']);self.assertEqual(result['native_measured_bounds']['objects']['target']['bounds_complete'],True);self.assertEqual(result['native_measured_bounds']['objects']['target'],bounds['objects']['target']);self.assertEqual(json.loads((checkpoint/'bounds.json').read_text()),bounds)
   self.assertEqual(result['svg_objects']['target']['attributes']['d'],'M1 2L3 4')
   self.assertEqual(result['svg_objects']['target']['parent_id'],'group')
   self.assertEqual(result['group_descendant_ids']['group'],['target','sibling'])
   self.assertNotIn('other',result['native_measured_bounds']['objects'])
   self.assertTrue(result['original_asset']['exists']);self.assertNotIn('crop_box',result['original_asset'])
 def test_missing_claimed_target_is_explicit_not_fabricated(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'current.svg').write_text('<svg/>');(root/'bounds.json').write_text('{"objects":{}}')
   result=build(root,root,{'required':[{'target_ids':['missing']}],'uncertain':[]})
   self.assertEqual(result['unbound_issue_object_ids'],['missing']);self.assertEqual(result['svg_objects'],{})
 def test_repair_card_scope_preserves_exact_active_cards_and_all_constructors(self):
  from planner_execution_evidence import scope_method_pack
  pack={'cards':[{'id':'D','rule':'arrow guard'},{'id':'S2','rule':'photo guard'},{'id':'S1','rule':'cuboid guard'}],'constructors':[{'name':'cuboid'},{'name':'arrow'}],'operation_contract':{'must_validate':True}}
  view=scope_method_pack(pack,{'required':[{'category':'D'}],'uncertain':[{'category':'S2'}]})
  self.assertEqual(view['cards'],pack['cards'][:2]);self.assertEqual(view['constructors'],pack['constructors']);self.assertEqual(view['operation_contract'],pack['operation_contract']);self.assertEqual(len(pack['cards']),3)

 def test_disabled_methods_exclude_native_numeric_snapshots(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'current.svg').write_text('<svg><rect id="shape" x="4"/></svg>');(root/'bounds.json').write_text('{"objects":{"shape":{"world":[9,8,7,6,5,4]}}}')
   result=build(root,root,{'capabilities':{'code_methods':False},'required':[{'target_ids':['shape']}],'uncertain':[]})
   self.assertFalse(result['native_measured_bounds']['available']);self.assertNotIn('objects',result['native_measured_bounds']);self.assertEqual(result['svg_objects']['shape']['attributes']['x'],'4')
 def test_review_keeps_all_observation_rubrics_but_only_active_repair_manuals(self):
  from planner_execution_evidence import scope_review_cards
  pack={'cards':[{'id':'F','definition':'overlap rules','observe':['look'],'counterevidence':['source overlap'],'execute':'repair F'},{'id':'S1','definition':'cuboid requirements','observe':['shared edges'],'counterevidence':['not a cuboid'],'execute':'repair cuboid'}],'constructors':['all remain'],'operation_contract':{'guard':True}}
  view=scope_review_cards(pack,{'required':[{'category':'F'}],'uncertain':[]})
  self.assertEqual(view['cards'][0],pack['cards'][0]);self.assertEqual(view['cards'][1]['definition'],pack['cards'][1]['definition']);self.assertEqual(view['cards'][1]['observe'],pack['cards'][1]['observe']);self.assertEqual(view['cards'][1]['counterevidence'],pack['cards'][1]['counterevidence']);self.assertNotIn('execute',view['cards'][1]);self.assertEqual(view['constructors'],pack['constructors'])
