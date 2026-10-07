import json
from PIL import Image
import pytest

from figfox_plus.native.document import parse, serialize, measure
from figfox_plus.native.first_postprocess import apply_declarations


@pytest.mark.parametrize('inline', [False, True])
def test_background_sample_preserves_outline_and_allows_valid_neighbor_sample(tmp_path, inline):
    source = tmp_path / 'source.png'
    image = Image.new('RGB', (40, 40), 'white')
    image.paste('#275e99', (20, 20, 30, 30))
    image.save(source)
    style = 'style="stroke:rgb(20,80,160);fill:white"' if inline else ''
    root = parse(f'''<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">
      <rect id="bad" x="2" y="2" width="14" height="14" fill="white" stroke="#1450a0" stroke-width="2" stroke-dasharray="3 2" {style} data-plus-color='{{"fill":[0,0,5,5],"stroke":[0,0,5,5]}}'/>
      <rect id="good" x="22" y="22" width="14" height="14" fill="white" stroke="red" stroke-width="2" data-plus-color='{{"stroke":[20,20,5,5]}}'/>
    </svg>''')
    original = serialize(root)
    result = apply_declarations(root, source, tmp_path, preserve_candidates=True)
    by = {n.get('id'): n for n in result.iter()}
    assert by['bad'].get('stroke') == '#1450a0'
    assert by['bad'].get('stroke-dasharray') == '3 2'
    assert by['bad'].get('x') == '2' and by['bad'].get('width') == '14'
    assert by['good'].get('stroke') == '#275e99'
    assert serialize(root) == original
    receipt = json.loads((tmp_path / 'first-postprocessing.json').read_text())
    deferred = next(r for r in receipt['steps'] if r['object_id'] == 'bad')
    assert deferred['status'] == 'deferred' and deferred['original_preserved']
    assert deferred['source_color_check']['status'] == 'unverified'
    candidate = receipt['candidates'][deferred['candidate_index']]
    assert candidate['status'] == 'available' and not candidate['automatically_adopted']
    assert candidate['model_requests'] == 0
    with Image.open(candidate['image']['png']) as alternative:
        assert alternative.size == (40,40)
        alternative.verify()
    import xml.etree.ElementTree as ET
    proposed = next(n for n in ET.parse(candidate['image']['svg']).iter() if n.get('id') == 'bad')
    assert proposed.get('stroke') == '#ffffff' and proposed.get('stroke-dasharray') == '3 2'
    assert next(r for r in receipt['steps'] if r['object_id'] == 'good')['status'] == 'executed'
    measure(result, tmp_path / 'output.png')
    with Image.open(tmp_path / 'output.png') as output:
        assert output.size == (40, 40)


def test_legitimate_muted_stroke_and_fill_samples_are_not_blocked(tmp_path):
    source = tmp_path / 'source.png'
    Image.new('RGB', (20, 20), '#999999').save(source)
    root = parse('''<svg xmlns="http://www.w3.org/2000/svg" width="20" height="20">
      <rect id="line" width="10" height="10" fill="white" stroke="black" data-plus-color='{"stroke":[0,0,4,4]}'/>
      <rect id="fill" x="12" width="6" height="10" fill="white" stroke="black" data-plus-color='{"fill":[0,0,4,4]}'/>
    </svg>''')
    result = apply_declarations(root, source, tmp_path)
    by = {n.get('id'): n for n in result.iter()}
    assert by['line'].get('stroke') == '#999999'
    assert by['fill'].get('fill') == '#999999'
    assert json.loads((tmp_path / 'first-postprocessing.json').read_text())['deferred_count'] == 0


@pytest.mark.integration
def test_default_chain_preserves_color_and_original_turns_without_a_candidate_branch(tmp_path, monkeypatch):
    from PIL import ImageDraw
    from figfox_plus.native import chain, pipeline
    from figfox_plus.native.review_problem_first_v13.lean_inspection import CATEGORIES
    import xml.etree.ElementTree as ET
    source = tmp_path/'source.png'
    image = Image.new('RGB',(40,40),'white')
    ImageDraw.Draw(image).rectangle((2,2,16,16),fill='#dddddd',outline='black')
    image.save(source)
    svg = '''<svg xmlns="http://www.w3.org/2000/svg" width="40" height="40">
      <rect id="frame" x="2" y="2" width="14" height="14" fill="#dddddd" stroke="black"
        data-plus-color='{"fill":[0,0,1,1],"stroke":[0,0,1,1]}'/></svg>'''
    monkeypatch.setattr(pipeline,'prepare_assets',lambda *args,**kwargs:{'assets':[], 'status':{'sam':'fixture'}})
    monkeypatch.setattr(chain,'call_gpt55',lambda *args,**kwargs:svg)
    calls = []
    def sender(messages, tools, root, **kwargs):
        calls.append(messages)
        plan = {'compact_category_sweeps':[{'category':category,'whole_image_observation':'Compared original and current.',
            'svg_observation':'Read the complete frame.','candidates':[]} for category in CATEGORIES],
            'issues':[],'programs':[]}
        return {'role':'assistant','content':json.dumps(plan)}
    out = tmp_path/'run'
    chain.run_chain(source,out,image_id='sample',rerun_authorization='offline regression',review_sender=sender)
    result = json.loads((out/'review/sample/result.json').read_text(encoding='utf-8'))
    assert len(calls) == 2 and result['repair_candidates'] == []
    assert not list(out.rglob('first-candidates'))
    assert not list(out.rglob('source-candidates'))
    assert '下载候选 SVG' not in (out/'review/sample/index.html').read_text(encoding='utf-8')
    assert next(node for node in ET.parse(out/'final.svg').iter() if node.get('id')=='frame').get('stroke')=='black'
