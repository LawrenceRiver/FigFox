import base64
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

from PIL import Image

PACKAGE = Path(__file__).resolve().parents[1] / 'skills' / 'figfox'
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="40" height="30" viewBox="0 0 40 30"><g id="panel"><text id="label" x="2" y="12">Source</text><rect id="shape" x="2" y="15" width="10" height="10"/></g><text id="outside" x="22" y="12">Keep</text></svg>'


class PortableSkillTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.assertTrue((PACKAGE / 'SKILL.md').is_file(), 'portable skill entry point missing')
        shutil.copytree(PACKAGE, self.root / 'installed')
        self.tool = self.root / 'installed' / 'scripts' / 'svg_tools.py'
        self.source = self.root / 'source.png'
        Image.new('RGB', (40, 30), 'white').save(self.source)
        self.svg = self.root / 'initial.svg'
        self.svg.write_text(SVG)

    def run_tool(self, *args):
        return subprocess.run([sys.executable, str(self.tool), *map(str, args)], cwd=self.root, capture_output=True, text=True)

    def test_installed_package_inspects_native_objects_without_repository(self):
        result = self.run_tool('inspect', self.svg)
        self.assertEqual(result.returncode, 0, result.stderr)
        data = json.loads(result.stdout)
        self.assertEqual(data['counts']['text'], 2)
        self.assertEqual(data['counts']['rect'], 1)
        self.assertIsNone(data['visual_quality_pass'])

    def test_scoped_edit_changes_selected_label_and_preserves_neighbor(self):
        plan = {'transactions': [{'id': 'fix-label', 'target_ids': ['panel'], 'depends_on': [], 'operations': [{'op': 'text', 'id': 'label', 'text': 'Edited'}]}]}
        file = self.root / 'plan.json'; file.write_text(json.dumps(plan))
        final = self.root / 'final.svg'
        result = self.run_tool('apply', self.svg, '--plan', file, '--source', self.source, '--out', final)
        self.assertEqual(result.returncode, 0, result.stderr)
        index = {n.get('id'): n for n in ET.parse(final).getroot().iter()}
        self.assertEqual(index['label'].text, 'Edited')
        self.assertEqual(index['outside'].text, 'Keep')
        self.assertEqual(self.svg.read_text(), SVG)

    def test_out_of_scope_write_is_rejected_without_output(self):
        plan = {'transactions': [{'id': 'bad', 'target_ids': ['panel'], 'depends_on': [], 'operations': [{'op': 'text', 'id': 'outside', 'text': 'Damaged'}]}]}
        file = self.root / 'plan.json'; file.write_text(json.dumps(plan))
        final = self.root / 'final.svg'
        result = self.run_tool('apply', self.svg, '--plan', file, '--out', final)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('outside', result.stderr)
        self.assertFalse(final.exists())

    def test_image_wrapper_is_flagged_without_editability_claim(self):
        buf = io.BytesIO(); Image.new('RGB', (40, 30)).save(buf, format='PNG')
        data = base64.b64encode(buf.getvalue()).decode()
        self.svg.write_text('<svg xmlns="http://www.w3.org/2000/svg" width="40" height="30"><image id="flat" width="40" height="30" href="data:image/png;base64,' + data + '"/></svg>')
        result = self.run_tool('inspect', self.svg)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('image_only_document', json.loads(result.stdout)['warnings'])

    def test_equal_size_paired_views_preserve_source_and_draft(self):
        draft = self.root / 'draft.png'; Image.new('RGB', (40, 30), 'blue').save(draft)
        out = self.root / 'pairs'
        result = self.run_tool('views', '--source', self.source, '--draft', draft, '--out', out)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(len(list(out.glob('*-pair.png'))), 4)
        manifest = json.loads((out / 'views.json').read_text())
        self.assertTrue(all(v['source_left'] for v in manifest['regions']))

    def test_source_crop_remains_independent_embedded_image(self):
        plan = {'transactions': [{'id': 'photo', 'target_ids': ['panel'], 'depends_on': [], 'operations': [{'op': 'source_crop', 'parent_id': 'panel', 'id': 'photo', 'source_box': [0, 0, 2, 2], 'target_box': [15, 15, 4, 4], 'remove_ids': []}]}]}
        file = self.root / 'plan.json'; file.write_text(json.dumps(plan))
        final = self.root / 'final.svg'
        result = self.run_tool('apply', self.svg, '--plan', file, '--source', self.source, '--out', final)
        self.assertEqual(result.returncode, 0, result.stderr)
        index = {n.get('id'): n for n in ET.parse(final).getroot().iter()}
        photo = index['photo']
        self.assertTrue(photo.tag.endswith('}image'))
        data = base64.b64decode(photo.get('href').split(',', 1)[1])
        with Image.open(io.BytesIO(data)) as image:
            self.assertEqual(image.size, (2, 2))
            self.assertEqual(image.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(index['label'].text, 'Source')

    @unittest.skipUnless(shutil.which('rsvg-convert'), 'local SVG renderer unavailable')
    def test_render_produces_real_canvas_sized_png(self):
        output = self.root / 'rendered.png'
        result = self.run_tool('render', self.svg, '--out', output)
        self.assertEqual(result.returncode, 0, result.stderr)
        with Image.open(output) as image:
            self.assertEqual(image.size, (40, 30))


if __name__ == '__main__':
    unittest.main()
