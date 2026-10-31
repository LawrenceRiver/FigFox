"""Synthetic contracts only: no figure inputs or executor invocation."""
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
C=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(C));sys.path.insert(0,str(C/'source/src'))
import brief
from category_profile import build_profile_pack,build_native_contract
from figfox_plus.native.review_problem_first_v13 import methods,lean_inspection

class BriefContracts(unittest.TestCase):
 def cell(self, root, enabled):
  root.mkdir();(root/'inputs').mkdir()
  policy={'version':'capabilities-v1','sam':True,'code_methods':enabled}
  sha=hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()
  (root/'inputs/capabilities.json').write_text(json.dumps({'policy':policy,'sha256':sha}))
  (root/'inputs/observer-assignment.json').write_text(json.dumps({'format':'observer-assignment-v1','mode':'enabled' if enabled else 'disabled_by_assignment','capability_sha256':sha}))
  return policy,brief.prepare_contracts(root)
 def test_actual_off_contract_and_all_role_dispatches(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'code-off';policy,record=self.cell(root,False)
   pack=build_profile_pack(methods,lean_inspection,capabilities=policy)
   self.assertEqual(pack['sources'],{});self.assertEqual(pack['helpers'],{});self.assertEqual(pack['constructors'],[]);self.assertEqual(pack['cards'],[])
   self.assertNotIn('CURRENT_TP',json.dumps(pack));self.assertNotIn('args.source_crop',json.dumps(pack));self.assertNotIn('measurement_viewport',json.dumps(pack));self.assertEqual(pack['operation_contract'],{})
   contract=build_native_contract(root,pack,capabilities=policy)
   self.assertEqual(contract['native_sources'],[])
   self.assertIn('OUTPUT_SVG',contract['runtime_contract']['generated_python'])
   for role in ('main','semantic','planner','verifier'):
    rendered=brief.render_brief(root,'run1',role,1 if role in ('planner','verifier') else None,off_stage=[root/'runs/run1/state.json'])
    for forbidden in ('source/src/','CURRENT_TP','target_tp','tp.json','proposals.json','analysis/manifest','args.source_crop','measurement_viewport','kind as geometry'):
     self.assertNotIn(forbidden,rendered)
    self.assertIn('disabled_by_assignment',rendered)
    self.assertIn('generated_python',rendered)
 def test_finite_views_and_status_projection(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'code-off';self.cell(root,False)
   run=root/'runs/run1';checkpoint=run/'checkpoint';(checkpoint/'pack').mkdir(parents=True)
   (checkpoint/'current.svg').write_text('<svg><g id="real"/></svg>')
   (checkpoint/'current.png').write_bytes(b'png');(checkpoint/'bounds.json').write_text('{"TP_SENTINEL":123}')
   (checkpoint/'pack/f1-pair.png').write_bytes(b'png')
   (checkpoint/'pack/pack.json').write_text(json.dumps({'frames':[{'frame_id':'f1','pair':'f1-pair.png','bbox':[991,992,993,994]}]}))
   rd=run/'round-1';rd.mkdir();(rd/'candidate').mkdir();out=run/'jobs/verifier-1';out.mkdir(parents=True)
   raw={'images':{'case':{'revision':'abc','svg':'HIDDEN_PATH'}},'rcd':[{'program_id':'p1','status':'failed','error':'bad guard','measurement':{'bbox':[991,992,993,994]},'convergence':{'status':'unresolved','check_id':'c1'}}]}
   (rd/'native-result.json').write_text(json.dumps(raw))
   (rd/'candidate.json').write_text(json.dumps({'revision':'a'*64,'evidence_hashes':{'current_svg':'a'*64},'required_regions':[]}))
   paths=brief.prepare_off_views(root,'run1','verifier',1,out)
   self.assertTrue(all(not x.is_dir() for x in paths))
   self.assertNotIn(rd/'native-result.json',paths);self.assertNotIn(checkpoint/'bounds.json',paths)
   visible=''.join(x.read_text() for x in paths if x.exists() and x.suffix=='.json')
   self.assertNotIn('991',visible);self.assertNotIn('TP_SENTINEL',visible);self.assertNotIn('HIDDEN_PATH',visible)
   projection=json.loads((out/'native-status.json').read_text());self.assertEqual(projection['record_count'],1)
   self.assertIn('bad guard',visible);self.assertIn('unresolved',visible);self.assertIn('c1',visible)
   with self.assertRaises(ValueError):brief.project_native_result({'rcd':[{'unexpected':1}]})
 def test_enabled_verifier_requires_bridge(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'code-on';self.cell(root,True)
   with self.assertRaises(ValueError):brief.render_brief(root,'run1','verifier',1)
   prompt=brief.render_brief(root,'run1','verifier',1,connector_stage=[root/'packet.json'],connector_context={'candidate_receipt_sha256':'abc','raster_aliases':{'before':'b'}})
   self.assertIn('Host connector context',prompt);self.assertIn('packet.json',prompt);self.assertIn('connector_paint_ack',prompt)
 def test_common_quality_hashes_same(self):
  with tempfile.TemporaryDirectory() as tmp:
   _,on=self.cell(Path(tmp)/'code-on',True);_,off=self.cell(Path(tmp)/'code-off',False)
   self.assertEqual(on['common_hashes'],off['common_hashes'])
   on_prompt=brief.render_brief(Path(tmp)/'code-on','run1','semantic')
   self.assertIn('source/src/',on_prompt);self.assertIn('proposals.json',on_prompt)

if __name__=='__main__':unittest.main()
