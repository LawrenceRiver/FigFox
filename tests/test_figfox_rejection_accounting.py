import importlib.util
import json
from pathlib import Path

spec=importlib.util.spec_from_file_location('batch_accounting',Path(__file__).resolve().parents[1]/'scripts/batch-experiment.py')
batch=importlib.util.module_from_spec(spec);spec.loader.exec_module(batch)


def test_explicit_pregeneration_rejection_is_separate_from_reported_usage():
    call={'model':'deepseek-flash','usage':{},'error':{'type':'HTTPError','status':402,
          'response_body':json.dumps({'error':{'message':'Insufficient Balance'}})}}
    batch.classify_rejected_call(call)
    assert call['cost']['estimated_usd']==0
    assert call['usage']=={}
    result=batch.token_summary([call,{'usage':{'prompt_tokens':100,'completion_tokens':12}}])
    assert result['token_usage_complete'] and result['total_tokens']==112


def test_unknown_failure_or_partial_usage_never_assumed_free():
    for call in [
        {'model':'deepseek-flash','usage':{},'error':{'type':'TimeoutError'}},
        {'model':'deepseek-flash','usage':{},'error':{'type':'HTTPError','status':500,
         'response_body':json.dumps({'error':{'message':'Insufficient Balance'}})}},
        {'model':'deepseek-flash','usage':{'prompt_tokens':10},'error':{'type':'HTTPError','status':402,
         'response_body':json.dumps({'error':{'message':'Insufficient Balance'}})}}]:
        batch.classify_rejected_call(call)
        assert 'usage_status' not in call
        assert not batch.token_summary([call])['token_usage_complete']
