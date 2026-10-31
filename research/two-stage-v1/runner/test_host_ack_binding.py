import unittest,tempfile,json,copy
from pathlib import Path
import run_ablation as r
from bounded_verifier_binding import bind_host_ack
class HostAckTest(unittest.TestCase):
 def test_proven_machine_envelope_only_never_quality_fields(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);expected={'mode':'m','candidate_receipt_sha256':'a'*64,'source_sha256':'b'*64,'use':'attention_hint_only'};actual={**expected,'candidate_receipt_sha256':'model-copy-has-incomplete-digest'};raw={'connector_paint_ack':actual,'unresolved_ids':['real defect']};body={'messages':[{'role':'user','content':[{'type':'text','text':json.dumps({'format':'test-fixture','connector_paint_ack_required_exact':expected})}]}]};request=root/'request.json';response=root/'response.json';r.write(request,{'body':body});r.write(response,{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(raw)}}]});proof={'request_file':str(request),'request_sha256':r.sha(request),'body_sha256':r.digest(body),'response_file':str(response),'provider_response_sha256':r.sha(response),'expected_ack':expected}
   before=copy.deepcopy(raw);result,ops=bind_host_ack(raw,proof);self.assertEqual(raw,before);self.assertEqual(result['unresolved_ids'],raw['unresolved_ids']);self.assertEqual(result['connector_paint_ack'],expected);self.assertTrue(ops)
   with self.assertRaises(ValueError):bind_host_ack({**raw,'connector_paint_ack':expected},proof)
   proof['expected_ack']={**expected,'source_sha256':'9'*64}
   with self.assertRaises(ValueError):bind_host_ack(raw,proof)
 def test_missing_machine_ack_is_host_bound_only_from_exact_actual_packet(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);expected={'mode':'m','candidate_receipt_sha256':'a'*64,'source_sha256':'b'*64,'use':'attention_hint_only'};raw={'unresolved_ids':['real defect']};body={'messages':[{'role':'user','content':[{'type':'text','text':json.dumps({'format':'test-fixture','connector_paint_ack_required_exact':expected})}]}]};request=root/'request.json';response=root/'response.json';r.write(request,{'body':body});r.write(response,{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(raw)}}]});proof={'request_file':str(request),'request_sha256':r.sha(request),'body_sha256':r.digest(body),'response_file':str(response),'provider_response_sha256':r.sha(response),'expected_ack':expected}
   result,ops=bind_host_ack(raw,proof);self.assertEqual(result['connector_paint_ack'],expected);self.assertEqual(result['unresolved_ids'],['real defect']);self.assertNotIn('connector_paint_ack',raw);self.assertTrue(ops)

 def test_real_judgments_inside_ack_are_relocated_without_erasure(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);expected={'mode':'m','candidate':{'revision':'r','evidence_hashes':{'svg':'a'*64}},'field_status':'field_available','use':'attention_hint_only'}
   bindings=[{'id':'actual','target_ids':['shape'],'neighbor_ids':[],'evidence':'real post-render evidence'}]
   ack={'mode':'m','candidate':{**copy.deepcopy(expected['candidate']),'field_status':'field_available','use':'attention_hint_only'},'current_bindings':bindings,'uncertainty_reviews':[]};raw={'connector_paint_ack':ack,'unresolved_ids':['actual']};before=copy.deepcopy(raw)
   body={'messages':[{'role':'user','content':[{'type':'text','text':json.dumps({'format':'test-fixture','connector_paint_ack_required_exact':expected})}]}]};request=root/'request.json';response=root/'response.json';r.write(request,{'body':body});r.write(response,{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(raw)}}]});proof={'request_file':str(request),'request_sha256':r.sha(request),'body_sha256':r.digest(body),'response_file':str(response),'provider_response_sha256':r.sha(response),'expected_ack':expected}
   value,ops=bind_host_ack(raw,proof);self.assertEqual(value['current_bindings'],bindings);self.assertEqual(value['connector_paint_ack'],expected);self.assertEqual(raw,before);self.assertTrue(ops)
   conflict={**raw,'current_bindings':[]};r.write(response,{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(conflict)}}]});proof['provider_response_sha256']=r.sha(response)
   with self.assertRaises(ValueError):bind_host_ack(conflict,proof)
