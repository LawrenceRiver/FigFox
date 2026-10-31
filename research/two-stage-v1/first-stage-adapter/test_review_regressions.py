"""Regression tests with synthetic inputs and stub renderer; no native execution."""
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET
import flow
import connector_paint_bridge as bridge
from test_assignment_policy import setup_cell


class ReviewRegressions(unittest.TestCase):
    def test_render_snapshot_finishes_evidence_with_cell_root(self):
        with tempfile.TemporaryDirectory() as d:
            cell=Path(d);(cell/'inputs').mkdir();(cell/'inputs/sam.json').write_text('{}')
            svg=cell/'source.svg';svg.write_text('<svg/>');original=cell/'original.png';original.write_bytes(b'synthetic image')
            output=cell/'out'
            def stage(parsed,original_path,folder):
                self.assertIsInstance(parsed,ET.Element)
                folder.mkdir(parents=True);(folder/'preview.png').write_bytes(b'synthetic image');(folder/'bounds.json').write_text('{}');(folder/'scene.svg').write_text('<svg/>')
                (folder/'pack').mkdir();(folder/'pack/pack.json').write_text('{"frames":[]}')
            document=SimpleNamespace(parse=ET.fromstring,public_svg=lambda parsed:ET.tostring(parsed,encoding='unicode'))
            with patch.object(flow,'native',return_value=(SimpleNamespace(stage=stage),document,None,None,None)) as native:
                result=flow.render_snapshot(svg,original,output,root=cell)
            native.assert_called_once_with(cell)
            self.assertEqual(result['revision'],flow.sha(svg))
            self.assertEqual(result['evidence_hashes']['sam_catalog'],flow.sha(cell/'inputs/sam.json'))

    def test_enabled_assignment_requires_observation_preparation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);setup_cell(root,on=True)
            with self.assertRaisesRegex(ValueError,'observation preparation'):
                flow.Flow(root).observation_proposals()

    def test_enabled_assignment_requires_connector_preparation(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);setup_cell(root,on=True)
            host=SimpleNamespace(root=root,path=lambda relative,exists=False:root/relative)
            with self.assertRaisesRegex(ValueError,'enabled assignment requires'):
                bridge.policy(host)

    def test_common_docs_mutation_invalidates_checked_state(self):
        for name in ('common-quality.md','common-conditional-policy.md'):
            with self.subTest(name=name), tempfile.TemporaryDirectory() as d:
                root=Path(d);policy=setup_cell(root)
                (root/'docs').mkdir();doc=root/'docs'/name;doc.write_text('frozen common contract')
                initial=root/'inputs/initial';(initial/'pack').mkdir(parents=True)
                for filename in ('original.png','current.png','current.svg','public.svg','bounds.json'):
                    (initial/filename).write_bytes(b'synthetic fixture')
                (initial/'pack/pack.json').write_text('{"frames":[]}')
                (root/'inputs/sam.json').write_text('{}')
                controller=flow.Flow(root)
                controller.begin('run1')
                controller.checked_state('run1')
                doc.write_text('changed common contract')
                with self.assertRaisesRegex(ValueError,'frozen prompt bytes changed'):
                    controller.checked_state('run1')

    def test_off_assignment_retains_explicit_observation_disable(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);setup_cell(root)
            self.assertIsNone(flow.Flow(root).observation_proposals())

if __name__=='__main__':unittest.main()
