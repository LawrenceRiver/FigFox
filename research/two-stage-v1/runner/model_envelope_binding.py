"""Bind machine envelope to proven same HTTP input, preserving all model judgments."""
import json,copy
from pathlib import Path
import run_ablation as r,live_api,bounded_trace

LOCALIZATION_TAIL='Finding_bindings are ONLY the explicitly requested corrections of unbound original object IDs; actual visual decisions/evidence remain frozen.'
def snapshot_from_system(text,marker):
 if text.count(marker)!=1:raise ValueError('ambiguous machine snapshot marker')
 source=text.split(marker,1)[1].lstrip();value,end=json.JSONDecoder().raw_decode(source);tail=source[end:].strip()
 if tail and tail!=LOCALIZATION_TAIL:raise ValueError('unrecognized suffix after machine snapshot')
 if not isinstance(value,dict) or set(value)!={'revision','evidence_hashes'}:raise ValueError('exact machine snapshot object required')
 return value

def bind(folder,stage,payload):
 folder=Path(folder);control=folder.parent.parent
 paths=list((control/'trace').glob('*-'+folder.parent.name+'-'+stage+'.json'))
 if len(paths)!=1:raise ValueError('one exact stage trace required for envelope binding')
 record=r.read(paths[0]);response=Path(record['response_file'])
 if r.sha(response)!=record['response_sha256']:raise ValueError('provider response proof changed')
 text,calls,_=live_api.extract(r.read(response),'chat_completions');original,_=bounded_trace.parse_model_object(text)
 if calls or original!=payload:raise ValueError('payload is not the exact saved model response')
 matches=[]
 for path in (folder/'api').glob('*-request.json'):
  body=r.read(path)['body']
  if r.digest(body)==record['body_sha256']:matches.append((path,body))
 if not matches:raise ValueError('exact saved input body required')
 path,body=sorted(matches,key=lambda item:str(item[0]))[0];snapshots=[]
 for message in body['messages']:
  text=message.get('content');marker='associations verbatim; never shift values between keys: '
  if message['role']=='system' and isinstance(text,str) and marker in text:snapshots.append(snapshot_from_system(text,marker))
 if len(snapshots)!=1:raise ValueError('unambiguous same-request snapshot required')
 snapshot=snapshots[0];result=copy.deepcopy(payload);operations=[]
 reports=[(key,result[key]) for key in ('main','semantic')] if {'main','semantic'}<=set(result) else [('plan',result['plan'])] if 'plan' in result else [('',result)]
 for pointer,report in reports:
  if report.get('revision')==snapshot['revision'] and report.get('evidence_hashes')==snapshot['evidence_hashes']:continue
  operations.append({'pointer':pointer,'operation':'host-bound machine envelope from same byte-verified API request; no quality field changed','original_revision':report.get('revision'),'original_evidence_hashes':report.get('evidence_hashes'),'canonical_snapshot':snapshot})
  report.update(copy.deepcopy(snapshot))
 return result,{'format':'same-request-machine-envelope-v1','request_file':str(path),'request_sha256':r.sha(path),'body_sha256':record['body_sha256'],'response_file':str(response),'response_sha256':r.sha(response),'model_sha256':r.digest(original),'operations':operations,'quality_fields_unchanged':True,'new_http_calls':0}
