import unittest,tempfile,json,hashlib
from pathlib import Path
import native_receipt_recovery as recovery
class RecoveryTests(unittest.TestCase):
 def test_append_preserves_old_raw_and_selects_actual_new_source(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);role=root/'runs/run1/round-1/verifier';role.mkdir(parents=True)
   def put(p,d):p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(d))
   put(root/'runs/run1/state.json',{'last_round':0});put(root/'runs/run1/round-1/candidate.json',{'revision':'candidate'})
   (root/'flow.py').write_text('# frozen native')
   old={'issues':[]};put(role/'raw.json',old);put(role/'receipt.json',{'sha256':recovery.sha(role/'raw.json')});put(role/'dispatch.json',{'agent_id':'original'})
   before=(role/'raw.json').read_bytes();source=root/'actual-model.json';report={k:[] for k in recovery.FIELDS};report['unresolved_ids']=['still-failed'];put(source,report)
   receipt=recovery.append_correction(root,'run1',1,source)
   self.assertEqual((role/'raw.json').read_bytes(),before)
   selected=recovery.verifier_path(root,'run1',1)
   self.assertEqual(selected,receipt);self.assertEqual(json.loads((selected/'raw.json').read_text()),report)
   self.assertEqual(json.loads((selected/'receipt.json').read_text())['sha256'],recovery.sha(source))
   with self.assertRaises(ValueError):recovery.append_correction(root,'run1',1,source)
   (role/'raw.json').write_text('{}')
   with self.assertRaises(ValueError):recovery.verifier_path(root,'run1',1)
