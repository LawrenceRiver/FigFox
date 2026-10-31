"""Current SVG line geometry facts. No reference coordinates or defect verdicts."""
import json
from pathlib import Path
import subprocess
import xml.etree.ElementTree as ET
from ..runtime import browser_environment, node_command


def build_line_facts(svg_path):
    """Read the explicit current SVG and measure it in an offline browser."""
    ET.register_namespace('', 'http://www.w3.org/2000/svg')
    svg = Path(svg_path).read_text()
    root = ET.fromstring(svg)
    if root.tag.rsplit('}', 1)[-1] != 'svg':
        raise ValueError('Input must be SVG')
    # Active and foreign HTML content is not needed for geometry measurement.
    for node in root.iter():
        for child in list(node):
            if child.tag.rsplit('}', 1)[-1] in {'script', 'foreignObject', 'animate', 'animateMotion', 'animateTransform', 'set'}:
                node.remove(child)
        for attr in list(node.attrib):
            if attr.lower().startswith('on'):
                del node.attrib[attr]
    env = browser_environment()
    runtime = Path(__file__).resolve().parents[3]/'runtime/current-line-facts.cjs'
    result = subprocess.run([node_command(), str(runtime)],
                            input=json.dumps({'svg': ET.tostring(root, encoding='unicode')}),
                            text=True, capture_output=True, env=env, timeout=120)
    if result.returncode:
        raise ValueError('Line facts measurement failed: '+result.stderr[:2000])
    return json.loads(result.stdout)
