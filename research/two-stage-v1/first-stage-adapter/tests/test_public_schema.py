"""Literal public wire tests using synthetic data only; no executor/provider."""
import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
C = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(C), str(C / 'source/src')]
import brief
from detection_contract import validate_detection_report, validate_issues

class PublicSchemaTests(unittest.TestCase):
    def test_semantic_both_assignments_receive_complete_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            for enabled in (False, True):
                root = Path(tmp) / str(enabled)
                (root / 'inputs').mkdir(parents=True)
                policy = {'version':'capabilities-v1','sam':True,'code_methods':enabled}
                sha = hashlib.sha256(json.dumps(policy,sort_keys=True,separators=(',',':')).encode()).hexdigest()
                (root/'inputs/capabilities.json').write_text(json.dumps({'policy':policy,'sha256':sha}))
                (root/'inputs/observer-assignment.json').write_text(json.dumps({'format':'observer-assignment-v1','mode':'enabled' if enabled else 'disabled_by_assignment','capability_sha256':sha}))
                brief.prepare_contracts(root)
                prompt = brief.render_brief(root,'synthetic','semantic',off_stage=[])
                for literal in ('Shared public JSON wire schema', '"image_id": "case"', '"neighbor_ids": []', '"original_evidence"', '"current_evidence"', '"target_ids"', '"container_id"', '"examined_regions"', '"unresolved_regions"', '"programs": []', 'F, E, B, S1, D, S2, A, C, S4', 'new_required_findings', 'new_uncertain_findings'):
                    self.assertIn(literal,prompt)

    def test_actual_validators_minimal_complete_and_missing_keys(self):
        with tempfile.TemporaryDirectory() as tmp:
            svg = Path(tmp)/'synthetic.svg'
            svg.write_text('<svg><g id="anchor"/></svg>')
            issue = {'id':'synthetic','image_id':'case','category':'A','decision':'confirmed','description':'Visible correspondence differs.','original_evidence':'Reference shows an object.','current_evidence':'Current lacks that object.','target_ids':[],'neighbor_ids':[],'container_id':'anchor'}
            state = {'revision':'synthetic','evidence_hashes':{},'required_regions':['frame']}
            report = {'revision':'synthetic','evidence_hashes':{},'examined_regions':['frame'],'unresolved_regions':[],'issues':[issue],'programs':[]}
            self.assertEqual(validate_detection_report(json.dumps(report),'semantic',state,svg)[1],[])
            for key in ('id','image_id','category','decision','description','original_evidence','current_evidence','target_ids','neighbor_ids','container_id'):
                bad = copy.deepcopy(issue); del bad[key]
                with self.subTest(issue_key=key), self.assertRaises(ValueError): validate_issues([bad],svg)
            for key in report:
                bad = copy.deepcopy(report); del bad[key]
                with self.subTest(report_key=key), self.assertRaises(ValueError): validate_detection_report(json.dumps(bad),'semantic',state,svg)
            present = dict(issue,target_ids=['anchor']); del present['container_id']
            validate_issues([present],svg)

if __name__ == '__main__': unittest.main()
