import json
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import assignment_policy as ap
sys.path.insert(0,str(Path(__file__).parent/'source/src'))
from figfox_plus.native.capabilities import validate_svg_capabilities, reject_disabled_program

EMPTY={'format':'sam-disabled-catalog-v1','status':'disabled_by_assignment','assets':[],'missing_assets':[],'complete_available_catalog':True}

def cell(root,sam=False,code=True):
    folder=root/'inputs';folder.mkdir()
    p={'version':'capabilities-v1','sam':sam,'code_methods':code}
    (folder/'capabilities.json').write_text(json.dumps({'policy':p,'sha256':ap.digest(p)}))
    (folder/'observer-assignment.json').write_text(json.dumps({'format':'observer-assignment-v1','mode':'enabled' if code else 'disabled_by_assignment','capability_sha256':ap.digest(p)}))
    (folder/'sam.json').write_text(json.dumps(EMPTY if sam is False else {'assets':[],'missing_assets':[],'complete_available_catalog':True}))
    return p

class FourCells(unittest.TestCase):
    def test_four_conditions(self):
        for sam in (False,True):
            for code in (False,True):
                with self.subTest(sam=sam,code=code),tempfile.TemporaryDirectory() as d:
                    root=Path(d);p=cell(root,sam,code);self.assertEqual(ap.load(root),p)
    def test_four_cell_common_hashes_and_no_off_asset_directory(self):
        import brief
        hashes=[]
        for sam in (False,True):
            for code in (False,True):
                with tempfile.TemporaryDirectory() as d:
                    root=Path(d);cell(root,sam,code)
                    hashes.append(brief.prepare_contracts(root)['common_hashes'])
                    prompt=brief.render_brief(root,'run1','main',off_stage=[root/'state.json'] if not code else None)
                    if not sam:self.assertNotIn(str(root/'inputs/sam')+',',prompt)
        self.assertTrue(all(item==hashes[0] for item in hashes))
    def test_off_verifier_candidate_hash_envelope(self):
        import brief
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cell(root,False,False);brief.prepare_contracts(root)
            r=root/'runs/run1';rd=r/'round-1';out=r/'jobs/verifier-1';out.mkdir(parents=True);rd.mkdir()
            (rd/'candidate').mkdir();(r/'checkpoint').mkdir()
            (rd/'native-result.json').write_text('{"rcd":[]}')
            snap={'revision':'a'*64,'evidence_hashes':{'current_svg':'a'*64,'bounds':'b'*64},'required_regions':['f1']}
            raw={**snap,'before_revision':'c'*64,'candidate_folder':'PRIVATE','native_result':{'numerical_diagnostic':991}}
            (rd/'candidate.json').write_text(json.dumps(raw))
            paths=brief.prepare_off_views(root,'run1','verifier',1,out)
            envelope=out/'candidate-evidence.json'
            self.assertIn(envelope,paths);self.assertNotIn(rd/'candidate.json',paths)
            self.assertEqual(json.loads(envelope.read_text()),snap)
            self.assertNotIn('991',envelope.read_text());self.assertNotIn('PRIVATE',envelope.read_text())
            prompt=brief.render_brief(root,'run1','verifier',1,off_stage=paths)
            self.assertIn(str(envelope),prompt);self.assertNotIn(str((rd/'candidate.json').resolve()),prompt)
            for change in ({'revision':3},{'evidence_hashes':{'current_svg':'b'*64}},{'required_regions':[991]},{'evidence_hashes':{'current_svg':'a'*64,'bounds':991}}):
                (rd/'candidate.json').write_text(json.dumps({**raw,**change}))
                with self.subTest(change=change),self.assertRaises(ValueError):brief.prepare_off_views(root,'run1','verifier',1,out)
    def test_sam_on_rejects_explicit_disabled_catalog(self):
        for code in (False,True):
            for marker in (EMPTY,{'assets':[],'status':'disabled_by_assignment'},{'assets':[],'format':'sam-disabled-catalog-v1'}):
                with self.subTest(code=code,marker=marker),tempfile.TemporaryDirectory() as d:
                    root=Path(d);cell(root,True,code)
                    (root/'inputs/sam.json').write_text(json.dumps(marker))
                    with self.assertRaisesRegex(ValueError,'SAM enabled'):ap.load(root)
    def test_off_planner_previous_verifier_feedback_is_finite(self):
        import brief
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cell(root,False,False);brief.prepare_contracts(root)
            r=root/'runs/run1';prev=r/'round-1';out=r/'jobs/planner-2';out.mkdir(parents=True);(prev/'verifier').mkdir(parents=True)
            feedback=prev/'verifier/raw.json';feedback.write_text('{"feedback":"same-run unresolved"}')
            (prev/'native-result.json').write_text('{"rcd":[]}')
            (r/'checkpoint').mkdir()
            paths=brief.prepare_off_views(root,'run1','planner',2,out)
            self.assertIn(feedback.resolve(),paths)
            self.assertNotIn(feedback.parent.resolve(),paths);self.assertNotIn(prev.resolve(),paths)
            self.assertNotIn(prev/'native-result.json',paths)
            prompt=brief.render_brief(root,'run1','planner',2,off_stage=paths)
            self.assertIn(str(feedback.resolve()),prompt)
            feedback.unlink();outside=root/'outside.json';outside.write_text('{}');feedback.symlink_to(outside)
            with self.assertRaisesRegex(ValueError,'verifier feedback'):brief.prepare_off_views(root,'run1','planner',2,out)
    def test_strict_booleans(self):
        for key in ('sam','code_methods'):
            for value in ('false',0,1,None):
                with self.subTest(key=key,value=value),tempfile.TemporaryDirectory() as d:
                    root=Path(d);p=cell(root);p[key]=value
                    (root/'inputs/capabilities.json').write_text(json.dumps({'policy':p,'sha256':ap.digest(p)}))
                    with self.assertRaises(ValueError):ap.load(root)
    def test_missing_catalog(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cell(root);(root/'inputs/sam.json').unlink()
            with self.assertRaisesRegex(ValueError,'SAM disabled'):ap.load(root)
    def test_contradictory_catalog(self):
        for change in ({'assets':[{'id':'leak'}]},{'missing_assets':[{}]},{'status':'ok'},{'complete_available_catalog':False},{'complete_available_catalog':1},{'extra':'evidence'}):
            with self.subTest(change=change),tempfile.TemporaryDirectory() as d:
                root=Path(d);cell(root)
                (root/'inputs/sam.json').write_text(json.dumps({**EMPTY,**change}))
                with self.assertRaisesRegex(ValueError,'SAM disabled'):ap.load(root)
    def test_sam_artifact_leakage(self):
        for relative in ('sam/asset.png','arrow-head-evidence.json','first-sam-boards/board.png','sam-ledger.jsonl'):
            with self.subTest(relative=relative),tempfile.TemporaryDirectory() as d:
                root=Path(d);cell(root);p=root/'inputs'/relative;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('leak')
                with self.assertRaisesRegex(ValueError,'SAM disabled'):ap.load(root)
    def test_run_sam_evidence_and_catalog_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);cell(root)
            leak=root/'runs/run1/round-1/sam-evidence.json';leak.parent.mkdir(parents=True);leak.write_text('{}')
            with self.assertRaisesRegex(ValueError,'SAM disabled'):ap.load(root)
            leak.unlink()
            catalog=root/'inputs/sam.json';catalog.rename(root/'neutral.json');catalog.symlink_to(root/'neutral.json')
            with self.assertRaisesRegex(ValueError,'SAM disabled'):ap.load(root)
    def test_native_actual_unbound_reference_rejection_and_common_raster(self):
        p={'version':'capabilities-v1','sam':False,'code_methods':True}
        for terminal in (False,True):
            with self.assertRaises(ValueError):validate_svg_capabilities(ET.fromstring('<svg><image href="sam/asset.png"/></svg>'),p,terminal=terminal)
            validate_svg_capabilities(ET.fromstring('<svg><image href="data:image/png;base64,AA=="/></svg>'),p,terminal=terminal)
        # Native has no SAM route: unsupported modules reject at program schema;
        # this function independently enforces the code-off route boundary.
        with self.assertRaises(ValueError):reject_disabled_program({'route':'module_program'},{**p,'code_methods':False})

if __name__=='__main__':unittest.main()
