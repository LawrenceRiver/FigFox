import importlib.util,json,tempfile,unittest,sys

from pathlib import Path
sys.path.insert(0,str(Path(__file__).parent))
spec=importlib.util.spec_from_file_location('live_api',Path(__file__).with_name('live_api.py'));api=importlib.util.module_from_spec(spec);spec.loader.exec_module(api)
class Lease:
 def __init__(self):self.slots=[]
 def send(self,provider,slot,body,send):self.slots.append(slot);return send('durable-test-id')
class Tests(unittest.TestCase):
 def test_missing_json_pointer_is_a_recoverable_parameter_error(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'state.json';p.write_text('{"accepted":[]}');_,_,catalog=api.build_role_packet('Allowed neutral inputs: '+str(p))
   with self.assertRaisesRegex(api.AdmissionError,'invalid JSON pointer'):api.read_evidence(catalog,{'action':'read','file':str(p),'pointer':'/rejected_programs'})
 def test_native_final_contract_is_validated_before_role_submission(self):
  from unittest.mock import patch
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'flow.py').write_text('# native fixture');job=root/'runs/r/jobs/main';job.mkdir(parents=True);e=root/'e.json';e.write_text('{}');(job/'dispatch-prompt.md').write_text('Allowed neutral inputs: '+str(e));seen=[]
   def reply(provider,body,rid):
    seen.append(body);return {'choices':[{'finish_reason':'stop','message':{'role':'assistant','content':'{"revision":"bad"}' if len(seen)==1 else '{"revision":"correct"}'}}],'usage':{'prompt_tokens':1,'completion_tokens':1}}
   c={'providers':{'ds':{'protocol':'chat_completions','model':'test','max_output_tokens':64000,'context_tokens':1000000,'max_input_tokens':936000}},'role_provider':{'main':'ds'},'current_sample_id':'a','current_cell':'c','_mock_send':reply}
   checks=[SimpleNamespace(returncode=0,stdout='{"status":"invalid_report","error":"stale report evidence hashes"}',stderr=''),SimpleNamespace(returncode=0,stdout='{"status":"valid_report"}',stderr='')]
   with patch.object(api.subprocess,'run',side_effect=checks) as validate:output=api.run_role(root,'r','main',None,c,Lease())
   self.assertEqual(json.loads(output.read_text())['revision'],'correct');self.assertEqual(len(seen),2);self.assertEqual(validate.call_count,2)
 def test_balance_http_error_is_typed_and_preserved(self):
  from unittest.mock import patch
  from types import SimpleNamespace
  payload={'transport_error':'HTTP','status':402,'detail':'insufficient balance'}
  with patch.object(api.subprocess,'run',return_value=SimpleNamespace(returncode=1,stdout=json.dumps(payload))):
   with self.assertRaises(api.ProviderHTTPError) as failed:api.transport({}, {}, '00000000-0000-0000-0000-000000000001')
  self.assertEqual(failed.exception.status_code,402)
 def test_truncated_role_retries_final_json_without_reexecuting_tools(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);job=root/'runs/r/jobs/main';job.mkdir(parents=True);e=root/'e.json';e.write_text('{}');(job/'dispatch-prompt.md').write_text('Allowed neutral inputs: '+str(e));seen=[]
   def reply(provider,body,rid):
    seen.append(body);return {'choices':[{'finish_reason':'length' if len(seen)==1 else 'stop','message':{'role':'assistant','content':'incomplete' if len(seen)==1 else '{}'}}],'usage':{'prompt_tokens':1,'completion_tokens':1}}
   c={'providers':{'ds':{'protocol':'chat_completions','model':'test','json_output':True,'max_output_tokens':64000,'context_tokens':1000000,'max_input_tokens':936000}},'role_provider':{'main':'ds'},'current_sample_id':'a','current_cell':'c','_mock_send':reply}
   output=api.run_role(root,'r','main',None,c,Lease());self.assertEqual(output.read_text(),'{}');self.assertEqual(len(seen),2);self.assertNotIn('tools',seen[1]);self.assertEqual(seen[1]['response_format'],{'type':'json_object'})
 def test_exhausted_draft_tool_returns_feedback_without_extra_validation(self):
  from unittest.mock import patch
  from types import SimpleNamespace
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);job=root/'runs/r/jobs/main';job.mkdir(parents=True);e=root/'e.json';e.write_text('{}');(job/'dispatch-prompt.md').write_text('Allowed neutral inputs: '+str(e));seen=[]
   def reply(provider,body,rid):
    seen.append(body);n=len(seen)
    msg={'role':'assistant','content':None,'tool_calls':[{'id':str(n),'function':{'name':'draft_check','arguments':'{"draft_json":"{}"}'}}]} if n<=3 else {'role':'assistant','content':'{}'}
    return {'choices':[{'finish_reason':'tool_calls' if n<=3 else 'stop','message':msg}],'usage':{'prompt_tokens':1,'completion_tokens':1}}
   c={'providers':{'ds':{'protocol':'chat_completions','model':'test','max_output_tokens':64000,'context_tokens':1000000,'max_input_tokens':936000}},'role_provider':{'main':'ds'},'current_sample_id':'a','current_cell':'c','_mock_send':reply}
   with patch.object(api.subprocess,'run',return_value=SimpleNamespace(returncode=0,stdout='valid',stderr='')) as validate:
    output=api.run_role(root,'r','main',None,c,Lease());self.assertEqual(json.loads(output.read_text()),{});self.assertEqual(validate.call_count,2)
   self.assertNotIn('draft_check',[t['function']['name'] for t in seen[2].get('tools',[])])
 def test_non_tool_json_turn_omits_provider_ignored_reasoning_only(self):
  pc={'protocol':'chat_completions','model':'ds','json_output':True};messages=[{'role':'assistant','content':'{}','reasoning_content':'opaque history'}]
  self.assertNotIn('reasoning_content',api.body_for(pc,messages)['messages'][0])
  self.assertEqual(api.body_for(pc,messages,[{'type':'function','function':{'name':'x'}}])['messages'][0]['reasoning_content'],'opaque history')
 def test_all_tool_results_precede_attached_image_messages(self):
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);job=root/'runs/r/jobs/main';job.mkdir(parents=True);e=root/'e.json';e.write_text('{}');(job/'dispatch-prompt.md').write_text('Allowed neutral inputs: '+str(e));seen=[]
   def reply(provider,body,rid):
    seen.append(body)
    msg={'role':'assistant','content':None,'reasoning_content':'','tool_calls':[{'id':str(i),'function':{'name':'read_evidence','arguments':'{"action":"read","file":"x"}'}} for i in range(2)]} if len(seen)==1 else {'role':'assistant','content':'{}'}
    return {'choices':[{'finish_reason':'tool_calls' if len(seen)==1 else 'stop','message':msg}],'usage':{'prompt_tokens':1,'completion_tokens':1}}
   c={'providers':{'ds':{'protocol':'chat_completions','model':'test','max_output_tokens':64000,'context_tokens':1000000,'max_input_tokens':936000}},'role_provider':{'main':'ds'},'current_sample_id':'a','current_cell':'c','_mock_send':reply}
   import io,base64
   from PIL import Image
   data=io.BytesIO();Image.new('RGB',(1,1),'white').save(data,format='PNG');c['providers']['ds']['image_token_bound']={'tile_size':32,'tokens_per_tile':2,'base_tokens':1}
   image={'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(data.getvalue()).decode()}}
   with patch.object(api,'read_evidence',return_value=({'image':'attached'},image)):api.run_role(root,'r','main',None,c,Lease())
   self.assertEqual([m['role'] for m in seen[1]['messages']],['user','assistant','tool','tool','user'])
 def test_recovery_slot_namespace_is_explicit(self):
  self.assertEqual(api.slot({'current_sample_id':'a','current_cell':'c','financial_slot_prefix':'repair1'},'score/JUDGE0/TURN0'),'a/c/repair1/score/JUDGE0/TURN0')
 def test_role_corrects_denied_tool_or_malformed_final_within_reserved_turns(self):
  for first in ({'role':'assistant','content':None,'tool_calls':[{'id':'c','function':{'name':'read_evidence','arguments':'{"action":"read","file":"/outside"}'}}]}, {'role':'assistant','content':'not a JSON object'}):
   with self.subTest(first=first),tempfile.TemporaryDirectory() as tmp:
    root=Path(tmp);job=root/'runs/r/jobs/main';job.mkdir(parents=True);e=root/'e.json';e.write_text('{}');(job/'dispatch-prompt.md').write_text('Allowed neutral inputs: '+str(e))
    seen=[]
    def reply(provider,body,rid):
     seen.append(body);msg=first if len(seen)==1 else {'role':'assistant','content':'{"issues":[]}'}
     return {'choices':[{'finish_reason':'tool_calls' if msg.get('tool_calls') else 'stop','message':msg}],'usage':{'prompt_tokens':1,'completion_tokens':1}}
    c={'providers':{'ds':{'protocol':'chat_completions','model':'test','max_output_tokens':64000,'context_tokens':1000000,'max_input_tokens':936000}},'role_provider':{'main':'ds'},'current_sample_id':'a','current_cell':'c','_mock_send':reply}
    output=api.run_role(root,'r','main',None,c,Lease());self.assertEqual(json.loads(output.read_text()),{'issues':[]});self.assertEqual(len(seen),2)
 def test_transport_pause_records_no_http_before_credentials(self):
  import io
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as tmp:
   pause=Path(tmp)/'pause.json';pause.write_text('{}')
   rid='00000000-0000-0000-0000-000000000001'
   with patch.object(api,'PAUSE_FILE',pause),patch.object(sys,'stdin',io.StringIO(json.dumps({'provider':{},'body':{},'request_id':rid}))),patch('urllib.request.urlopen',side_effect=AssertionError('HTTP forbidden')):
    with self.assertRaises(SystemExit) as stopped:api.transport_child()
   self.assertEqual(stopped.exception.code,75)
   self.assertFalse(json.loads((pause.parent/'paused-before-http'/(rid+'.json')).read_text())['http_started'])
 def test_json_output_contract_only_on_final_calls_without_tools(self):
  tool={'type':'function','function':{'name':'inspect','parameters':{'type':'object'}}}
  pc={'protocol':'chat_completions','model':'deepseek-flash','json_output':True}
  body=api.body_for(pc,[{'role':'user','content':'Return JSON object'}],[tool])
  self.assertNotIn('response_format',body);self.assertEqual(body['tools'],[tool])
  self.assertEqual(api.body_for(pc,[{'role':'user','content':'Return JSON object'}])['response_format'],{'type':'json_object'})
 def test_required_files_can_be_reread_without_expanding_evidence_roots(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp)/'required.json';p.write_text('{"id":"native"}')
   _,_,catalog=api.build_role_packet('Allowed neutral inputs: '+str(p))
   result,_=api.read_evidence(catalog,{'action':'read','file':str(p),'pointer':'/id'})
   self.assertEqual(result['value'],'native')
 def test_full_context_rejected(self):
  with self.assertRaises(api.AdmissionError):api.admit({'context_window':64001,'max_output_tokens':64000},{'input':'long enough'})
 def test_min_output_budget(self):
  self.assertEqual(api.body_for({'protocol':'responses','model':'x','max_output_tokens':32768},[])['max_output_tokens'],32768)
 def test_reasoning_preserved(self):
  raw={'status':'completed','output':[{'type':'reasoning','id':'r','encrypted_content':'opaque'},{'type':'function_call','call_id':'c','name':'draft_check','arguments':'{}'}]}
  _,calls,msg=api.extract(raw,'responses');body=api.body_for({'protocol':'responses','model':'x'},[msg,{'role':'tool','tool_call_id':'c','content':'ok'}]);self.assertEqual(body['input'][0],raw['output'][0]);self.assertEqual(body['input'][-1]['call_id'],'c')
 def test_exact_final_bytes(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);job=root/'runs/r/jobs/main';job.mkdir(parents=True);e=root/'e.json';e.write_text('{"evidence":true}');(job/'dispatch-prompt.md').write_text('Allowed neutral inputs: '+str(e)+'\nAllowed current stage inputs: '+str(e))
   final=' { "issues" : [] }\n';cfg={'providers':{'openai':{'protocol':'responses','model':'test','context_tokens':1000000,'max_input_tokens':936000,'max_output_tokens':64000}},'role_provider':{'main':'openai'},'current_sample_id':'S','current_cell':'C','_mock_send':lambda *args:{'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':final}]}],'usage':{'input_tokens':1,'output_tokens':1}}}
   lease=Lease();path=api.run_role(root,'r','main',None,cfg,lease);self.assertEqual(path.read_bytes(),final.encode());self.assertEqual(lease.slots,['S/C/main/TURN0'])
 def test_inventory_symlinks_rejected(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);(p/'x').write_text('x');(p/'link').symlink_to(p/'x')
   with self.assertRaises(api.AdmissionError):api.inventory([p])
 def test_truncation_rejected(self):
  with self.assertRaises(api.AdmissionError):api.extract({'choices':[{'finish_reason':'length','message':{'content':'{}'}}]},'chat_completions')

 def test_real_native_callback_and_generic_admission(self):
  base=Path('/Users/lawrenceriver/Desktop/figfox-debug/experiments/final-architecture-20261023/convergence-v2')
  adapter=base/'insertion-parity-adapter-20261029';fixture=base/'generic-cell-input-bridge-20261029/native-smoke-fixture'
  python='/Users/lawrenceriver/Desktop/7月/plus/.venv/bin/python'
  with tempfile.TemporaryDirectory() as tmp:
   tmp=Path(tmp);original=tmp/'original.png'
   from PIL import Image
   Image.new('RGB',(120,80),'white').save(original)
   policy={'version':'capabilities-v1','sam':False,'code_methods':False}
   svg='<svg xmlns="http://www.w3.org/2000/svg" width="120" height="80" viewBox="0 0 120 80"><g id="frame" data-plus-kind="frame"><rect id="object7" x="20" y="20" width="60" height="40" fill="#3388aa"/></g></svg>'
   cfg={'native_python':python,'current_sample_id':'synthetic','current_cell':'S0C0','providers':{'openai':{'protocol':'responses','model':'mock','context_tokens':1000000,'max_input_tokens':967232,'max_output_tokens':32768,'image_token_bound':{'tile_size':512,'tokens_per_tile':1024,'base_tokens':1024}}},'_mock_send':lambda *args:{'status':'completed','output':[{'type':'message','content':[{'type':'output_text','text':svg}]}]}}
   first=api.run_first({'adapter':str(adapter),'native_source_root':str(adapter/'source'),'output_root':str(tmp/'first'),'original_png':str(original),'runtime_json':str(fixture/'runtime.json'),'capabilities':policy},cfg,Lease())
   generic=base/'generic-cell-input-bridge-20261029';sys.path.insert(0,str(generic));import prepare_cell
   registry=tmp/'registry.json';registry.write_text('{}')
   spec={'adapter':str(adapter),'native_source_root':str(adapter/'source'),'output_root':str(tmp/'cell'),'original_png':first['original'],'initial_svg':first['stage0_scene'],'runtime_json':first['runtime'],'runtime_binding':first['runtime_binding'],'first_stage_provenance':first['provenance'],'registry':str(registry),'python':python,'capabilities':{'policy':policy,'sha256':prepare_cell.digest(policy)}}
   prepared=prepare_cell.admit(spec)
   self.assertTrue(prepared)


 def test_lossless_inline_png_projection(self):
  import io,base64
  from PIL import Image
  image=io.BytesIO();Image.new('RGB',(2,3),'red').save(image,format='PNG');data=image.getvalue()
  svg=('<svg xmlns="http://www.w3.org/2000/svg"><image id="a" href="data:image/png;base64,'+base64.b64encode(data).decode()+'"/></svg>').encode()
  text,images,proof=api.readonly_inline_png_projection(svg,'original.svg');self.assertTrue(proof['inverse_verified']);self.assertEqual(images[0]['bytes'],len(data));self.assertNotIn(base64.b64encode(data).decode(),text)
  with self.assertRaises(api.AdmissionError):api.readonly_inline_png_projection(svg.replace(b'<image id="a"',b'<image href="elsewhere.png"/><image id="a"'),'bad.svg')
 def test_extra_body_and_body_limit(self):
  pc={'protocol':'chat_completions','model':'x','max_output_tokens':64000,'extra_body':{'thinking':{'type':'enabled'},'reasoning_effort':'high'}}
  self.assertEqual(api.body_for(pc,[])['thinking'],{'type':'enabled'})
  pc['extra_body']={'model':'bad'}
  with self.assertRaises(api.AdmissionError):api.body_for(pc,[])
  with self.assertRaises(api.AdmissionError):api.admit({'max_request_bytes':1},{'input':'abc'})


 def test_closed_optional_catalog(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);checkpoint=p/'checkpoint';(checkpoint/'pack').mkdir(parents=True)
   (checkpoint/'current.svg').write_text('<svg/>');(checkpoint/'public.svg').write_text('<svg/>')
   from PIL import Image
   for name in ('original.png','current.png','pack/frame-pair.png','pack/frame-current.png') :Image.new('RGB',(2,2),'white').save(checkpoint/name)
   (checkpoint/'pack/pack.json').write_text(json.dumps({'frames':[{'frame_id':'F','pair':str(checkpoint/'pack/frame-pair.png')}]}));(checkpoint/'bounds.json').write_text('{"secret_measure":23}')
   messages,manifest,catalog=api.build_role_packet('Allowed current stage inputs: '+str(checkpoint))
   self.assertEqual([x['frame_id'] for x in manifest['required_frames']],['F']);self.assertIn(str(checkpoint/'bounds.json'),catalog)
   self.assertNotIn('secret_measure',json.dumps(messages))
   answer,_=api.read_evidence(catalog,{'action':'read','file':str(checkpoint/'bounds.json'),'pointer':'/secret_measure'});self.assertEqual(answer['value'],23)
   with self.assertRaises(api.AdmissionError):api.read_evidence(catalog,{'action':'read','file':'/etc/passwd'})
   (checkpoint/'bounds.json').write_text('{}')
   with self.assertRaises(api.AdmissionError):api.read_evidence(catalog,{'action':'read','file':str(checkpoint/'bounds.json')})

if __name__=='__main__':unittest.main()
