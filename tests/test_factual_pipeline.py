import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from PIL import Image

from figfox_plus.factual.pipeline import run
from figfox_plus.factual.transport import request


SVG='<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20"><rect id="r" width="10" height="10" fill="red"/></svg>'

class FactualPipelineTests(unittest.TestCase):
    def test_fresh_run_and_checkpoint_resume_make_no_duplicate_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);source=p/'source.png';Image.new('RGB',(20,20),'white').save(source)
            calls=[]
            def first(image,folder,sam,send):
                calls.append('G0');return SVG
            def send(stage,prompt,payload,images,folder):
                calls.append(stage)
                if stage=='G1':return {'regions':[{'id':x,'status':'no_confirmed_difference','evidence':'paired views checked'} for x in 'ABCD'],'issues':[], 'fact_inventory':[{'id':'f1','region':'A','kind':'geometry','source_reading':'rectangle','initial_reading':'rectangle','source_box':[0,0,10,10],'initial_box':[0,0,10,10],'certainty':'clear','source_basis':'paired crop'}]}
                return {'fact_checks':[{'fact_id':'f1','decision':'confirmed','source_evidence':'paired crop','source_reading':'rectangle','initial_reading':'rectangle'}],'additional_issues':[],'transactions':[],'unresolved':[]}
            result=run(source,p/'run',sam=False,send=send,g0_builder=first)
            self.assertEqual(result['status'],'execution_complete')
            self.assertIsNone(result['visual_quality_pass'])
            run(source,p/'run',sam=False,send=send,g0_builder=first)
            self.assertEqual(calls,['G0','G1','G2'])
            Image.new('RGB',(20,20),'black').save(source)
            with self.assertRaisesRegex(ValueError,'source'):run(source,p/'run',sam=False,send=send,g0_builder=first)

    def test_checkpoint_rejects_source_or_capability_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);source=p/'source.png';Image.new('RGB',(20,20)).save(source)
            cp=p/'cp';cp.mkdir();(cp/'initial.svg').write_text(SVG)
            (cp/'manifest.json').write_text(json.dumps({'source_sha256':'wrong','initial_sha256':hashlib.sha256(SVG.encode()).hexdigest(),'sam':False,'provenance':{'request_id':'historical'}}))
            with self.assertRaisesRegex(ValueError,'source'):run(source,p/'run',sam=False,checkpoint=cp)

    def test_uncertain_request_is_not_resent_and_reserve_retained(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp);settings={'model':'fixture','endpoint':'https://example.invalid','key_env':'MISSING','input_usd_per_million':5,'output_usd_per_million':30,'max_input_tokens':1000,'max_output_tokens':100,'budget_usd':1}
            calls=[]
            def fail(*args):calls.append(1);raise TimeoutError('uncertain')
            with self.assertRaises(TimeoutError):request(folder,'prompt',[],settings,http=fail)
            with self.assertRaisesRegex(ValueError,'uncertain'):request(folder,'prompt',[],settings,http=fail)
            self.assertEqual(len(calls),1)
            self.assertGreater(json.loads((folder/'receipt.json').read_text())['reserved_usd'],0)

    def test_interrupted_checkpoint_draft_cannot_be_replaced(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp);source=p/'source.png';Image.new('RGB',(20,20)).save(source)
            out=p/'run';g0=out/'G0';g0.mkdir(parents=True)
            (g0/'initial.svg').write_text(SVG.replace('red','blue'))
            (g0/'manifest.json').write_text(json.dumps({'source_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),'sam':False,'initial_sha256':hashlib.sha256(SVG.encode()).hexdigest()}))
            with self.assertRaisesRegex(ValueError,'G0 hash'):run(source,out,sam=False,repair=False)

if __name__=='__main__':unittest.main()
