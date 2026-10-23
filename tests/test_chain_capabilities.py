"""Synthetic offline capability dataflow; never research results."""
import importlib
import json
from pathlib import Path

import pytest
from PIL import Image
from figfox_plus.native import pipeline

OFF = {'version': 'capabilities-v1', 'sam': False, 'code_methods': False}
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect id="a" x="1" y="1" width="20" height="20" fill="red"/></svg>'


def test_policy_is_strict_detached_and_stable():
    spec = importlib.util.find_spec('figfox_plus.native.capabilities')
    assert spec is not None, 'frozen capabilities policy is missing'
    c = importlib.import_module(spec.name)
    p = c.normalize_capabilities(OFF)
    assert c.capability_hash(p) == c.capability_hash(dict(reversed(list(p.items()))))
    for bad in (0, 'off', None):
        with pytest.raises(ValueError):
            c.normalize_capabilities(dict(OFF, sam=bad))
    assert c.normalize_capabilities(None)['code_methods'] is True


def test_first_off_never_prepares_sam_and_generates_visible_svg(tmp_path, monkeypatch):
    original = tmp_path/'original.png'; Image.new('RGB', (100,100), 'white').save(original)
    monkeypatch.setattr(pipeline, 'prepare_assets', lambda *a, **k: pytest.fail('disabled SAM called'))
    prompts=[]
    def sender(prompt, images, *args):
        prompts.append(prompt); assert images == [original]
        return SVG
    root = pipeline.first(original, tmp_path, send=sender, capabilities=OFF)
    assert root.find('{http://www.w3.org/2000/svg}rect') is not None
    assert json.loads((tmp_path/'sam.json').read_text())['status'] == 'disabled_by_assignment'
    assert 'def cuboid' not in prompts[0]


@pytest.mark.parametrize('declaration', ['data-plus-sp=\'{"kind":"geometry","data":{}}\'', 'data-plus-crop="1,1,10,10"', 'data-plus-color=\'{"fill":[1,1,2,2]}\''])
def test_first_off_rejects_declarations_before_execution(tmp_path, monkeypatch, declaration):
    original=tmp_path/'original.png'; Image.new('RGB',(100,100)).save(original)
    monkeypatch.setattr(pipeline, 'prepare_assets', lambda *a, **k: pytest.fail('SAM called'))
    monkeypatch.setattr(pipeline, 'sp_element', lambda *a, **k: pytest.fail('SP called'))
    monkeypatch.setattr(pipeline, 'execute', lambda *a, **k: pytest.fail('method called'))
    with pytest.raises(ValueError, match='disabled'):
        pipeline.first(original,tmp_path,send=lambda *a: SVG.replace('id="a"', 'id="a" '+declaration),capabilities=OFF)


def test_sam_failure_precedes_sender(tmp_path, monkeypatch):
    original=tmp_path/'original.png'; Image.new('RGB',(100,100)).save(original)
    monkeypatch.setattr(pipeline,'prepare_assets',lambda *a, **k: {'assets':[], 'status':{'sam':'failed'}})
    with pytest.raises(ValueError,match='SAM'):
        pipeline.first(original,tmp_path,send=lambda *a: pytest.fail('paid sender reached'),capabilities=dict(OFF,sam=True))


@pytest.mark.parametrize('stale_revision', [False, True])
def test_chain_exports_terminal_review_image(tmp_path, monkeypatch, stale_revision):
    """Synthetic host integration: final paths must follow the committed review."""
    import hashlib
    from figfox_plus.native import chain
    from figfox_plus.native.document import parse
    original = tmp_path/'source.png'; Image.new('RGB', (100, 100), 'white').save(original)
    observed = {}
    first_sender = lambda *a: SVG
    review_sender = lambda *a, **k: {'role': 'assistant'}

    def first(image, run, *, send, capabilities, sam_service_url):
        observed['first_policy'] = capabilities
        assert send is first_sender
        return parse(send('synthetic', [image], run/'gpt55', 'first'))

    def prepare(bundle, folder, *, upstream_arrow_specs, capabilities):
        observed['review_policy'] = capabilities
        assert upstream_arrow_specs == {}
        Path(folder).mkdir(parents=True)

    def review(folder, *, sender, request_limit, capabilities):
        assert sender is review_sender and request_limit == 2
        terminal = Path(folder)/'terminal.svg'
        terminal.write_text(SVG.replace('red', 'blue'))
        png = Path(folder)/'terminal.png'; Image.new('RGB', (100, 100), 'blue').save(png)
        revision = hashlib.sha256(terminal.read_bytes()).hexdigest()
        if stale_revision: revision = '0'*64
        return {'status': 'visual_review_pending', 'images': {'case': {
            'svg': str(terminal), 'png': str(png), 'revision': revision,
            'original': str(original)}}, 'visual_passed': False}

    monkeypatch.setattr(chain, 'first', first)
    monkeypatch.setattr(chain, 'prepare', prepare)
    monkeypatch.setattr(chain, 'review_run', review)
    monkeypatch.setattr(chain, 'freeze_arrow_evidence', lambda *a, **k: pytest.fail('SAM-off arrow handoff'))
    out = tmp_path/'chain'
    args = dict(image_id='case', rerun_authorization='synthetic-only', capabilities=OFF,
                first_sender=first_sender, review_sender=review_sender)
    if stale_revision:
        with pytest.raises(ValueError, match='revision'): chain.run_chain(original, out, **args)
        assert not (out/'chain-result.json').exists()
    else:
        chain.run_chain(original, out, **args)
        result = json.loads((out/'chain-result.json').read_text())
        image = result['images']['case']
        assert 'blue' in Path(image['svg']).read_text()
        assert image['revision'] == hashlib.sha256(Path(image['svg']).read_bytes()).hexdigest()
        assert result['capabilities'] == OFF
        assert observed['first_policy'] == observed['review_policy'] == OFF
        assert result['visual_passed'] is False


def test_chain_cli_has_explicit_two_capability_axes(tmp_path, monkeypatch):
    from figfox_plus import cli
    from figfox_plus.native import chain
    captured = {}
    def run(*args, **kwargs): captured.update(kwargs)
    monkeypatch.setattr(chain, 'run_chain', run)
    assert cli.main(['chain', '--image', 'synthetic.png', '--out', str(tmp_path/'out'),
                     '--id', 'fixture', '--rerun-authorization', 'synthetic-only',
                     '--sam', 'off', '--code-methods', 'off',
                     '--sam-service-url', 'http://127.0.0.1:9999']) == 0
    assert captured['capabilities'] == OFF
    assert captured['sam_service_url'] == 'http://127.0.0.1:9999'


def test_full_chain_first_review_followup_commits_terminal_svg(tmp_path):
    """All real host stages, fake model messages; not a research sample."""
    import hashlib
    from figfox_plus.native import chain
    original = tmp_path/'original.png'; Image.new('RGB', (100, 100), 'white').save(original)
    counts = {'first': 0, 'review': 0}
    context = {}
    def first_sender(prompt, images, folder, purpose):
        counts['first'] += 1
        assert images == [original]
        return SVG
    def review_sender(messages, tools, folder, **kwargs):
        counts['review'] += 1
        # No candidate is executed in the first two fake turns.
        if counts['review'] == 1:
            bundle = json.loads((Path(folder)/'inputs.json').read_text())
            context['revision'] = bundle['images']['case']['current_revision']
        revision = context['revision']
        issue = {'id': 'synthetic-i', 'image_id': 'case', 'category': 'S1',
                 'decision': 'confirmed', 'target_ids': ['a'], 'neighbor_ids': [],
                 'description': 'synthetic wrong shape',
                 'original_evidence': 'synthetic original', 'current_evidence': 'synthetic current'}
        program = {'id': 'synthetic-p', 'issue_ids': ['synthetic-i'], 'image_id': 'case',
                   'base_revision': revision, 'phase': 'reconstructor', 'route': 'generated_python',
                   'target_ids': ['a'], 'depends_on': [], 'source_code':
                   'import xml.etree.ElementTree as ET\n'
                   'tree=ET.parse(INPUT_SVG)\n'
                   'tree.getroot()[0].set("fill","blue")\n'
                   'tree.write(OUTPUT_SVG,encoding="unicode")\n'}
        return {'role': 'assistant', 'content': json.dumps({
            'issues': [issue], 'programs': [program] if counts['review'] == 3 else []})}

    out = tmp_path/'chain'
    chain.run_chain(original, out, image_id='case', rerun_authorization='synthetic-only',
                    capabilities=OFF, first_sender=first_sender, review_sender=review_sender)
    result = json.loads((out/'chain-result.json').read_text())
    review = json.loads(Path(result['review_result']).read_text())
    assert counts == {'first': 1, 'review': 3}
    assert review['followup']['opened'] is True
    assert 'blue' in Path(result['images']['case']['svg']).read_text()
    assert result['images']['case']['revision'] == hashlib.sha256(Path(result['images']['case']['svg']).read_bytes()).hexdigest()
    assert result['images']['case']['revision'] == review['followup']['images']['case']['revision']
    assert result['visual_passed'] is False
    events = [json.loads(line) for path in out.rglob('invocation-trace.jsonl') for line in path.read_text().splitlines()]
    assert not [e for e in events if e['category'] == 'code_intervention' and e['status'] == 'started']
    assert [e for e in events if e['method'] == 'program_transaction' and e['status'] == 'changed_unverified']
    assert [e for e in events if e['method'] == 'stage' and e['category'] == 'common_guard' and e['status'] == 'completed']
