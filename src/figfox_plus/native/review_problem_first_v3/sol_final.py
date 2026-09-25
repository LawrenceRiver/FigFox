"""Reserved final Sol comparison: a shared durable ledger permits one attempt."""
import fcntl
import hashlib
import json
from pathlib import Path
import time
import urllib.request
import urllib.error
from ...state import write_json
from ..review_luna_v1.transport import body_for, credential, message_from
from ..single_call.transport import _open_http


def final_sender(ledger_dir, *, send_http=None):
    """Create adapter only; no request until explicitly called by final runner."""
    ledger=Path(ledger_dir).resolve()
    def send(messages,tools,task_dir,*,request_limit=1):
        if request_limit!=1:raise ValueError('final Sol comparison permits one request')
        root=Path(task_dir).resolve();root.mkdir(parents=True,exist_ok=True)
        for ancestor in (root,*root.parents):
            if (ancestor/'local-replay.json').exists():raise ValueError('local replay cannot call Sol')
        if send_http is None:
            if not (ledger/'final-ready.json').exists():raise ValueError('final version not yet designated')
            inputs=json.loads((root/'inputs.json').read_text())
            if list(inputs['images'])!=['privacy']:raise ValueError('final Sol comparison is Privacy only')
        ledger.mkdir(parents=True,exist_ok=True)
        with (ledger/'request.lock').open('a') as lock:
            fcntl.flock(lock,fcntl.LOCK_EX)
            if (ledger/'attempt.json').exists():raise ValueError('Sol final request already attempted; no retry in any output folder')
            body=body_for(messages,tools)
            body.update(model='gpt-6-sol',reasoning={'effort':'medium','summary':'auto'},max_output_tokens=128000)
            encoded=json.dumps(body,ensure_ascii=False).encode()
            token=hashlib.sha256(encoded).hexdigest();folder=root/'model-turns'/token;folder.mkdir(parents=True,exist_ok=True)
            write_json(folder/'request.json',{'endpoint':'https://api.openai.com/v1/responses','body':body})
            headers={'Content-Type':'application/json'}
            if send_http is None:headers['Authorization']='Bearer '+credential()
            attempt={'request_hash':token,'task_dir':str(root),'model':'gpt-6-sol','reasoning_effort':'medium','retry_allowed':False}
            write_json(ledger/'attempt.json',attempt);write_json(folder/'attempt.json',attempt)
            request=urllib.request.Request('https://api.openai.com/v1/responses',encoded,headers)
            try:
                final=None;last=0;progress={'summary_chars':0,'tool_argument_chars':0}
                with (send_http or _open_http)(request,timeout=1800) as response,(folder/'events.jsonl').open('w') as log:
                    for line in response:
                        line=line.decode() if isinstance(line,bytes) else line
                        if not line.startswith('data:'):continue
                        data=line[5:].strip()
                        if data=='[DONE]':break
                        event=json.loads(data);log.write(json.dumps(event,ensure_ascii=False)+'\n');log.flush()
                        kind=event.get('type','')
                        if kind=='response.reasoning_summary_text.delta':progress['summary_chars']+=len(event.get('delta',''))
                        if kind=='response.function_call_arguments.delta':progress['tool_argument_chars']+=len(event.get('delta',''))
                        if time.monotonic()-last>2:write_json(folder/'progress.json',progress);last=time.monotonic()
                        if kind=='response.completed':final=event['response'];break
                        if kind in ('error','response.failed','response.incomplete'):
                            write_json(folder/'provider-failure.json',event);raise ValueError('Sol response failed or incomplete; no retry')
                if final is None:raise ValueError('Sol stream ended before completed; no retry')
                write_json(folder/'response.json',final);write_json(folder/'usage.json',final.get('usage',{}))
                return message_from(final)
            except Exception as exc:
                record={'type':type(exc).__name__,'message':str(exc),'retry_allowed':False}
                if isinstance(exc,urllib.error.HTTPError):record.update(status=exc.code,response_body=exc.read(65536).decode(errors='replace'))
                write_json(folder/'error.json',record);raise
    return send
