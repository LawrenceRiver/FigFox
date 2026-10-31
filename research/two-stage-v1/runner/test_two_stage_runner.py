import unittest,tempfile,json,uuid
from pathlib import Path
from unittest.mock import patch
import two_stage_runner as runner
import live_api,run_ablation as r
class TwoStageNativeSimulation(unittest.TestCase):
 def test_shared_initial_two_C_branches_three_calls_each_no_scores(self):
  from PIL import Image
  with tempfile.TemporaryDirectory(prefix='figfox-two-stage-synthetic-',delete=False) as tmp:
   root=Path(tmp);image=root/'source.png';Image.new('RGB',(64,64),'white').save(image)
   if getattr(self,'nonempty',False):
    from PIL import ImageDraw
    fixture=Image.open(image);ImageDraw.Draw(fixture).rectangle((16,8,39,39),fill='blue');fixture.save(image)
   config=r.read(runner.CFG);row={'sample_id':'synthetic-only','cell':'S0C0','sam':False,'external_code':False,'source_image_path':str(image),'source_image_sha256':r.sha(image),'provider':'deepseek','slot_providers':{'first':'openai','score':'deepseek_score'}}
   calls=[]
   class Lease:
    current=''
    def _find(self,provider,slot):return {'request_id':str(uuid.uuid5(uuid.NAMESPACE_URL,slot))}
    def send(self,provider,slot,body,send):self.current=slot;calls.append(slot);return send(self._find(provider,slot)['request_id'])
    def close(self):pass
   initial_lease=Lease();current=[initial_lease]
   def reserve(*args,**kwargs):
    lease=Lease();current[0]=lease;return lease
   def callback(provider,body,rid):
    slot=current[0].current
    if '/first/' in slot:
     return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':getattr(self,'initial_svg','<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect id="shape" x="8" y="8" width="32" height="32" fill="blue"/></svg>')}]}],'usage':{'input_tokens':1,'output_tokens':1}}
    cell=slot.split('/')[1];native=root/row['sample_id']/cell/'cell';state=r.read(native/'runs/run1/state.json');snapshot=r.read(native/'runs/run1/round-1/candidate.json') if '/verifier/' in slot else state;checkpoint=Path(snapshot.get('candidate_folder',native/'runs/run1/checkpoint'));frames=[x['frame_id'] for x in r.read(checkpoint/'pack/pack.json')['frames']]
    base={'revision':snapshot['revision'],'evidence_hashes':snapshot['evidence_hashes'],'examined_regions':frames,'unresolved_regions':[]}
    if '/main/' in slot:
     main={**base,'issues':[],'programs':[]};semantic={**base,'issues':[],'programs':[]};proposals=native/'inputs/analysis/proposals.json'
     if proposals.exists() and not getattr(self,'defer_reviews',False):semantic['proposal_reviews']=[{'proposal_id':p['id'],'decision':'qualified','source_evidence':'Synthetic fixture only.','current_evidence':'Synthetic fixture only.','necessity_reason':'Synthetic transport test, not quality evidence.','issue_ids':[]} for p in r.read(proposals)['proposals']]
     if getattr(self,'invalid_reviews',False) and proposals.exists() and r.read(proposals).get('proposals'):
      semantic['issues']=[{'id':'synthetic-confirmed','image_id':'case','category':'A','decision':'confirmed','description':'Synthetic-only frozen finding; not real experiment evidence.','original_evidence':'Synthetic fixture source.','current_evidence':'Synthetic fixture current.','target_ids':['faint'],'neighbor_ids':[],'container_id':None}]
      semantic['proposal_reviews']=[{'proposal_id':p['id'],'decision':'uncertain','source_evidence':'Synthetic source.','current_evidence':'Synthetic current.','necessity_reason':'Intentionally invalid review linking confirmed finding.','issue_ids':['synthetic-confirmed']} for p in r.read(proposals)['proposals']]
     if getattr(self,'nonempty',False):semantic['issues']=[{'id':'synthetic-shape','image_id':'case','category':'C','decision':'confirmed','description':'Synthetic fixture rectangle horizontal extent differs.','original_evidence':'Synthetic source rect x16 width24.','current_evidence':'Synthetic SVG rect x8 width32.','target_ids':['shape'],'neighbor_ids':[],'container_id':None}]
     answer={'main':main,'semantic':semantic}
    elif '/planner/' in slot:answer={**base,'issues':state['required']+state['uncertain'],'programs':[],'unresolved_reasons':[]}
    else:answer={**base,'resolved_ids':[],'unresolved_ids':[x['id'] for x in state['required']],'not_required':[],'new_required_findings':[],'new_uncertain_findings':[],'protected_regressions':[],'pending_observation_reviews':[{'id':p['id'],'decision':'defer','evidence':'Synthetic fixture, keep uncertain.'} for p in state.get('pending_observations',[])]}
    if '/planner/' in slot and getattr(self,'nonempty',False):
     program={'id':'synthetic-fix','image_id':'case','issue_ids':[state['required'][0]['id']],'base_revision':state['revision'],'phase':'reconstructor','route':'generated_python','target_ids':['shape'],'depends_on':[],'rcd_predescription':'Synthetic integration fixture: change only shape x/width; preserve IDs and all other nodes.','source_code':"import xml.etree.ElementTree as ET\ntree=ET.parse(INPUT_SVG)\nfor node in tree.getroot().iter():\n if node.get('id')=='shape': node.set('x','16'); node.set('width','24')\ntree.write(OUTPUT_SVG,encoding='unicode')\n"}
     answer['programs']=[program]
    if '/verifier/' in slot and getattr(self,'nonempty',False):
     self.assertNotEqual(snapshot['revision'],snapshot['before_revision'],'real executor must change SVG');self.actual_repair_seen=getattr(self,'actual_repair_seen',0)+1
    if '/planner/' in slot and any(part.get('type')=='text' and part.get('text','').startswith('This is the SECOND') for part in body['messages'][-1]['content']):
     proposals=r.read(native/'inputs/analysis/proposals.json')['proposals'];self.assertTrue(proposals);self.supplement_seen=True
     if getattr(self,'invalid_reviews',False):
      import joint_detector_adapter
      joint_detector_adapter.register(native,'run1',native.parent/('B'+str(1+int(cell[-1]))+'1-model.json'))
     if getattr(self,'invalid_reviews',False):
      from planner_packet_transport import decode_wire
      text=next(part['text'] for part in body['messages'][-1]['content'] if part.get('type')=='text' and part.get('text','').startswith('This is the SECOND'));packet=decode_wire(text);answer.pop('issues',None);answer['issue_ids']=[issue['id'] for issue in packet['active_required']+packet['active_uncertain']]
     answer={'proposal_reviews':[{'proposal_id':p['id'],'decision':'qualified','source_evidence':'Synthetic source fixture only.','current_evidence':'Synthetic native transport fixture only.','necessity_reason':'Wiring test preserves evidence and does not establish actual quality.','issue_ids':[]} for p in proposals],'new_semantic_issues':[],'plan':answer}
    if '/verifier/' in slot and snapshot.get('connector_paint'):
     packet=r.read(native/'runs/run1/round-1/connector-paint/packet.json');ctx=r.read(native/'runs/run1/jobs/verifier-1/connector-concern-context.json')
     answer['connector_paint_ack']={**snapshot['connector_paint'],'candidate_receipt_sha256':ctx['candidate_receipt_sha256'],**{k:packet[k] for k in ('source_sha256','before','candidate','field_status')},'use':'attention_hint_only'}
     answer.update(connector_concern_reviews=[],connector_visual_concerns=[])
    if '/verifier/' in slot and not row.get('external_code'):answer.setdefault('connector_paint_ack',None)
    return {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(answer)}}],'usage':{'prompt_tokens':1,'completion_tokens':1}}
   config['_mock_send']=callback
   for pc in config['providers'].values():pc.update(context_tokens=100000000,max_input_tokens=99000000,max_request_bytes=100000000)
   with patch.object(runner,'CONTROL',root),patch.object(runner,'CURRENT_CONFIG',config),patch.object(runner,'CFG_NATIVE',config['native_python']),patch.object(runner,'CURRENT_ROW',row),patch.object(runner.budget,'reserve_recovery',side_effect=reserve):
    first=live_api.run_first({'output_root':str(root/'initial'),'adapter':config['first_stage_adapter_root'],'native_source_root':config['native_source_root'],'runtime_json':config['runtime_json'],'original_png':str(image),'capabilities':{'version':'capabilities-v1','sam':False,'code_methods':False}},{**config,'current_sample_id':row['sample_id'],'current_cell':'S0C0'},initial_lease)
    for enabled in [False,True]:
     result=runner.branch({**row,'cell':'S0C'+str(int(enabled)),'external_code':enabled},1,first,config,{'simulation':True})
     self.assertEqual(result['status'],'complete');self.assertFalse(result['native_state']['visual_passed']);self.assertIn('deferred',result['evaluation'])
   self.assertEqual(len([slot for slot in calls if '/first/' in slot]),1)
   self.assertEqual(len([slot for slot in calls if '/S0C0/' in slot and '/first/' not in slot]),3)
   self.assertEqual(len([slot for slot in calls if '/S0C1/' in slot]),3)
   self.assertFalse(any('/score/' in slot for slot in calls))

 def test_nonempty_observer_reviews_share_second_call_with_plan(self):
  self.defer_reviews=True;self.supplement_seen=False
  self.initial_svg='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect id="bg" width="64" height="64" fill="white"/><text id="faint" x="2" y="40" font-size="24" fill="#eeeeee">Test</text></svg>'
  self.test_shared_initial_two_C_branches_three_calls_each_no_scores()
  self.assertTrue(self.supplement_seen,'fixture must exercise nonempty actual observation proposals')

 def test_nonempty_native_execution_with_real_change_keeps_unresolved_verdict(self):
  self.nonempty=True;self.actual_repair_seen=0
  self.test_shared_initial_two_C_branches_three_calls_each_no_scores()
  self.assertEqual(self.actual_repair_seen,2)

 def test_invalid_existing_proposal_review_is_corrected_inside_second_call(self):
  self.invalid_reviews=True;self.supplement_seen=False
  self.initial_svg='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect id="bg" width="64" height="64" fill="white"/><text id="faint" x="2" y="40" font-size="24" fill="#eeeeee">Test</text></svg>'
  self.test_shared_initial_two_C_branches_three_calls_each_no_scores()
  self.assertTrue(self.supplement_seen)
