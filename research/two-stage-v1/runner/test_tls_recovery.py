import unittest,tempfile
from pathlib import Path
import bounded_trace as trace
class TLSRecoveryTest(unittest.TestCase):
 def test_exact_failure_retains_unknown_reserve_and_never_replays_old_id(self):
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);exit=p/'exit.json';prior=p/'trace.json';trace.write(exit,{'request_id':'original','returncode':1,'stderr':'ssl.do_handshake ConnectionResetError: Connection reset by peer'});trace.write(prior,{'request_id':'original','status':'failed_or_charge_unknown'})
   proof={'transport_exit_file':str(exit),'transport_exit_sha256':trace.sha(exit),'original_trace_file':str(prior),'original_trace_sha256':trace.sha(prior),'original_request_id':'original','expected_original_response_file':str(p/'absent.json'),'old_fee_reserve_retained':True,'old_request_replay_allowed':False}
   self.assertEqual(trace.verify_tls_recovery(proof)['request_id'],'original')
   with self.assertRaises(ValueError):trace.verify_tls_recovery({**proof,'old_fee_reserve_retained':False})
   (p/'absent.json').write_text('{}')
   with self.assertRaises(ValueError):trace.verify_tls_recovery(proof)
