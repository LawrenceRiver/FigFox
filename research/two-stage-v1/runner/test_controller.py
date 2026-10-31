"""Offline simulation tests; no live experiment evidence."""
import tempfile, unittest, json, hashlib
from pathlib import Path
from unittest.mock import patch
import run_ablation as r
class ControllerTests(unittest.TestCase):
 def test_completed_native_checkpoint_can_be_scored_without_regeneration(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);checkpoint=p/'checkpoint';checkpoint.mkdir();original=p/'source.png';original.write_bytes(b'original');(checkpoint/'current.svg').write_text('<svg/>');(checkpoint/'current.png').write_bytes(b'rendered')
   row={'sam':False,'external_code':False,'source_image_path':str(original),'source_image_sha256':r.sha(original)};state={'runtime_finished_monotonic_ns':1,'capabilities':{'version':'capabilities-v1','sam':False,'code_methods':False},'revision':r.sha(checkpoint/'current.svg'),'evidence_hashes':{'original_png':r.sha(original),'current_svg':r.sha(checkpoint/'current.svg'),'current_png':r.sha(checkpoint/'current.png')}};r.write(p/'state.json',state)
   self.assertEqual(r.reusable_finished_native(p/'state.json',row)['final_png'],str(checkpoint/'current.png'))
   (checkpoint/'current.png').write_bytes(b'changed')
   with self.assertRaises(ValueError):r.reusable_finished_native(p/'state.json',row)
 def test_reuse_first_requires_original_bytes_and_same_capabilities(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);original=p/'source.png';original.write_bytes(b'original');svg=p/'first.svg';svg.write_text('<svg/>');policy={'version':'capabilities-v1','sam':False,'code_methods':True}
   r.write(p/'provenance.json',{'origin':'actual frozen native.pipeline.first automatic isolated provider callback','original_png_sha256':r.sha(original),'initial_svg_sha256':r.sha(svg),'capability_sha256':r.digest(policy)})
   first={'stage0_scene':str(svg),'original':str(original),'provenance':str(p/'provenance.json')};r.write(p/'result.json',first)
   row={'sam':False,'external_code':True,'source_image_path':str(original),'source_image_sha256':r.sha(original)}
   self.assertEqual(r.reusable_first(p/'result.json',row),first)
   with self.assertRaises(ValueError):r.reusable_first(p/'result.json',{**row,'sam':True})
   svg.write_text('<svg>changed</svg>')
   with self.assertRaises(ValueError):r.reusable_first(p/'result.json',row)
 def test_sam_preparer_uses_explicit_verified_local_dependency(self):
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp);source=out/'sam.py';source.write_text('verified dependency')
   c={'native_source_root':'frozen','sam_preparer_source_root':'installed','sam_preparer_files':{str(source):r.sha(source)},'sam_service_url':'local','adapter_root':str(out/'adapter')}
   calls=[]
   def native(argv,config,log):
    calls.append(argv)
    if len(calls)==1:r.write(out/'sam-catalog.json',{'source_hash':'fixture'})
   with patch.object(r,'native',side_effect=native):r.sam_for({'sample_id':'a','source_image_path':'original'},c,out)
   self.assertEqual(calls[0][4],'installed')
   source.write_text('changed')
   (out/'sam-catalog.json').unlink()
   with patch.object(r,'native',side_effect=AssertionError('changed dependency ran')):
    with self.assertRaisesRegex(ValueError,'SAM preparer'):r.sam_for({'sample_id':'a','source_image_path':'original'},c,out)
 def test_capped_plan_uses_sample_envelopes(self):
  from decimal import Decimal
  rows=[{'sample_id':'a','cell':'S0C0'},{'sample_id':'b','cell':'S0C0'}]
  c={'sample_cap_usd':5,'ledger_path':'unused','expected_cap_usd':10,'sam_service_url':'local'}
  with patch.object(r,'validate',return_value=(rows,{'a':rows[:1],'b':rows[1:]},{})),patch.object(r.budget,'plan_block',return_value=[{'reserve_usd':Decimal(60)}]),patch.object(r.budget,'inspect_budget',return_value={'available_usd':Decimal(10)}):
   p=r.plan(c);self.assertEqual(p['first_block_upper_usd'],5);self.assertEqual(p['all_cells_upper_usd'],10)
 def test_resume_rejects_changed_final_bytes(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'final';p.write_text('real receipt bytes');record={'status':'complete','bindings':{'frozen':1},'final_svg':str(p),'final_png':str(p),'final_svg_sha256':r.sha(p),'final_png_sha256':r.sha(p)}
   self.assertTrue(r.complete_valid(record,{'frozen':1}));p.write_text('tampered');self.assertFalse(r.complete_valid(record,{'frozen':1}))
 def test_plan_never_reserves_and_reports_exact_shortage(self):
  from decimal import Decimal
  rows=[{'sample_id':'fixture','cell':'S0C0'}];config={'providers':{},'ledger_path':'unused','expected_cap_usd':15,'sam_service_url':'local'}
  with patch.object(r,'validate',return_value=(rows,{'fixture':rows},{'frozen':1})),patch.object(r.budget,'plan_block',return_value=[{'reserve_usd':Decimal('2.10')}]),patch.object(r.budget,'inspect_budget',return_value={'available_usd':Decimal('0.20')}),patch.object(r.budget,'reserve_block',side_effect=AssertionError('must not reserve')),patch.object(r.live_api,'transport',side_effect=AssertionError('must not send')):
   x=r.plan(config);self.assertEqual(x['first_block_shortage_usd'],Decimal('1.90'));self.assertEqual(x['http_calls'],0)
 def test_missing_sam_blocks_before_api(self):
  with tempfile.TemporaryDirectory() as d,patch.object(r.live_api,'run_first',side_effect=AssertionError('must not send')):
   with self.assertRaisesRegex(ValueError,'before first API'):r.sam_for({'sample_id':'fixture'},{},Path(d))
 def test_unknown_outputs_remain_unknown(self):
  with tempfile.TemporaryDirectory() as d:
   row={'sample_id':'fixture','cell':'S0C0','source_group':'group'};r.report(Path(d),[row],[{'row':row,'status':'failed_unknown'}]);x=json.loads((Path(d)/'overall.json').read_text());self.assertEqual(x['unknown_cells'],320);self.assertEqual(x['primary_usable_denominator'],80)
class NativeLifecycleSimulation(unittest.TestCase):
 def test_transport_recovery_keeps_completed_native_stages_and_first_generation(self):
  from PIL import Image
  c=r.read(Path(r.__file__).with_name('config.json'))
  with tempfile.TemporaryDirectory() as tmp:
   out=Path(tmp);original=out/'original.png';Image.new('RGB',(64,64),'white').save(original);folder=out/'attempt';folder.mkdir();root=folder/'cell'
   class Lease:
    current='';calls=[]
    def send(self,provider,slot,body,send):self.current=slot;self.calls.append(slot);return send('synthetic-no-http')
   lease=Lease();failed=[False]
   def callback(provider,body,rid):
    slot=lease.current
    if '/semantic/' in slot and not failed[0]:failed[0]=True;raise r.live_api.ProviderHTTPError(402,'synthetic funding interruption')
    if '/first/' in slot:answer='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64"><rect id="shape" x="10" y="10" width="20" height="20"/></svg>'
    elif '/score/' in slot:answer={'items':[{'id':f'D{i:02}','status':'unknown','evidence':'Synthetic only.'} for i in range(1,19)]}
    else:
     state=r.read(root/'runs/run1/state.json');snapshot=r.read(root/'runs/run1/round-1/candidate.json') if '/verifier/' in slot else state;checkpoint=Path(snapshot.get('candidate_folder',root/'runs/run1/checkpoint'));frames=[f['frame_id'] for f in r.read(checkpoint/'pack/pack.json')['frames']];answer={'revision':snapshot['revision'],'evidence_hashes':snapshot['evidence_hashes'],'examined_regions':frames,'unresolved_regions':[]}
     if '/planner/' in slot:answer.update(issues=[],programs=[],unresolved_reasons=[])
     elif '/verifier/' in slot:answer.update(resolved_ids=[],unresolved_ids=[],not_required=[],new_required_findings=[],new_uncertain_findings=[],protected_regressions=[])
     else:answer.update(issues=[],programs=[])
    text=answer if isinstance(answer,str) else json.dumps(answer)
    if provider=='openai':return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':text}]}],'usage':{'input_tokens':1,'output_tokens':1}}
    return {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':text}}],'usage':{'prompt_tokens':1,'completion_tokens':1}}
   c['_mock_send']=callback
   for p in c['providers'].values():p.update(context_tokens=100000000,max_input_tokens=99000000,max_request_bytes=100000000)
   row={'sample_id':'synthetic','cell':'S0C0','sam':False,'external_code':False,'source_image_path':str(original),'source_image_sha256':r.sha(original)}
   with self.assertRaises(r.live_api.ProviderHTTPError):r.cell(row,c,lease,folder,None)
   recovered=out/'recovered';recovered.mkdir();result=r.cell(row,c,lease,recovered,None,first_receipt=folder/'first/result.json',resume_cell_root=root)
   self.assertEqual(result['status'],'complete');self.assertEqual(sum('/first/' in x for x in lease.calls),1);self.assertEqual(sum('/main/' in x for x in lease.calls),1)
 def test_single_cell_real_native_lifecycle_fake_provider(self):
  """Real renderer/state/CLI, synthetic provider only; not model-quality evidence."""
  from PIL import Image
  config=r.read(Path(r.__file__).with_name('config.json'))
  with tempfile.TemporaryDirectory(prefix='figfox-formal-synthetic-') as d:
   out=Path(d);original=out/'original.png';Image.new('RGB',(64,64),'white').save(original)
   folder=out/'attempt';folder.mkdir();root=folder/'cell'
   class FakeLease:
    current='';calls=[]
    def send(self,provider,slot,body,send):
     self.current=slot;self.calls.append(slot);return send('synthetic-no-http')
   lease=FakeLease()
   def callback(provider,body,request_id):
    slot=lease.current
    if '/first/' in slot:answer='<svg xmlns="http://www.w3.org/2000/svg" width="64" height="64" viewBox="0 0 64 64"><g id="frame" data-plus-kind="frame"><rect id="object7" x="16" y="16" width="32" height="32" fill="#3388aa"/></g></svg>'
    elif '/score/' in slot:answer={'items':[{'id':f'D{i:02}','status':'unknown','evidence':'Synthetic wiring test; no quality claim.'} for i in range(1,19)]}
    else:
     state=r.read(root/'runs/run1/state.json');snapshot=state
     if '/verifier/' in slot:snapshot=r.read(root/'runs/run1/round-1/candidate.json')
     checkpoint=Path(snapshot.get('candidate_folder',root/'runs/run1/checkpoint'));pack=r.read(checkpoint/'pack/pack.json');frames=[x['frame_id'] for x in pack['frames']]
     answer={'revision':snapshot['revision'],'evidence_hashes':snapshot['evidence_hashes'],'examined_regions':frames,'unresolved_regions':[]}
     if '/planner/' in slot:answer.update(issues=[],programs=[],unresolved_reasons=[])
     elif '/verifier/' in slot:answer.update(resolved_ids=[],unresolved_ids=[],not_required=[],new_required_findings=[],new_uncertain_findings=[],protected_regressions=[])
     else:answer.update(issues=[],programs=[])
    text=answer if isinstance(answer,str) else json.dumps(answer)
    if provider=='openai':return {'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':text}]}],'usage':{'input_tokens':1,'output_tokens':1}}
    return {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':text}}],'usage':{'prompt_tokens':1,'completion_tokens':1}}
   config['_mock_send']=callback
   # Explicit simulation envelope admits fixture packets without any live send.
   for provider in config['providers'].values():provider.update(context_tokens=100000000,max_input_tokens=99000000,max_request_bytes=100000000)
   row={'sample_id':'synthetic-only','cell':'S0C0','sam':False,'external_code':False,'source_image_path':str(original)}
   result=r.cell(row,config,lease,folder,None)
   self.assertEqual(result['status'],'complete');self.assertTrue(Path(result['final_svg']).is_file());self.assertIsNotNone(result['native_state']['runtime_finished_monotonic_ns']);self.assertEqual(len(lease.calls),7)

class ExecutionSimulationTests(unittest.TestCase):
 def test_default_never_advances_past_failed_condition(self):
  class Lease:
   def inspect_attempts(self):return []
   def retire_cell(self,*args):pass
  with tempfile.TemporaryDirectory() as tmp:
   rows=[{'sample_id':'a','cell':cell,'source_group':'g'} for cell in ('S0C0','S0C1')]
   with patch.object(r,'plan',return_value={'missing':[],'budget':{'blocked':False},'first_block_shortage_usd':0}),patch.object(r,'validate',return_value=(rows,{'a':rows},{})),patch.object(r,'sam_for',return_value='synthetic'),patch.object(r.budget,'reserve_block',return_value=Lease()),patch.object(r,'cell',side_effect=ValueError('integration broken')) as call:
    with self.assertRaisesRegex(RuntimeError,'recover'):r.execute({'output_root':tmp})
    self.assertEqual(call.call_count,1)
 def test_budget_stop_never_advances_to_next_image(self):
  class Lease:
   def inspect_attempts(self):return []
   def retire_cell(self,*args):pass
  with tempfile.TemporaryDirectory() as tmp:
   groups={s:[{'sample_id':s,'cell':c,'source_group':s} for c in ('S0C0','S0C1','S1C0','S1C1')] for s in ('a','b')};rows=sum(groups.values(),[])
   def cell(row,*args):
    if row['sample_id']=='a':raise r.budget.SampleBudgetExceeded('hard cap')
    raise ValueError('synthetic terminal failure')
   with patch.object(r,'plan',return_value={'missing':[],'budget':{'blocked':False},'first_block_shortage_usd':0}),patch.object(r,'validate',return_value=(rows,groups,{'frozen':1})),patch.object(r,'sam_for',return_value='synthetic'),patch.object(r.budget,'reserve_block',return_value=Lease()),patch.object(r,'cell',side_effect=cell) as call:
    with self.assertRaisesRegex(RuntimeError,'recover'):r.execute({'output_root':tmp})
    self.assertEqual(call.call_count,1);run=next(Path(tmp).glob('*/identity.json')).parent
    self.assertEqual(r.read(run/'overall.json')['budget_capped_cells'],1)
 def test_terminal_failure_and_resume_wait_for_repair_without_new_calls(self):
  class Lease:
   def inspect_attempts(self):return []
   def retire_cell(self,sample,cell):self.retired=getattr(self,'retired',[])+[(sample,cell)]
  with tempfile.TemporaryDirectory() as d:
   rows=[{'sample_id':'fixture','cell':c,'source_group':'group'} for c in ('S0C0','S0C1','S1C0','S1C1')];c={'output_root':d};binding={'fixture':1}
   lease=Lease()
   with patch.object(r,'plan',return_value={'missing':[],'budget':{'blocked':False},'first_block_shortage_usd':0}),patch.object(r,'validate',return_value=(rows,{'fixture':rows},binding)),patch.object(r,'sam_for',return_value='simulation'),patch.object(r.budget,'reserve_block',return_value=lease),patch.object(r,'cell',side_effect=ValueError('invalid model JSON')) as call:
    with self.assertRaisesRegex(RuntimeError,'recover'):r.execute(c)
    run=next(Path(d).glob('*/identity.json')).parent
    with self.assertRaisesRegex(RuntimeError,'recover'):r.execute(c,str(run))
    self.assertEqual(call.call_count,1);self.assertEqual(len(lease.retired),2)
    result=r.read(run/'overall.json');self.assertEqual(result['terminal_failed_cells'],1)
 def test_interrupted_before_any_native_or_http_is_restartable(self):
  class Lease:
   def inspect_attempts(self):return []
   def retire_cell(self,sample,cell):self.retired=getattr(self,'retired',[])+[(sample,cell)]
  with tempfile.TemporaryDirectory() as d:
   rows=[{'sample_id':'fixture','cell':'S0C0','source_group':'group'}];c={'output_root':d};binding={'fixture':1};run=Path(d)/str(__import__('uuid').uuid4());run.mkdir();r.write(run/'identity.json',{'run_uuid':run.name,'config_sha256':r.digest(c),'bindings':binding});out=run/'fixture/S0C0';r.write(out/'started.json',{'row':rows[0],'bindings':binding})
   with patch.object(r,'plan',return_value={'missing':[]}),patch.object(r,'validate',return_value=(rows,{'fixture':rows},binding)),patch.object(r,'sam_for',return_value='simulation'),patch.object(r.budget,'reserve_block',return_value=Lease()),patch.object(r,'cell',side_effect=ValueError('invalid model JSON')) as call:
    with self.assertRaisesRegex(RuntimeError,'recover'):r.execute(c,str(run))
    self.assertEqual(call.call_count,1)
 def test_cached_response_without_native_receipt_is_not_reissued(self):
  class Lease:pass
  with tempfile.TemporaryDirectory() as d:
   row={'sample_id':'fixture','cell':'S0C0','source_group':'group'};c={'output_root':d};binding={'fixture':1};run=Path(d)/str(__import__('uuid').uuid4());run.mkdir();r.write(run/'identity.json',{'run_uuid':run.name,'config_sha256':r.digest(c),'bindings':binding});r.write(run/'fixture/S0C0/first/response.json',{'cached':'simulation'})
   with patch.object(r,'plan',return_value={'missing':[]}),patch.object(r,'validate',return_value=([row],{'fixture':[row]},binding)),patch.object(r,'sam_for',return_value='simulation'),patch.object(r.budget,'reserve_block',return_value=Lease()),patch.object(r,'cell',side_effect=AssertionError('must not replay')):
    with self.assertRaisesRegex(ValueError,'automatic replay prohibited'):r.execute(c,str(run))
if __name__=='__main__':unittest.main()
