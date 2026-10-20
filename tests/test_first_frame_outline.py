"""First-pass outlines retain their generated paint; repair tools remain unchanged."""
from pathlib import Path
import json, tempfile, unittest
import xml.etree.ElementTree as ET
from PIL import Image
from figfox_plus.native.pipeline import first
from figfox_plus.native.tools import execute, nodes

class FirstFrameOutlineTests(unittest.TestCase):
    def generate(self, *, fill='#ffffff', stroke='#7441aa', kind='frame', style=None, sampled='#fdfdfd', attribute='stroke'):
        root=ET.Element('{http://www.w3.org/2000/svg}svg',{'width':'10','height':'10'})
        attrs={'id':'f','x':'0','y':'0','width':'10','height':'10','fill':fill,
               'stroke':stroke,'data-plus-kind':kind,'data-plus-color':json.dumps({attribute:[0,0,10,10]})}
        if style is not None:attrs['style']=style
        ET.SubElement(root,'{http://www.w3.org/2000/svg}rect',attrs)
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name);source=folder/'source.png';Image.new('RGB',(10,10),sampled).save(source)
            result=first(source,folder,send=lambda *args,**kwargs:ET.tostring(root,encoding='unicode'),sam={'assets':[]})
            receipts=json.loads((folder/'first-color-execution.json').read_text())
        return nodes(result)['f'],receipts

    def test_colored_outline_retained(self):
        node,_=self.generate();self.assertEqual(node.get('stroke'),'#7441aa')

    def test_gradient_fill_outline_retained(self):
        node,_=self.generate(fill='url(#greenPanel)',stroke='#80b77a',sampled='#f4fbef')
        self.assertEqual(node.get('stroke'),'#80b77a')

    def test_gray_outline_retained(self):
        node,_=self.generate(stroke='#111');self.assertEqual(node.get('stroke'),'#111')

    def test_inline_style_remains_authoritative(self):
        node,_=self.generate(stroke='none',style='stroke:purple;fill:white')
        self.assertEqual(node.get('style'),'stroke:purple;fill:white')

    def test_non_frame_stroke_still_sampled(self):
        node,_=self.generate(kind='line');self.assertEqual(node.get('stroke'),'#fdfdfd')

    def test_fill_still_sampled(self):
        node,_=self.generate(attribute='fill',sampled='#e0e0e0')
        self.assertEqual(node.get('fill'),'#e0e0e0');self.assertEqual(node.get('stroke'),'#7441aa')

    def test_no_existing_stroke_still_sampled(self):
        node,_=self.generate(stroke='none',sampled='#ff0000');self.assertEqual(node.get('stroke'),'#ff0000')

    def test_preservation_explicitly_recorded(self):
        _,logs=self.generate();self.assertEqual(logs[0]['status'],'skipped')
        self.assertEqual(logs[0]['result']['color'],'#7441aa')

    def test_repair_sample_tool_remains_unrestricted(self):
        with tempfile.TemporaryDirectory() as name:
            folder=Path(name);source=folder/'source.png';Image.new('RGB',(10,10),'red').save(source)
            root=ET.fromstring('<svg xmlns="http://www.w3.org/2000/svg"><rect id="f" width="10" height="10" data-plus-kind="frame" stroke="#7441aa" fill="#ffffff"/></svg>')
            op={'id':'p','issue_id':'i','action':'sample_color','target_ids':['f'],'args':{'source_crop':[0,0,10,10],'attribute':'stroke'}}
            result,logs=execute(root,[op],[{'id':'i','target_ids':['f']}],source,folder)
            self.assertEqual(nodes(result)['f'].get('stroke'),'#ff0000')
            self.assertEqual(logs[0]['status'],'executed')

if __name__=='__main__':unittest.main()
