"""Verify saved HTTP request/response before rebinding constant machine metadata."""
import json,hashlib
from pathlib import Path
import planner_packet_transport as transport

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def digest(v):return hashlib.sha256(json.dumps(v,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
def build(folder,trace_row,snapshot):
 folder=Path(folder);response=Path(trace_row['response_file'])
 if sha(response)!=trace_row['response_sha256']:raise ValueError('saved response changed')
 matching=[]
 for path in (folder/'api').glob('*-request.json'):
  body=json.loads(path.read_text())['body']
  if digest(body)==trace_row['body_sha256']:matching.append((path,body))
 if not matching:raise ValueError('exact saved request required')
 path,body=sorted(matching,key=lambda item:str(item[0]))[0];expected={'revision':snapshot['revision'],'evidence_hashes':snapshot['evidence_hashes']};plain=[];acks=[]
 for message in body['messages']:
  content=message['content']
  if message['role']=='system' and isinstance(content,str) and 'associations verbatim; never shift values between keys: ' in content:plain.append(json.loads(content.split('associations verbatim; never shift values between keys: ',1)[1]))
  if isinstance(content,list):
   for part in content:
    if part.get('type')!='text':continue
    try:packet=transport.decode_wire(part['text'])
    except (ValueError,KeyError,TypeError,json.JSONDecodeError):continue
    if isinstance(packet,dict) and 'connector_paint_ack_required_exact' in packet:acks.append(packet['connector_paint_ack_required_exact'])
 if plain!=[expected] or len(acks)!=1:raise ValueError('saved request does not prove exact snapshot and ack')
 ack=acks[0]
 if ack['candidate_receipt_sha256']!=sha(folder/'cell/runs/run1/round-1/candidate.json'):raise ValueError('request candidate identity mismatch')
 return {'request_file':str(path),'request_sha256':sha(path),'body_sha256':trace_row['body_sha256'],'response_file':str(response),'provider_response_sha256':sha(response),'expected_snapshot':expected,'expected_ack':ack,'exact_request_metadata_verified':True}
