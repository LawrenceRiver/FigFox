import unittest,tempfile,json,copy
from pathlib import Path
import model_envelope_binding as m,run_ablation as r
class EnvelopeTest(unittest.TestCase):
 def test_only_same_saved_request_machine_constants_are_bound(self):
  with tempfile.TemporaryDirectory() as tmp:
   control=Path(tmp);folder=control/'sample-x/S0C1';(folder/'api').mkdir(parents=True);(control/'trace').mkdir()
   snapshot={'revision':'actual','evidence_hashes':{'bounds':'true-hash'}}
   payload={'revision':'actual','evidence_hashes':{'bounds':'one-letter-copy-error'},'unresolved_ids':['real-failed'],'protected_regressions':['keep regression']}
   before=copy.deepcopy(payload);body={'messages':[{'role':'system','content':'associations verbatim; never shift values between keys: '+json.dumps(snapshot)}]}
   request=folder/'api/x-request.json';r.write(request,{'body':body});response=control/'response.json';r.write(response,{'choices':[{'finish_reason':'stop','message':{'content':json.dumps(payload)}}]})
   trace=control/'trace/第001张图-sample-x-B23.json';r.write(trace,{'response_file':str(response),'response_sha256':r.sha(response),'body_sha256':r.digest(body)})
   value,proof=m.bind(folder,'B23',payload);self.assertEqual(payload,before);self.assertEqual(value['unresolved_ids'],before['unresolved_ids']);self.assertEqual(value['protected_regressions'],before['protected_regressions']);self.assertEqual(value['evidence_hashes'],snapshot['evidence_hashes']);self.assertTrue(proof['operations'])
   with self.assertRaises(ValueError):m.bind(folder,'B23',{**payload,'unresolved_ids':[]})
   r.write(request,{'body':{**body,'changed':True}})
   with self.assertRaises(ValueError):m.bind(folder,'B23',payload)

 def test_only_known_host_localization_suffix_can_follow_exact_snapshot(self):
  marker='associations verbatim; never shift values between keys: ';value={'revision':'r','evidence_hashes':{'svg':'h'}};prefix=marker+json.dumps(value)
  self.assertEqual(m.snapshot_from_system(prefix+' '+m.LOCALIZATION_TAIL,marker),value)
  for bad in [prefix+' '+json.dumps({'revision':'other'}),prefix+' arbitrary suffix',prefix+' '+marker+json.dumps(value)]:
   with self.assertRaises(ValueError):m.snapshot_from_system(bad,marker)
