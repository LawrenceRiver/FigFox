import unittest,copy
from pathlib import Path
import empty_sam_execution as sam
class EmptySamProofTest(unittest.TestCase):
 def test_real_retained_receipt_passes_but_source_or_receipt_changes_fail(self):
  root=Path(__file__).resolve().parents[1]/'output/two-stage-20261030/sample-0021/sam';original=Path('/Users/lawrenceriver/Downloads/FigFoxBench-v3/sources/021.png')
  proof=sam.build(root/'sam-catalog.json',root/'sam-validation-log.json',original);self.assertTrue(sam.verify(proof,original))
  for altered in [None,{**proof,'original_png_sha256':'0'*64}]:
   with self.assertRaises(ValueError):sam.verify(altered,original)
  bad=copy.deepcopy(proof);bad['files']['raw_response']['sha256']='0'*64
  with self.assertRaises(ValueError):sam.verify(bad,original)
