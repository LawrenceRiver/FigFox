"""Per-call auditable timing, usage and estimates for the bounded two-stage run."""
import json,hashlib,re,time,threading,csv,html,os,tempfile
from pathlib import Path
from datetime import datetime,timezone
LOCK=threading.RLock()
def parse_model_object(text):
 duplicate_events=[]
 def unique(pairs):
  value={}
  for key,item in pairs:
   if key in value:
    canonical=lambda x:json.dumps(x,sort_keys=True,separators=(',',':'),allow_nan=False)
    if canonical(value[key])!=canonical(item):raise ValueError('conflicting duplicate model JSON key: '+key)
    event={'key':key,'canonical_value_sha256':hashlib.sha256(canonical(item).encode()).hexdigest()}
    if event not in duplicate_events:duplicate_events.append(event)
    continue
   value[key]=item
  return value
 def nonfinite(value):raise ValueError('nonfinite model JSON constant: '+value)
 source=text.lstrip();decoder=json.JSONDecoder(object_pairs_hook=unique,parse_constant=nonfinite);completion=None
 quote_repairs=[];deletion_repairs=[]
 for attempt in range(36):
  try:
   _,end=decoder.raw_decode(source);tail=source[end:]
   continuation=re.match(r',\s*"(new_required_findings|new_uncertain_findings|protected_regressions|uncertainty_reviews|pending_observation_reviews|current_bindings|connector_paint_ack|connector_visual_concerns|connector_concern_reviews)"\s*:',tail.lstrip())
   if source[end-1:end]=='}' and continuation:
    if len(deletion_repairs)>=4:raise ValueError('excessive premature JSON root closure repair')
    deletion_repairs.append({'kind':'premature root close before already written native field','remove_at_offset':end-1,'characters':'}','next_existing_key':continuation.group(1)});source=source[:end-1]+source[end:];continue
   break
  except json.JSONDecodeError as error:
   if error.msg=='Invalid \\escape' and source[error.pos:error.pos+1]=='\\' and source[error.pos+1:error.pos+2] not in ('"','\\','/','b','f','n','r','t','u'):
    if sum(x['kind']=='literal invalid JSON backslash' for x in quote_repairs)>=32:raise ValueError('excessive JSON escape repair')
    quote_repairs.append({'kind':'literal invalid JSON backslash','insert_before_offset':error.pos,'characters':'\\','written_escape_prefix':source[error.pos:error.pos+2]});source=source[:error.pos]+'\\'+source[error.pos:];continue
   if sum(x['kind']!='literal invalid JSON backslash' for x in quote_repairs)>=4:break
   hash_quote_repaired=False
   pattern=r'"([A-Za-z_][A-Za-z0-9_]*_sha256|revision|base_revision|original_png|current_svg|current_png|public_svg|bounds|pairs|pack_pixels|pack_metadata|sam_catalog)"\s*:\s*"([0-9a-f]{64})(?=[}\],])'
   for candidate in re.finditer(pattern,source):
    if candidate.end()>error.pos:continue
    quoted=False;escaped=False
    for char in source[:candidate.start()]:
     if quoted:
      if escaped:escaped=False
      elif char=='\\':escaped=True
      elif char=='"':quoted=False
     elif char=='"':quoted=True
    if quoted:continue
    offset=candidate.end();quote_repairs.append({'kind':'missing closing quote of already written 64-hex machine hash','insert_before_offset':offset,'characters':'"','existing_key':candidate.group(1),'existing_hash':candidate.group(2)});source=source[:offset]+'"'+source[offset:];hash_quote_repaired=True;break
   if hash_quote_repaired:continue
   match=re.match(r'([A-Za-z_][A-Za-z0-9_]*)"\s*:',source[error.pos:]) if error.msg=='Expecting property name enclosed in double quotes' else None
   if match:
    quote_repairs.append({'kind':'missing opening key quote','insert_before_offset':error.pos,'characters':'"','existing_key':match.group(1)});source=source[:error.pos]+'"'+source[error.pos:];continue
   missing_array=re.search(r',\s*"(unresolved_reasons|programs|issue_ids|resolved_ids|unresolved_ids|not_required|new_required_findings|new_uncertain_findings|protected_regressions|uncertainty_reviews)"\s*$',source[:error.pos]) if error.msg=="Expecting ',' delimiter" and source[error.pos:error.pos+1]==':' else None
   if missing_array:
    stack=[];quoted=False;escaped=False
    for char in source[:missing_array.start()]:
     if quoted:
      if escaped:escaped=False
      elif char=='\\':escaped=True
      elif char=='"':quoted=False
     elif char=='"':quoted=True
     elif char in '{[':stack.append(char)
     elif char in '}]':
      if not stack or stack.pop()!={'}':'{',']':'['}[char]:raise ValueError('ambiguous JSON container grammar')
    if not quoted and len(stack)>=2 and stack[-2:]==['{','[']:
     offset=missing_array.start();quote_repairs.append({'kind':'missing array close before already written native object field','insert_before_offset':offset,'characters':']','existing_key':missing_array.group(1)});source=source[:offset]+']'+source[offset:];continue
   if error.msg=="Expecting ',' delimiter" and source[error.pos:error.pos+1] in ('}',']'):
    stack=[];quoted=False;escaped=False
    for char in source[:error.pos]:
     if quoted:
      if escaped:escaped=False
      elif char=='\\':escaped=True
      elif char=='"':quoted=False
     elif char=='"':quoted=True
     elif char in '{[':stack.append(char)
     elif char in '}]':
      if not stack or stack.pop()!={'}':'{',']':'['}[char]:raise ValueError('ambiguous JSON container grammar')
    wanted={'}':'{',']':'['}[source[error.pos]]
    if not quoted and wanted in stack and stack[-1]!=wanted:
     suffix=''
     while stack[-1]!=wanted:suffix+='}' if stack.pop()=='{' else ']'
     if len(suffix)>4:raise ValueError('excessive JSON delimiter repair')
     quote_repairs.append({'kind':'missing descendant container close','insert_before_offset':error.pos,'characters':suffix});source=source[:error.pos]+suffix+source[error.pos:];continue
   break
 try:value,end=decoder.raw_decode(source)
 except json.JSONDecodeError as error:
  if error.pos!=len(source.rstrip()):raise
  stack=[];quoted=False;escaped=False
  for char in source.rstrip():
   if quoted:
    if escaped:escaped=False
    elif char=='\\':escaped=True
    elif char=='"':quoted=False
   elif char=='"':quoted=True
   elif char in '{[':stack.append(char)
   elif char in '}]':
    if not stack or {'}':'{',']':'['}[char]!=stack.pop():raise ValueError('mismatched JSON grammar cannot be inferred')
  if quoted or escaped or not stack or len(stack)>4:raise
  suffix=''.join('}' if char=='{' else ']' for char in reversed(stack));source=source.rstrip()+suffix
  value,end=decoder.raw_decode(source);completion={'operation':'append only missing final container delimiters; all original characters/values preserved','characters':suffix,'quality_fields_unchanged':True}
 tail=source[end:].strip()
 if not isinstance(value,dict):raise ValueError('model stage must be a JSON object')
 if tail and (len(tail)>4 or any(char not in '}]' for char in tail)):raise ValueError('additional model content cannot be silently discarded')
 if quote_repairs or deletion_repairs:completion={'operation':'repair only JSON punctuation; every written field/value retained, no judgment or code changed','offset_unit':'Unicode codepoints in each operation current source','insertions':quote_repairs,'deletions':deletion_repairs,'other_delimiter_repair':completion,'quality_fields_unchanged':True}
 if duplicate_events:completion={'operation':'coalesce only byte-equivalent canonical key/value duplicates; conflicting values rejected','duplicates':duplicate_events,'other_grammar_repair':completion,'quality_fields_unchanged':True}
 return value,completion or ({'operation':'discard surplus trailing closing delimiters after one complete object','characters':tail,'quality_fields_unchanged':True} if tail else None)
def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def write(path,value):
 path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
 with LOCK:
  temp=None
  try:
   with tempfile.NamedTemporaryFile(mode='w',encoding='utf-8',dir=path.parent,prefix=path.name+'.',suffix='.tmp',delete=False) as stream:
    temp=Path(stream.name);stream.write(json.dumps(value,ensure_ascii=False,indent=2,default=str));stream.flush();os.fsync(stream.fileno())
   os.replace(temp,path)
  finally:
   if temp is not None:temp.unlink(missing_ok=True)
def name(index,sample,stage):
 if not re.fullmatch(r'A[12]|B[1-4][123](?:-R[1-9][0-9]*)?',stage):raise ValueError('invalid business stage')
 return f'第{index:03d}张图-{sample}-{stage}'
def usage(response,pc):
 u=response.get('usage',{});inp=u.get('prompt_tokens',u.get('input_tokens'));out=u.get('completion_tokens',u.get('output_tokens'));cached=u.get('prompt_cache_hit_tokens',u.get('prompt_tokens_details',{}).get('cached_tokens',u.get('input_tokens_details',{}).get('cached_tokens',0)))
 reasoning=u.get('completion_tokens_details',u.get('output_tokens_details',{})).get('reasoning_tokens',0)
 cost=None if inp is None or out is None else ((inp-cached)*pc['input_usd_per_million']+cached*pc['cache_usd_per_million']+out*pc['output_usd_per_million'])/1e6
 return dict(input_tokens=inp,output_tokens=out,cached_input_tokens=cached,reasoning_tokens_included_in_output=reasoning,estimated_usd=cost,fee_basis='configured token rates, not provider invoice')
def cached(path,body_hash):
 path=Path(path)
 if not path.exists():return None
 record=json.loads(path.read_text())
 if record.get('body_sha256')!=body_hash:raise ValueError('stage input changed; prior receipt cannot replay')
 if record['status']!='completed':raise ValueError('unresolved/failed stage retained; automatic request replay forbidden')
 response=Path(record['response_file'])
 if not response.is_file() or sha(response)!=record['response_sha256']:raise ValueError('stage response hash mismatch')
 return json.loads(response.read_text())
def render(root):
 root=Path(root)
 with LOCK:
  rows=[json.loads(p.read_text()) for p in sorted(list((root/'trace').glob('*.json'))+list((root/'trace/history').glob('*.settlement.json')))]
  write(root/'trace-summary.json',{'rows':rows,'new_estimated_usd':sum((r.get('new_estimated_usd') or 0) for r in rows)})
  columns=['name','status','elapsed_seconds','input_tokens','output_tokens','cached_input_tokens','reasoning_tokens_included_in_output','estimated_usd','new_estimated_usd','request_id']
  with (root/'trace.csv').open('w') as stream:
   writer=csv.DictWriter(stream,fieldnames=columns,extrasaction='ignore');writer.writeheader();writer.writerows(rows)
  table='<tr>'+''.join('<th>'+html.escape(k)+'</th>' for k in columns)+'</tr>'
  table+=''.join('<tr>'+''.join('<td>'+html.escape(str(row.get(k,'')))+'</td>' for k in columns)+'</tr>' for row in rows)
  followup=root/'followup.json'
  panel=''
  if followup.exists():
   progress=json.loads(followup.read_text())
   panel='<section><h2>持续跟进状态</h2>'+''.join('<p><strong>'+html.escape(str(k))+'</strong>：'+html.escape(str(v))+'</p>' for k,v in progress.items())+'</section>'
  (root/'trace.html').write_text('<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="10"><title>FigFox 实际运行轨迹</title><style>body{font:14px system-ui;padding:24px}table{border-collapse:collapse}td,th{padding:8px;border:1px solid #ccc;text-align:left}th{background:#eef}</style><h1>FigFox 两阶段实际运行轨迹</h1>'+panel+'<p>费用为配置费率估算；复用项 new_estimated_usd=0。失败和未知费用不会计为零。</p><p>表内 completed 仅表示接口已返回，不代表原生程序或视觉质量通过。原生完成以顶部进度和各组 result.json 为准；正式评分后置。原模型回复与保守的原生协议验收投影分别保留。</p><table>'+table+'</table>')
def verify_tls_recovery(proof):
 exit_file=Path(proof['transport_exit_file']);prior=Path(proof['original_trace_file'])
 if sha(exit_file)!=proof['transport_exit_sha256'] or sha(prior)!=proof['original_trace_sha256']:raise ValueError('TLS failure provenance changed')
 failure=json.loads(exit_file.read_text());trace=json.loads(prior.read_text())
 if failure.get('request_id')!=proof['original_request_id'] or trace.get('request_id')!=proof['original_request_id'] or trace.get('status')!='failed_or_charge_unknown':raise ValueError('exact unresolved original attempt required')
 stderr=failure.get('stderr','')
 if failure.get('returncode')==0 or not all(part in stderr for part in ('do_handshake','ConnectionResetError','Connection reset by peer')):raise ValueError('specific TLS handshake reset evidence required')
 if Path(proof['expected_original_response_file']).exists():raise ValueError('original response exists; recover it instead of issuing another request')
 if proof.get('old_fee_reserve_retained') is not True or proof.get('old_request_replay_allowed') is not False:raise ValueError('unknown fees must remain reserved; old request ID must not be replayed')
 return failure

def verify_malformed_control_reply(raw):
 content=raw['choices'][0]['message']['content']
 if '<｜end▁of▁thinking｜>' not in content:raise ValueError('actual malformed control marker evidence required')
 try:parse_model_object(content)
 except json.JSONDecodeError:return True
 raise ValueError('valid existing JSON must be reused without new request')

def verify_invalid_verifier_reply(raw,expected_invalid):
 content=raw['choices'][0]['message']['content'];value,_=parse_model_object(content)
 required=('resolved_ids','unresolved_ids','not_required','new_required_findings','new_uncertain_findings','protected_regressions')
 invalid=[key for key in required if not isinstance(value.get(key),list)]
 if not invalid or sorted(invalid)!=sorted(expected_invalid):raise ValueError('only actual missing/invalid mandatory verifier arrays justify this correction')
 return value

def invoke(config,provider,financial_slot,messages,lease,folder,tools,send_once):
 import live_api
 stage=config['business_stage'];label=name(config['image_index'],config['current_sample_id'],stage);root=Path(config['trace_root']);path=root/'trace'/(label+'.json');pc=config['providers'][provider]
 body=live_api.body_for(pc,messages,tools);live_api.admit(pc,body)
 digest=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
 saved=cached(path,digest)
 if saved is not None:return saved
 if stage.startswith('B'):
  branch=stage[:2];old=[json.loads(p.read_text()) for p in (root/'trace').glob(f'*{config["current_sample_id"]}-{branch}*.json')]
  recovery=config.get('stage_recovery')
  if '-R' in stage:
   if not recovery or recovery.get('recovery_stage')!=stage:raise ValueError('explicit audited stage recovery required')
   proof=Path(recovery['proof_file'])
   if sha(proof)!=recovery['proof_sha256']:raise ValueError('stage recovery proof changed')
   verified=json.loads(proof.read_text())
   if verified.get('reason')=='isolated_tls_handshake_failure':raw=verify_tls_recovery(verified)
   else:
    original=Path(verified['original_response_file'])
    if sha(original)!=verified['original_response_sha256']:raise ValueError('original failed response changed')
    raw=json.loads(original.read_text())
   if sha(Path(verified['native_candidate_file']))!=verified['native_candidate_sha256']:raise ValueError('native recovery candidate changed')
   if verified.get('reason')=='truncated_wrong_output_contract':
    if not any(choice.get('finish_reason')=='length' for choice in raw.get('choices',[])):raise ValueError('recovery requires actual provider truncation evidence')
   elif verified.get('reason')=='isolated_tls_handshake_failure':pass
   elif verified.get('reason')=='malformed_json_control_marker':
    verify_malformed_control_reply(raw)
   elif verified.get('reason')=='invalid_verifier_schema' and stage[2]=='3':
    verify_invalid_verifier_reply(raw,verified['invalid_mandatory_fields'])
   elif verified.get('reason')=='native_proposal_review_contract' and stage[2]=='2':
    log=Path(verified['native_error_log'])
    if sha(log)!=verified['native_error_log_sha256']:raise ValueError('native rejection evidence changed')
    failure=json.loads(log.read_text())
    if failure.get('returncode')==0 or 'proposal_reviews must exactly partition proposal IDs' not in failure.get('stderr',''):raise ValueError('actual omitted-review native rejection required')
   else:raise ValueError('unsupported recovery; no blind retry')
   if stage.endswith('-R2'):
    previous=Path(verified['previous_recovery_response'])
    if sha(previous)!=verified['previous_recovery_response_sha256']:raise ValueError('previous actual recovery changed')
    previous_body=json.loads(previous.read_text());previous_text=previous_body['choices'][0]['message']['content'];previous_value,_=parse_model_object(previous_text)
    if verified.get('root_cause')=='incomplete_observation_partition_after_first_correction':
     catalog=Path(verified['proposal_catalog_file'])
     if sha(catalog)!=verified['proposal_catalog_sha256']:raise ValueError('proposal catalog changed')
     known={item['id'] for item in json.loads(catalog.read_text())['proposals']};actual={item['proposal_id'] for item in previous_value['proposal_reviews']}
     if not actual<known or sorted(known-actual)!=verified['only_missing_proposal_ids']:raise ValueError('R2 requires exact nonempty omitted subset; no replay of reviewed work')
    elif verified.get('root_cause')=='conflicting_planner_system_schema_in_recovery_prompt':
     if 'proposal_reviews' in previous_value or 'programs' not in previous_value:raise ValueError('R2 only allowed for proven conflicting-schema planner output')
    else:raise ValueError('specific second recovery root-cause proof required')
   elif not stage.endswith('-R1'):raise ValueError('bounded recovery limit reached')
   if any(row.get('stage')==stage for row in old):raise ValueError('no blind repeated recovery calls')
  elif len([row for row in old if '-R' not in row.get('stage','')])>=3:raise ValueError('normal three-request branch limit reached')
 row=lease._find(provider,financial_slot)
 record={'name':label,'sample_id':config['current_sample_id'],'stage':stage,'provider':provider,'model':pc['model'],'status':'request_started','request_id':row['request_id'],'body_sha256':digest,'started_utc':datetime.now(timezone.utc).isoformat(),'reused':False}
 write(path,record);render(root);started=time.monotonic()
 try:
  raw=send_once();response=root/'responses'/(label+'.json');write(response,raw)
  record.update(status='completed',ended_utc=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-started,response_file=str(response),response_sha256=sha(response),**usage(raw,pc));record['new_estimated_usd']=record['estimated_usd'];write(path,record);render(root)
  print('STAGE_COMPLETE',label,round(record['elapsed_seconds'],2),record['input_tokens'],record['output_tokens'],record['estimated_usd'],flush=True);return raw
 except BaseException as exc:
  record.update(status='failed_or_charge_unknown',ended_utc=datetime.now(timezone.utc).isoformat(),elapsed_seconds=time.monotonic()-started,error_type=type(exc).__name__,error=str(exc),new_estimated_usd=None);write(path,record);render(root);raise
