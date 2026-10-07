import hashlib
import json
from pathlib import Path

from PIL import Image
import pytest

from figfox_plus.native.first_recovery import recover_baseline
from figfox_plus.native.document import parse
from figfox_plus.native.pipeline import stage
from figfox_plus.state import write_json
from figfox_plus.usage_cost import cost_snapshot

SVG='<svg xmlns="http://www.w3.org/2000/svg" width="24" height="16"><rect id="frame" width="24" height="16" fill="red"/></svg>'


def fixture(tmp_path,raw='<svg><rect id="frame"'):
    original=tmp_path/'original.png';Image.new('RGB',(24,16),'red').save(original)
    run=tmp_path/'run/native-fixture';(run/'gpt55').mkdir(parents=True)
    (run/'gpt55/response.txt').write_text(raw,encoding='utf-8')
    write_json(run/'gpt55/request.json',{'model':'gpt-5.5','prompt':'original generic drawing contract',
        'images':[{'path':str(original),'sha256':hashlib.sha256(original.read_bytes()).hexdigest()}]})
    write_json(run/'sam.json',{'source_hash':hashlib.sha256(original.read_bytes()).hexdigest(),'assets':[]})
    return original,run


def first(original,run,*,send,sam):
    return parse(send('unused',[],run/'gpt55','unused'))


def test_truncated_first_draft_recovers_once_with_real_render_and_unchanged_raw(tmp_path):
    from figfox_plus.native.review_problem_first_v13.transport import send
    original,run=fixture(tmp_path)
    raw=(run/'gpt55/response.txt').read_bytes();calls=[]
    class Response:
        headers={'Content-Type':'application/json'}
        status=200
        def __enter__(self):return self
        def __exit__(self,*args):pass
        def read(self):return json.dumps({'model':'deepseek-flash','choices':[{'finish_reason':'stop',
            'message':{'role':'assistant','content':SVG}}],'usage':{'prompt_tokens':100,'completion_tokens':100}}).encode()
    def http(request,timeout):calls.append(request);return Response()
    def sender(messages,tools,folder,**kwargs):
        assert 'original generic drawing contract' in messages[0]['content'][0]['text']
        assert '<svg><rect id="frame"' in messages[0]['content'][0]['text']
        assert len(messages[0]['content'])==2 and kwargs['request_limit']==1
        return send(messages,tools,folder,send_http=http,**kwargs)
    recover_baseline(original,run,ValueError('missing complete SVG'),first=first,stage=stage,sender=sender,allow_model_recovery=True)
    assert (run/'gpt55/response.txt').read_bytes()==raw
    assert (run/'stage-0/scene.svg').is_file()
    with Image.open(run/'stage-0/preview.png') as im:
        assert im.size==(24,16) and im.convert('RGB').getpixel((10,8))==(255,0,0)
    assert json.loads((run/'first-recovery.json').read_text(encoding='utf-8'))['status']=='recovered'
    with pytest.raises(ValueError,match='already attempted'):
        recover_baseline(original,run,ValueError('still bad'),first=first,stage=stage,sender=sender,allow_model_recovery=True)
    assert len(calls)==1
    cost=cost_snapshot(run.parent)
    assert cost['model_requests']==2 and cost['unknown_cost_requests']==1
    assert cost['estimated_usd']>0 and not cost['cost_complete']


def test_complete_partial_svg_is_rendered_without_another_paid_request(tmp_path):
    original,run=fixture(tmp_path,SVG)
    write_json(run/'gpt55/error.json',{'type':'ConnectionResetError'})
    before=(run/'gpt55/response.txt').read_bytes()
    def forbidden(*args,**kwargs):pytest.fail('complete partial SVG needs no additional paid model')
    recover_baseline(original,run,ConnectionResetError('lost completion'),first=first,stage=stage,sender=forbidden)
    assert (run/'gpt55/response.txt').read_bytes()==before
    assert (run/'stage-0/preview.png').is_file() and not (run/'first-recovery-attempt.json').exists()
    state=json.loads((run/'first-recovery.json').read_text(encoding='utf-8'))
    assert state['status']=='partial_reply_rendered' and state['original_api_completed'] is False


def test_bad_recovery_is_failed_and_cannot_start_an_unbounded_loop(tmp_path):
    original,run=fixture(tmp_path);calls=[]
    def sender(*args,**kwargs):calls.append(1);return {'content':'<svg><g>'}
    with pytest.raises(ValueError,match='missing complete SVG'):
        recover_baseline(original,run,ValueError('truncated'),first=first,stage=stage,sender=sender,allow_model_recovery=True)
    with pytest.raises(ValueError,match='already attempted'):
        recover_baseline(original,run,ValueError('truncated'),first=first,stage=stage,sender=sender,allow_model_recovery=True)
    assert len(calls)==1 and not (run/'stage-0/preview.png').exists()
    assert json.loads((run/'first-recovery.json').read_text(encoding='utf-8'))['status']=='failed'


def test_changed_source_evidence_cannot_start_recovery(tmp_path):
    original,run=fixture(tmp_path);original.write_bytes(b'changed')
    def forbidden(*args,**kwargs):pytest.fail('changed evidence must block before API')
    with pytest.raises(ValueError,match='evidence changed'):
        recover_baseline(original,run,ValueError('truncated'),first=first,stage=stage,sender=forbidden,allow_model_recovery=True)
    assert not (run/'first-recovery-attempt.json').exists()


def test_no_first_reply_does_not_retry_auth_or_network_failures(tmp_path):
    original,run=fixture(tmp_path,'')
    def forbidden(*args,**kwargs):pytest.fail('empty network failure must not retry automatically')
    with pytest.raises(ConnectionError,match='network error'):
        recover_baseline(original,run,ConnectionError('network error'),first=first,stage=stage,sender=forbidden)


def test_default_first_recovery_reports_failure_without_an_additional_model_call(tmp_path):
    original, run = fixture(tmp_path)
    before = (run/'gpt55/response.txt').read_bytes()
    failure = ValueError('missing complete SVG')
    def forbidden(*args, **kwargs):pytest.fail('default recovery cannot add a model call')
    with pytest.raises(ValueError, match='missing complete SVG') as raised:
        recover_baseline(original, run, failure, first=first, stage=stage, sender=forbidden)
    assert raised.value is failure
    assert (run/'gpt55/response.txt').read_bytes() == before
    assert not (run/'first-recovery-attempt.json').exists()
    assert not (run/'stage-0/preview.png').exists()
    record = json.loads((run/'first-recovery.json').read_text(encoding='utf-8'))
    assert record['status'] == 'manual_recovery_required' and record['additional_model_requests'] == 0
