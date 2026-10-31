import unittest,tempfile,copy
from pathlib import Path
import run_ablation as r
import two_stage_identity_migration as migration
class IdentityTest(unittest.TestCase):
 def test_only_archived_bridge_change_allowed_original_identity_unchanged(self):
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp);(root/'protocol-migrations').mkdir();oldfile=root/'old.py';newfile=root/'new.py';oldfile.write_text('old reviewed bridge');newfile.write_text('new proof-only empty SAM branch');old={'source':'same','bindings':{'bridge':r.sha(oldfile),'native_source':'frozen'}};new=copy.deepcopy(old);new['bindings']['bridge']=r.sha(newfile);marker=root/'identity.json';r.write(marker,old);before=r.sha(marker)
   r.write(root/'protocol-migrations/test-bridge-migration.json',{'from_sha256':r.sha(oldfile),'to_sha256':r.sha(newfile),'old_source_archive':str(oldfile),'new_source_archive':str(newfile)})
   self.assertTrue(migration.verify(marker,new,root));self.assertEqual(r.sha(marker),before)
   with self.assertRaises(ValueError):migration.verify(marker,{**new,'source':'different'},root)
