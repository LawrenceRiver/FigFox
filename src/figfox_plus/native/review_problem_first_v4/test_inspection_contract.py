"""Synthetic contract tests; no visual fixtures or historical answers."""
from copy import deepcopy
import importlib
import unittest

MODULE = 'figfox_plus.native.review_overnight_v1.inspection_contract'


def schedule():
    return [dict(image_id='image', **{'pass': p}, category=c, region_id=r,
                 original_asset_id='original/'+r, current_asset_id='current/'+r,
                 evidence_assets=['original/'+r, 'current/'+r], current_revision='revision')
            for p in (1, 2, 3) for c in ('E', 'F', 'B', 'A', 'S1')
            for r in (['full'] if p == 1 else ['pair-a', 'pair-b'])]


def plan(contract, spec):
    records = []
    for region in contract.inspection_regions(spec):
        checks = {}
        for category in contract.CATEGORIES:
            checks[category] = dict(state='uncertain', original_observation='Source evidence is unreadable at the supplied resolution.',
                                    current_observation='Target evidence is unreadable at the supplied resolution.', issue_ids=[])
            if category in ('E', 'F'):
                checks[category]['candidate_check'] = 'Candidate relationships cannot be resolved from the supplied evidence.'
        row = dict(region=region['region'], checks=checks)
        if region['pass'] == 1:
            row['svg_observation'] = 'SVG identity is available but does not resolve the unreadable visual evidence.'
        records.append(row)
    return dict(inspection_records=records)


class InspectionContractTests(unittest.TestCase):
    def setUp(self):
        try:
            self.contract = importlib.import_module(MODULE)
        except ModuleNotFoundError:
            self.fail('inspection_contract implementation is absent')
        self.spec = schedule()
        self.plan = plan(self.contract, self.spec)

    def test_round_trip_preserves_observations_and_schedule_invariants(self):
        rows = self.contract.expand_observations(self.plan, self.spec)
        self.assertEqual(len(rows), 25)
        for row, unit in zip(rows, self.spec):
            for key in ('image_id', 'pass', 'category', 'region_id', 'current_revision', 'evidence_assets'):
                self.assertEqual(row[key], unit[key])
            self.assertEqual(row['state'], 'uncertain')
        rows[0]['issue_ids'].append('changed')
        self.assertEqual(self.plan['inspection_records'][0]['checks']['E']['issue_ids'], [])

    def test_uncertainty_is_complete_record_not_visual_acceptance(self):
        result = self.contract.audit_inspection(self.spec, self.plan, [])
        self.assertTrue(result['records_complete'])
        self.assertFalse(result['inspection_complete'])
        self.assertEqual(result['visual_acceptance'], 'not_assessed')

    def test_missing_record_never_becomes_clear(self):
        self.plan['inspection_records'].pop()
        result = self.contract.audit_inspection(self.spec, self.plan, [])
        self.assertFalse(result['records_complete'])

    def test_identity_is_explicit_and_record_order_is_not_positional(self):
        before = self.contract.expand_observations(self.plan, self.spec)
        self.plan['inspection_records'].reverse()
        self.assertEqual(before, self.contract.expand_observations(self.plan, self.spec))
        self.plan['inspection_records'][0]['region'] = True
        with self.assertRaises(ValueError): self.contract.expand_observations(self.plan, self.spec)

    def test_rejects_missing_category_generic_evidence_and_missing_svg(self):
        for field in ('category', 'original_observation', 'candidate_check', 'svg_observation'):
            p = deepcopy(self.plan); row = p['inspection_records'][0]
            if field == 'category': del row['checks']['S1']
            elif field == 'svg_observation': del row[field]
            else: row['checks']['E'][field] = 'same as previous round'
            with self.subTest(field=field), self.assertRaises(ValueError):
                self.contract.expand_observations(p, self.spec)

    def test_rejects_duplicate_unknown_record_or_invariant_override(self):
        for change in ('duplicate', 'unknown', 'override'):
            p = deepcopy(self.plan)
            if change == 'duplicate': p['inspection_records'].append(deepcopy(p['inspection_records'][0]))
            if change == 'unknown': p['inspection_records'][0]['region'] = 99
            if change == 'override': p['inspection_records'][0]['checks']['E']['evidence_assets'] = ['other']
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.contract.expand_observations(p, self.spec)

    def test_rejects_incomplete_or_modified_host_schedule(self):
        for change in ('missing_category', 'missing_pass', 'changed_pair', 'duplicate'):
            s = deepcopy(self.spec)
            if change == 'missing_category': s = [u for u in s if u['category'] != 'S1']
            if change == 'missing_pass': s = [u for u in s if u['pass'] != 3]
            if change == 'changed_pair':
                for u in s:
                    if u['pass'] == 3:
                        u['original_asset_id'] = 'changed'; u['evidence_assets'][0] = 'changed'
            if change == 'duplicate': s.append(deepcopy(s[0]))
            with self.subTest(change=change), self.assertRaises(ValueError): self.contract.inspection_regions(s)

    def test_issue_links_are_checked_without_repair_programs(self):
        check = self.plan['inspection_records'][0]['checks']['E']
        check.update(state='issue', issue_ids=['finding'])
        self.assertFalse(self.contract.audit_inspection(self.spec, self.plan, [])['records_complete'])
        issues = [dict(id='finding', image_id='image', category='E')]
        self.assertTrue(self.contract.audit_inspection(self.spec, self.plan, issues)['records_complete'])

    def test_no_observation_defaults_and_no_mixed_encodings(self):
        for change in ('missing_observation', 'missing_reason', 'mixed'):
            p = deepcopy(self.plan)
            check = p['inspection_records'][0]['checks']['B']
            if change == 'missing_observation': del check['current_observation']
            if change == 'missing_reason': check['state'] = 'not_applicable'
            if change == 'mixed': p['observations'] = []
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.contract.expand_observations(p, self.spec)

    def test_schema_and_prompt_expose_all_categories(self):
        props = self.contract.INSPECTION_SCHEMA['properties']['inspection_records']['items']['properties']['checks']
        self.assertEqual(props['required'], list(self.contract.CATEGORIES))
        self.assertIn('generated_python', self.contract.INSPECTION_PROMPT)
        self.assertIn('照片被误画', self.contract.INSPECTION_PROMPT)


if __name__ == '__main__': unittest.main()
