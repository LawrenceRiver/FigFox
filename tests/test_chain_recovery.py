import json

import pytest

from figfox_plus.native import chain


def saved_case(tmp_path):
    image = tmp_path/'original.png'
    image.write_bytes(b'original fixture')
    out = tmp_path/'run'
    run = out/'native-fixture'
    (run/'gpt55').mkdir(parents=True)
    (run/'run.json').write_text(json.dumps({'original':str(image)}))
    (run/'sam.json').write_text(json.dumps({'source_hash':chain.sha(image)}))
    (run/'gpt55/response.json').write_text(json.dumps({
        'status':'completed','model':'gpt-5.5','output':[{'type':'message','content':[
            {'type':'output_text','text':'<svg><desc>A & B</desc></svg>'}]}]}))
    return image, out, run


def test_recovery_uses_saved_response_without_calling_gpt(tmp_path, monkeypatch):
    image, out, run = saved_case(tmp_path)
    def forbidden(*args, **kwargs):
        pytest.fail('recovery must never send a GPT request')
    monkeypatch.setattr(chain, 'call_gpt55', forbidden)
    def first(original, destination, *, send, sam):
        assert destination == run
        assert sam['source_hash'] == chain.sha(image)
        assert send('unused', [], run/'gpt55', 'unused') == '<svg><desc>A & B</desc></svg>'
        raise RuntimeError('stopped before rendering')
    monkeypatch.setattr(chain, 'first', first)
    with pytest.raises(RuntimeError, match='stopped before rendering'):
        chain.run_chain(image,out,image_id='case-002',rerun_authorization='unused',resume_first=run)


@pytest.mark.parametrize('condition', ['changed_image', 'existing_review', 'existing_baseline'])
def test_recovery_rejects_wrong_input_and_completed_stages(tmp_path, condition):
    image, out, run = saved_case(tmp_path)
    if condition == 'changed_image':image.write_bytes(b'changed')
    elif condition == 'existing_review':(out/'review').mkdir()
    else:(run/'stage-0').mkdir()
    with pytest.raises(SystemExit):
        chain.run_chain(image,out,image_id='case-002',rerun_authorization='unused',resume_first=run)


def test_resume_baseline_rejects_changed_saved_svg(tmp_path):
    image,out,run=saved_case(tmp_path)
    (run/'stage-0').mkdir()
    (run/'stage-0/scene.svg').write_text('<svg/>')
    (run/'run.json').write_text(json.dumps({'original':str(image),'baseline_svg_sha256':'incorrect'}))
    with pytest.raises(SystemExit,match='hash mismatch'):
        chain.run_chain(image,out,image_id='case-001',rerun_authorization='unused',resume_baseline=run)
