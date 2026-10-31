"""Automatic, auditable model execution. No network is performed at import time."""
import base64, hashlib, json, os, re, subprocess, sys, uuid
from pathlib import Path
PAUSE_FILE=Path(__file__).resolve().parent.parent/'output/formal-launch-20261029/provider-pause.json'

class AdmissionError(ValueError): pass
class ProviderHTTPError(RuntimeError):
    def __init__(self,status_code,detail):
        self.status_code=status_code
        super().__init__('provider HTTP '+str(status_code)+': '+str(detail))

def validate_verifier_output(report):
    for field in ('resolved_ids','unresolved_ids','not_required','new_required_findings','new_uncertain_findings','protected_regressions'):
        if not isinstance(report.get(field),list):raise ValueError('verifier schema requires array '+field+'; return the verifier acceptance schema, not a detector report or planner program list')

def dump(p,x):
    p=Path(p);p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(x,ensure_ascii=False,indent=2))
def clean_env():
    return {k:v for k,v in os.environ.items() if not any(s in k.upper() for s in ('KEY','TOKEN','SECRET','PASSWORD','ENV_FILE','PYTHONPATH'))}
def readonly_inline_png_projection(data,path):
    """Lossless read-only transport view; original remains native authority."""
    import io,xml.etree.ElementTree as ET
    from PIL import Image
    text=data.decode('utf-8')
    if 'data:image/png;base64,' not in text:return text,[],None
    tree=ET.fromstring(text)
    for node in tree.iter():
        for key,value in node.attrib.items():
            if key.rsplit('}',1)[-1] in ('href','src') and not value.startswith(('#','data:image/png;base64,')):
                raise AdmissionError('SVG dependency outside admitted inline PNG closure: '+str(path)+' href='+value)
    if re.search(r'@import|url\(\s*["\']?(?!#|data:image/png;base64,)',text,re.I):raise AdmissionError('SVG CSS dependency outside closure')
    pattern=re.compile(r'data:image/png;base64,([A-Za-z0-9+/=\s]+)')
    backings=[];extras=[]
    def replace(match):
        encoded=re.sub(r'\s','',match.group(1));image=base64.b64decode(encoded,validate=True)
        with Image.open(io.BytesIO(image)) as im:
            if im.format!='PNG':raise AdmissionError('inline PNG MIME mismatch')
            im.verify() # includes PNG chunk CRC verification
        sha=hashlib.sha256(image).hexdigest();marker='FIGFOX_READONLY_INLINE_PNG_'+str(len(backings))+'_'+sha
        backings.append((marker,match.group(0)));extras.append({'path':str(path)+'#inline-png-'+str(len(backings)-1),'sha256':sha,'bytes':len(image),'content':{'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(image).decode(),'detail':'high'}}})
        return marker
    projected=pattern.sub(replace,text);restored=projected
    for marker,original in backings:restored=restored.replace(marker,original)
    if restored.encode()!=data:raise AdmissionError('SVG projection inverse proof failed')
    if not backings:return text,[],None
    proof={'format':'readonly-lossless-inline-png-alias-v1','original_path':str(path),'original_sha256':hashlib.sha256(data).hexdigest(),'projected_sha256':hashlib.sha256(projected.encode()).hexdigest(),'inverse_verified':True,'inline_aliases':[{'marker':marker,'sha256':row['sha256'],'path':row['path']} for (marker,_),row in zip(backings,extras)],'authority':'read-only nonexecutable transport view; native always uses complete original SVG bytes'}
    return projected,extras,proof

def exact_text_root_views(content,root_prefix):
    marker='~FIGFOX_ROOT~/'
    if len(root_prefix)<64:return content,None
    suffix=0
    while any(marker in part.get('text','') for part in content if part.get('type')=='text'):
        suffix+=1;marker='~FIGFOX_ROOT_'+str(suffix)+'~/'
    encoded=[];changed=False
    for part in content:
        if part.get('type')!='text':encoded.append(part);continue
        text=part['text']
        if marker in text:raise AdmissionError('reserved root marker collision')
        projected=text.replace(root_prefix,marker)
        if projected.replace(marker,root_prefix)!=text:raise AdmissionError('text root inverse proof failed')
        changed|=projected!=text;encoded.append({**part,'text':projected})
    notice={'type':'text','text':'LOSSLESS ABSOLUTE-PATH ALIAS: in every following text block, replace literal '+marker+' with '+root_prefix+' before interpreting evidence paths or source text. No other bytes differ; inverse equality verified. Native originals are unchanged.'} if changed else None
    return encoded,notice

def exact_path_trie_views(document):
    key='$figfox_exact_path_trie';terminal='\0'
    def paths(tree):
        result=[]
        def walk(node,prefix):
            for segment,child in node.items():
                if segment==terminal:result.append('/'+'/'.join(prefix))
                else:walk(child,prefix+[segment])
        walk(tree,[]);return result
    def encode(value):
        if isinstance(value,dict):
            if key in value:raise AdmissionError('reserved path trie collision')
            return {k:encode(v) for k,v in value.items()}
        if isinstance(value,list):
            if len(value)>=100 and all(isinstance(v,str) and v.startswith('/') and terminal not in v for v in value):
                tree={}
                for path in value:
                    node=tree
                    for part in path[1:].split('/'):node=node.setdefault(part,{})
                    node[terminal]=True
                encoded={key:tree}
                if paths(tree)==value and len(json.dumps(encoded))<len(json.dumps(value)):return encoded
            return [encode(v) for v in value]
        return value
    def decode(value):
        if isinstance(value,dict):
            if list(value)==[key]:return paths(value[key])
            return {k:decode(v) for k,v in value.items()}
        return [decode(v) for v in value] if isinstance(value,list) else value
    encoded=encode(document)
    if decode(encoded)!=document:raise AdmissionError('ordered path trie inverse proof failed')
    return encoded

def exact_path_list_views(document):
    """Exact ordered path-index delta view, never a filtered index."""
    key='$figfox_exact_path_deltas'
    def encode(value):
        if isinstance(value,dict):
            if key in value:raise AdmissionError('reserved path delta collision')
            return {k:encode(v) for k,v in value.items()}
        if isinstance(value,list):
            if len(value)>=100 and all(isinstance(v,str) and v.startswith('/') for v in value):
                previous='';deltas=[]
                for path in value:
                    common=0
                    while common<min(len(previous),len(path)) and previous[common]==path[common]:common+=1
                    deltas.append([common,path[common:]]);previous=path
                encoded={key:deltas}
                if len(json.dumps(encoded))<len(json.dumps(value)):return encoded
            return [encode(v) for v in value]
        return value
    def decode(value):
        if isinstance(value,dict):
            if list(value)==[key]:
                previous='';paths=[]
                for common,suffix in value[key]:previous=previous[:common]+suffix;paths.append(previous)
                return paths
            return {k:decode(v) for k,v in value.items()}
        return [decode(v) for v in value] if isinstance(value,list) else value
    encoded=encode(document)
    if decode(encoded)!=document:raise AdmissionError('ordered path index inverse proof failed')
    return encoded

def exact_string_prefix_views(documents):
    """Reversible aliases for repeated absolute paths/JSON pointer prefixes."""
    from collections import Counter
    counts=Counter();strings=[];marker='~FP'
    def visit(value):
        if isinstance(value,str):
            if value.startswith(marker):raise AdmissionError('reserved evidence path prefix collision')
            if value.startswith('/') and len(value)>=24:
                strings.append(value)
                for index,char in enumerate(value):
                    if char=='/' and index>=16:counts[value[:index+1]]+=1
        elif isinstance(value,dict):
            for child in value.values():visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(documents);candidates={prefix for prefix,n in counts.items() if n>=4};selected={}
    for value in strings:
        matches=[value[:i+1] for i,ch in enumerate(value) if ch=='/' and value[:i+1] in candidates]
        if matches:selected[value]=max(matches,key=len)
    used=Counter(selected.values());prefixes=[p for p,n in used.items() if n>=4 and (len(p)-12)*n>len(p)+20]
    mapping={marker+str(i)+'~':p for i,p in enumerate(sorted(prefixes))};reverse={v:k for k,v in mapping.items()}
    def transform(value,decode=False):
        if isinstance(value,str):
            if decode:
                for key,prefix in mapping.items():
                    if value.startswith(key):return prefix+value[len(key):]
            elif selected.get(value) in reverse:
                prefix=selected[value];return reverse[prefix]+value[len(prefix):]
            return value
        if isinstance(value,dict):return {k:transform(v,decode) for k,v in value.items()}
        return [transform(v,decode) for v in value] if isinstance(value,list) else value
    encoded=transform(documents)
    if transform(encoded,True)!=documents:raise AdmissionError('path prefix inverse proof failed')
    return encoded,mapping

def exact_json_key_views(documents):
    from collections import Counter
    counts=Counter()
    def visit(value):
        if isinstance(value,dict):
            for key,child in value.items():
                if key.startswith('~K'):raise AdmissionError('reserved JSON key alias collision')
                if len(key)>12 and key!='$figfox_exact_json_ref':counts[key]+=1
                visit(child)
        elif isinstance(value,list):
            for child in value:visit(child)
    visit(documents);mapping={'~K'+str(i):key for i,key in enumerate(sorted(key for key,n in counts.items() if n>3))};reverse={v:k for k,v in mapping.items()}
    def transform(value,keys):
        if isinstance(value,dict):return {keys.get(k,k):transform(v,keys) for k,v in value.items()}
        return [transform(v,keys) for v in value] if isinstance(value,list) else value
    encoded=transform(documents,reverse)
    if transform(encoded,mapping)!=documents:raise AdmissionError('JSON key transport inverse proof failed')
    return encoded,mapping

def exact_json_views(documents):
    """Reversible common-subtree transport encoding; every unique value is inline."""
    from collections import Counter
    key='$figfox_exact_json_ref';counts=Counter();identities={}
    def fingerprint(value):
        if isinstance(value,dict) and key in value:raise AdmissionError('reserved JSON transport reference collision')
        if isinstance(value,(dict,list,str)):
            if not isinstance(value,str):
                for child in (value.values() if isinstance(value,dict) else value):fingerprint(child)
            raw=json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'))
            if len(raw)>=128:
                digest=hashlib.sha256(raw.encode()).hexdigest()[:16];counts[digest]+=1;identities[id(value)]=digest
    for document in documents:fingerprint(document)
    table={}
    def encode(value,inline=False):
        digest=identities.get(id(value)) if isinstance(value,(dict,list,str)) else None
        if digest and counts[digest]>1 and not inline:
            if digest not in table:table[digest]=encode(value,True)
            return {key:digest}
        if isinstance(value,dict):return {k:encode(v) for k,v in value.items()}
        return [encode(v) for v in value] if isinstance(value,list) else value
    views=[encode(document) for document in documents]
    def expand(value):
        if isinstance(value,dict):
            if list(value)==[key]:return expand(table[value[key]])
            return {k:expand(v) for k,v in value.items()}
        return [expand(v) for v in value] if isinstance(value,list) else value
    if [expand(view) for view in views]!=documents:raise AdmissionError('exact JSON transport inverse proof failed')
    return views,table

def exact_xml_column_views(documents):
    copied=json.loads(json.dumps(documents))
    for view in copied:
        if not isinstance(view,dict) or view.get('format')!='lossless-readonly-xml-attribute-templates-v1':continue
        segments=[];original=view['segments'];index=0
        while index<len(original):
            segment=original[index]
            if isinstance(segment,str):segments.append(segment);index+=1;continue
            key=segment[0];rows=[]
            while index<len(original) and isinstance(original[index],list) and original[index][0]==key:
                rows.append(original[index][1]);index+=1
            columns=[]
            for column in zip(*rows):
                column=list(column);rle=[]
                for value in column:
                    if rle and rle[-1][1]==value:rle[-1][0]+=1
                    else:rle.append([1,value])
                encoded={'rle':rle}
                columns.append(encoded if len(json.dumps(encoded))<len(json.dumps(column)) else column)
            segments.append([key,{'rows':len(rows),'columns':columns}])
        restored=[]
        for segment in segments:
            if isinstance(segment,str):restored.append(segment);continue
            key,run=segment;columns=[([value for count,value in column['rle'] for _ in range(count)] if isinstance(column,dict) else column) for column in run['columns']]
            for i in range(run['rows']):restored.append([key,[column[i] for column in columns]])
        if restored!=original:raise AdmissionError('XML ordered column inverse proof failed')
        view['segments']=segments
        view['decode']='First expand each [template_id,{rows:N,columns:[...]}] segment into N ordinary [template_id,values] segments in order. A column is an exact value array, or {rle:[[count,value],...]} which repeats each value count times. Row i uses column[i] from each expanded column. Then: '+view['decode']
    return copied

def exact_xml_atom_views(documents):
    from collections import Counter
    copied=json.loads(json.dumps(documents));counts=Counter()
    views=[d for d in copied if isinstance(d,dict) and d.get('format')=='lossless-readonly-xml-attribute-templates-v1']
    for view in views:
        for segment in view['segments']:
            if isinstance(segment,list):counts.update(value for value in segment[1] if len(value)>=8)
    table=sorted(value for value,count in counts.items() if count>=2);lookup={value:i for i,value in enumerate(table)}
    for view in views:
        view['attribute_value_atoms']=table
        for segment in view['segments']:
            if isinstance(segment,list):segment[1][:]=[lookup.get(value,value) for value in segment[1]]
    restored=json.loads(json.dumps(copied))
    for view in restored:
        if not isinstance(view,dict) or view.get('format')!='lossless-readonly-xml-attribute-templates-v1':continue
        atoms=view.pop('attribute_value_atoms')
        for segment in view['segments']:
            if isinstance(segment,list):segment[1][:]=[atoms[value] if type(value)is int else value for value in segment[1]]
    if restored!=documents:raise AdmissionError('XML attribute atom inverse proof failed')
    return copied

def exact_xml_view(text):
    """Lexical attribute templates, preserving every original XML character."""
    tags=re.compile(r'''<[A-Za-z_:](?:[^>"']|"[^"]*"|'[^']*')*>''')
    attributes=re.compile(r'''(?:"([^"]*)"|'([^']*)')''')
    templates={};lookup={};segments=[];offset=0
    for match in tags.finditer(text):
        if match.start()>offset:segments.append(text[offset:match.start()])
        tag=match.group();parts=[];values=[];cursor=0
        for attribute in attributes.finditer(tag):
            start,end=attribute.span(1 if attribute.group(1) is not None else 2)
            parts.append(tag[cursor:start]);values.append(tag[start:end]);cursor=end
        parts.append(tag[cursor:]);signature=tuple(parts)
        key=lookup.get(signature)
        if key is None:
            key='X'+str(len(templates));lookup[signature]=key;templates[key]=parts
        segments.append([key,values]);offset=match.end()
    if offset<len(text):segments.append(text[offset:])
    restored=''.join(segment if isinstance(segment,str) else ''.join(part+(segment[1][i] if i<len(segment[1]) else '') for i,part in enumerate(templates[segment[0]])) for segment in segments)
    if restored!=text:raise AdmissionError('XML lexical transport inverse proof failed')
    return {'format':'lossless-readonly-xml-attribute-templates-v1','decode':'If attribute_value_atoms is present, replace every integer in segment values by the exact string at that index in attribute_value_atoms first. Concatenate segments in order. Literal strings are unchanged. For each [template_id,values], interleave templates[template_id][i] with values[i], ending with the last template part. This reconstructs every original XML character; native uses unchanged original bytes.','original_sha256':hashlib.sha256(text.encode()).hexdigest(),'templates':templates,'segments':segments}

def inventory(paths):
    result=[];seen=set()
    for raw in paths:
        p=Path(raw)
        if not p.exists(): raise AdmissionError('missing allowed evidence: '+str(p))
        entries=sorted(p.rglob('*')) if p.is_dir() else [p]
        for f in entries:
            if f.is_symlink(): raise AdmissionError('symlink evidence forbidden: '+str(f))
            if not f.is_file() or str(f) in seen: continue
            seen.add(str(f));data=f.read_bytes()
            if f.suffix.lower()=='.png':
                content={'type':'image_url','image_url':{'url':'data:image/png;base64,'+base64.b64encode(data).decode(),'detail':'high'}}
            else:
                try: content={'type':'text','text':data.decode('utf-8')}
                except UnicodeDecodeError: raise AdmissionError('unsupported evidence bytes: '+str(f))
            if f.suffix.lower()=='.svg':
                try:projected,extras,proof=readonly_inline_png_projection(data,f)
                except AdmissionError:
                    # Unsupported closure retains every original SVG byte; never claim projected admission.
                    projected,extras,proof=data.decode('utf-8'),[],None
                if proof:
                    content={'type':'text','text':'READ-ONLY NONEXECUTABLE SVG VIEW; complete original retained at '+str(f)+'; inverse proof '+json.dumps(proof)+'\n'+projected};result.extend(extras)
            xml_transport=False
            if f.suffix.lower()=='.svg' and len(content.get('text',''))>200000:
                view=exact_xml_view(content['text']);encoded=json.dumps(view,ensure_ascii=False,separators=(',',':'))
                if len(encoded)<len(content['text']):
                    content={'type':'text','text':encoded};xml_transport=True
            result.append({'path':str(f),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data),'content':content,'xml_transport':xml_transport})
    return result

def body_for(pc,messages,tools=None):
    budget=pc.get('max_output_tokens',64000)
    if pc['protocol']=='responses':
        inputs=[]
        for m in messages:
            if m.get('role')=='tool': inputs.append({'type':'function_call_output','call_id':m['tool_call_id'],'output':m['content']});continue
            if m.get('_response_items') is not None:inputs.extend(m['_response_items']);continue
            content=m['content'];content=[{'type':'text','text':content}] if isinstance(content,str) else content
            inputs.append({'role':m['role'],'content':[{'type':'input_text','text':x['text']} if x['type']=='text' else {'type':'input_image','image_url':x['image_url']['url'],'detail':'high'} for x in content]})
        body={'model':pc['model'],'input':inputs,'max_output_tokens':budget}
        if tools:body['tools']=[{'type':'function',**t['function']} for t in tools]
    elif pc['protocol']=='chat_completions':
        body={'model':pc['model'],'messages':[{k:v for k,v in m.items() if not k.startswith('_') and (tools or k!='reasoning_content')} for m in messages],'max_tokens':budget}
        if tools:body['tools']=tools
        if pc.get('json_output') is True and not tools:body['response_format']={'type':'json_object'}
    else:raise AdmissionError('explicit protocol must be responses or chat_completions')
    extra=pc.get('extra_body',{})
    permitted={'reasoning'} if pc['protocol']=='responses' else {'thinking','reasoning_effort'}
    if not isinstance(extra,dict) or set(extra)-permitted:raise AdmissionError('extra_body contains forbidden protocol override')
    body.update(extra)
    return body

def admit(pc,body):
    from budget import estimate_input_tokens
    if pc.get('max_request_bytes') is not None and len(json.dumps(body).encode())>pc['max_request_bytes']:raise AdmissionError('complete request exceeds HTTP body limit')
    canonical=pc.get('context_tokens',pc.get('context_window'))
    if canonical is None:raise AdmissionError('explicit context_tokens required')
    if 'context_tokens' in pc and 'context_window' in pc and pc['context_tokens']!=pc['context_window']:raise AdmissionError('conflicting context aliases')
    needed=estimate_input_tokens(body,pc)
    if needed>pc.get('max_input_tokens',canonical-pc.get('max_output_tokens',64000)) or needed+pc.get('max_output_tokens',64000)>canonical:raise AdmissionError('complete request exceeds context/input bound')

def slot(config,suffix):
    if config.get('financial_slot_prefix'):suffix=config['financial_slot_prefix']+'/'+suffix
    return config['current_sample_id']+'/'+config['current_cell']+'/'+suffix

def transport(pc,body,request_id):
    payload={'provider':pc,'body':body,'request_id':request_id}
    proc=subprocess.run([sys.executable,'-B',str(Path(__file__).resolve()),'--transport'],input=json.dumps(payload),text=True,capture_output=True,env=dict(os.environ),timeout=pc.get('timeout_seconds',600))
    if proc.returncode:
        try:error=json.loads(proc.stdout)
        except ValueError:error={}
        if error.get('transport_error')=='HTTP':raise ProviderHTTPError(error.get('status'),error.get('detail',''))
        dump(PAUSE_FILE.parent/'transport-exits'/(str(uuid.UUID(request_id))+'.json'),{'request_id':request_id,'returncode':proc.returncode,'stderr':getattr(proc,'stderr','')[-4000:],'stdout':proc.stdout[-1200:]})
        raise RuntimeError('isolated provider transport failed: '+proc.stdout[:1200])
    return json.loads(proc.stdout)

def request(config,provider,slot,messages,lease,folder,tools=None):
    if config.get('business_stage'):
        import bounded_trace
        return bounded_trace.invoke(config,provider,slot,messages,lease,folder,tools,lambda:_request_once(config,provider,slot,messages,lease,folder,tools))
    return _request_once(config,provider,slot,messages,lease,folder,tools)

def _request_once(config,provider,slot,messages,lease,folder,tools=None):
    pc=config['providers'][provider];body=body_for(pc,messages,tools);admit(pc,body)
    if hasattr(lease,'check_context'):lease.check_context(provider,body)
    attempt=uuid.uuid4().hex;dump(Path(folder)/(attempt+'-request.json'),{'attemptUUID':attempt,'provider':provider,'slot':slot,'body':body})
    send=lambda request_id:transport(pc,body,request_id)
    # Explicit test hook never selected by production configuration files.
    if callable(config.get('_mock_send')):send=lambda request_id:config['_mock_send'](provider,body,request_id)
    raw=lease.send(provider,slot,body,send);dump(Path(folder)/(attempt+'-response.json'),{'attemptUUID':attempt,'raw':raw});return raw

def extract(raw,protocol):
    if protocol=='responses':
        if raw.get('status') not in (None,'completed'):raise AdmissionError('provider response incomplete')
        items=raw.get('output',[]);text=''.join(c.get('text','') for x in items if x.get('type')=='message' for c in x.get('content',[]) if c.get('type')=='output_text')
        calls=[{'id':x['call_id'],'function':{'name':x['name'],'arguments':x['arguments']}} for x in items if x.get('type')=='function_call']
        return text,calls,{'role':'assistant','content':text,'_response_items':items}
    choice=raw['choices'][0]
    if choice.get('finish_reason') not in ('stop','tool_calls'):raise AdmissionError('provider output truncated/incomplete')
    msg=choice['message'];return msg.get('content') or '',msg.get('tool_calls',[]),msg

def _keyless(command,config):
    return subprocess.run(command,env=clean_env(),capture_output=True,text=True,check=True,timeout=config.get('native_timeout_seconds',7200))

def build_role_packet(prompt):
    """Required native evidence plus a closed, hashed optional file catalog."""
    paths=[]
    for line in prompt.splitlines():
        for prefix in ('Allowed neutral inputs: ','Allowed current stage inputs: ','Read every listed enabled authoritative source and supplied method manual: '):
            if line.startswith(prefix):paths.extend(line[len(prefix):].split(', '))
    if not paths:raise AdmissionError('actual brief has no closed evidence inventory')
    required=[];frames=[]
    for raw in paths:
        p=Path(raw)
        if not p.is_dir():required.append(p);continue
        if p.name in ('checkpoint','candidate'):
            required.extend(p/name for name in ('original.png','current.png','current.svg','public.svg') if (p/name).is_file())
            pack=p/'pack/pack.json'
            if not pack.is_file():raise AdmissionError('required native pack missing')
            required.append(pack);catalog=json.loads(pack.read_text())
            for frame in catalog['frames']:
                pair=Path(frame['pair']);pair=pair if pair.is_absolute() else pack.parent/pair
                if pair.resolve().parent!=pack.parent.resolve() or not pair.is_file():raise AdmissionError('required frame pair outside actual pack')
                required.append(pair);frames.append({'frame_id':frame['frame_id'],'pair':str(pair)})
        elif p.name=='sam':required.extend(f for f in p.rglob('*') if f.is_file())
        else:
            # Prior-round plans/feedback/queues/candidates are mandatory. Internal native
            # transaction traces remain hash-closed optional evidence, not repeated attachments.
            required.extend(f for f in p.rglob('*') if f.is_file() and not {'native-stage','native'}.intersection(f.relative_to(p).parts[:-1]) and f.suffix in ('.json','.md','.txt') and f.name not in ('bounds.json','native-result.json'))
    all_files={}
    for raw in paths:
        p=Path(raw)
        for f in (sorted(p.rglob('*')) if p.is_dir() else [p]):
            if f.is_symlink():raise AdmissionError('symlink evidence forbidden')
            if f.is_file():
                data=f.read_bytes();all_files[str(f)]={'path':str(f),'sha256':hashlib.sha256(data).hexdigest(),'bytes':len(data)}
    required_paths={str(p) for p in required};optional={k:v for k,v in all_files.items() if k not in required_paths}
    for i,(path,row) in enumerate(sorted(optional.items())):row['id']='E'+str(i)
    manifest={'allowed_roots':paths,'required_files':sorted(required_paths),'required_frames':frames,'optional_files':list(optional.values())}
    manifest_sha=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode()).hexdigest()
    evidence=inventory(required);unique={};aliases={}
    for item in evidence:aliases.setdefault(item['sha256'],[]).append(item['path']);unique.setdefault(item['sha256'],item)
    # JSON whitespace is lossless parsed content; original exact bytes remain in immutable backing.
    for item in unique.values():
        if item['path'].endswith('.json') and item['content']['type']=='text':item['content']['text']=json.dumps(json.loads(item['content']['text']),ensure_ascii=False,separators=(',',':'))
    json_items=[item for item in unique.values() if (item['path'].endswith('.json') or item.get('xml_transport')) and item['content']['type']=='text']
    originals=[json.loads(item['content']['text']) for item in json_items]
    views,shared=exact_json_views(exact_path_list_views(exact_path_trie_views(exact_xml_column_views(exact_xml_atom_views(originals)))))
    key_bundle,key_aliases=exact_json_key_views([views,shared]);views,shared=key_bundle
    prefix_bundle,path_prefixes=exact_string_prefix_views([views,shared]);views,shared=prefix_bundle
    if (shared or key_aliases or path_prefixes) and len(json.dumps([views,shared,key_aliases,path_prefixes],ensure_ascii=False))<len(json.dumps(originals,ensure_ascii=False)):
        for item,view in zip(json_items,views):item['content']['text']=json.dumps(view,ensure_ascii=False,separators=(',',':'))
        shared_content={'type':'text','text':'LOSSLESS READ-ONLY JSON TRANSPORT TABLE. Every object with the sole key $figfox_exact_json_ref expands recursively to the exact value keyed by its content ID below. First expand any string beginning with a path_prefixes marker by replacing that marker with its exact prefix; no other string bytes change. Then recursively expand every dictionary field key named in field_key_aliases to its exact original name, in both documents and shared_values; then recursively expand value references using shared_values. Expand these references when reading required JSON evidence. After expanding strings, field keys and shared references, expand each object whose sole key is $figfox_exact_path_deltas into the original ordered string list: start previous="", and for each [common,suffix] set previous=previous[:common]+suffix and append it. Then expand any sole-key $figfox_exact_path_trie object: traverse its dictionary in insertion order; each normal key appends a slash-separated path segment, and a \\u0000 key emits the current full path starting with /. Preserve traversal order. Every original path is retained in order. All unique values are attached in full; no measurements or judgments were removed. Inverse equality verified for every original JSON document; original files and hashes remain native authority.\n'+json.dumps({'field_key_aliases':key_aliases,'path_prefixes':path_prefixes,'shared_values':shared},ensure_ascii=False,separators=(',',':'))}
    else:shared_content=None
    notice={'closed_catalog_sha256':manifest_sha,'allowed_roots':paths,'optional_file_count':len(optional),'required_frame_count':len(frames),'optional_access':'read_evidence list (paged exact paths/opaque IDs) or read exact path/ID, JSON pointer or byte page. At most two read calls. All unrequested files remain accessible in this closed catalog; no directory escape. Required pair images include every exact frame ID in supplied pack.json.','alias_index':{k:v for k,v in aliases.items() if len(v)>1}}
    content=[{'type':'text','text':prompt+'\nTransport evidence closure: '+json.dumps(notice,separators=(',',':'))}]
    content += [y for item in unique.values() for y in ({'type':'text','text':'Required evidence '+item['path']},item['content'])]
    if shared_content:content.append(shared_content)
    root_prefix=next((path.split('/cell/',1)[0]+'/cell/' for path in paths if '/cell/' in path),'')
    content,root_notice=exact_text_root_views(content,root_prefix)
    if root_notice:content.insert(0,root_notice)
    for i,path in enumerate(sorted(required_paths)):
        if path in all_files:all_files[path]['id']='R'+str(i)
    return [{'role':'user','content':content}],manifest,all_files

def read_evidence(catalog,args):
    rows=sorted(catalog.values(),key=lambda x:x['id']);action=args.get('action')
    if action=='list':
        if args.get('prefix') is not None:rows=[row for row in rows if row['path'].startswith(args['prefix'])]
        start=args.get('offset',0)
        if type(start)is not int or start<0:raise AdmissionError('invalid catalog page')
        page=rows[start:start+100];return {'files':page,'next_offset':start+100 if start+100<len(rows) else None,'total':len(rows)},None
    if action!='read':raise AdmissionError('unknown evidence action')
    matches=[row for row in rows if args.get('file') in (row['id'],row['path'])]
    if len(matches)!=1:raise AdmissionError('file outside closed optional catalog')
    row=matches[0];data=Path(row['path']).read_bytes()
    if hashlib.sha256(data).hexdigest()!=row['sha256']:raise AdmissionError('immutable optional evidence changed')
    if row['path'].lower().endswith('.png'):
        return {'file':row,'image':'complete exact PNG attached'},inventory([row['path']])[0]['content']
    if args.get('pointer') is not None:
        value=json.loads(data);pointer=args['pointer']
        if pointer and not pointer.startswith('/'):raise AdmissionError('invalid JSON pointer')
        try:
            for part in pointer.split('/')[1:] if pointer else []:
                key=part.replace('~1','/').replace('~0','~');value=value[int(key)] if isinstance(value,list) else value[key]
        except (KeyError,IndexError,TypeError,ValueError) as exc:raise AdmissionError('invalid JSON pointer lookup: '+str(exc)) from exc
        return {'file':row,'pointer':pointer,'value':value,'complete':True},None
    start=args.get('offset',0)
    if type(start)is not int or start<0:raise AdmissionError('invalid byte page')
    page=data[start:start+32768]
    return {'file':row,'byte_offset':start,'bytes_base64':base64.b64encode(page).decode(),'encoding':'UTF8 bytes in base64; exact page','next_offset':start+len(page) if start+len(page)<len(data) else None,'total_bytes':len(data)},None

def run_role(cell_root,run,role,round_number,config,lease):
    root=Path(cell_root).resolve();tag=role+(f'-{round_number}' if round_number else '');job=root/'runs'/run/'jobs'/tag
    prompt=job/'dispatch-prompt.md';python=config.get('native_python',sys.executable)
    if not prompt.exists():
        cmd=[python,'-B',str(root/'brief.py'),run,role,'--root',str(root)]
        if round_number:cmd+=['--round',str(round_number)]
        _keyless(cmd,config)
    text=prompt.read_text();messages,manifest,catalog=build_role_packet(text);dump(job/'api-evidence-inventory.json',manifest)
    if role=='verifier' and config.get('verifier_schema_recovery'):
        messages.append({'role':'user','content':'An earlier unaccepted verifier receipt used the wrong role schema and failed native acceptance. Its immutable provenance is '+json.dumps(config['verifier_schema_recovery'])+'. Independently verify the same existing candidate using all attached evidence and the original verifier contract. Return the complete verifier schema including all six disposition arrays. Preserve uncertainty and actual failures; do not infer resolved IDs or a pass from this recovery instruction. The previous failed bytes and their costs remain preserved.'})
    read_tool={'type':'function','function':{'name':'read_evidence','description':'Read only closed optional evidence. At most two calls. list pages are 100 rows; file byte pages 32768 bytes with explicit next offset. JSON pointer returns complete value.','parameters':{'type':'object','properties':{'action':{'enum':['list','read']},'file':{'type':'string'},'offset':{'type':'integer'},'pointer':{'type':'string'},'prefix':{'type':'string'}},'required':['action'],'additionalProperties':False}}}
    tools=[read_tool]
    if role!='verifier':tools.append({'type':'function','function':{'name':'draft_check','description':'Read-only actual native flow draft check. At most twice.','parameters':{'type':'object','properties':{'draft_json':{'type':'string'}},'required':['draft_json'],'additionalProperties':False}}})
    provider=config['role_provider'][role]
    if config['providers'][provider]['max_output_tokens']!=64000:raise AdmissionError('role output budget must remain 64000')
    protocol=config['providers'][provider]['protocol'];checks=0;reads=0;force_final=False;max_turns=3 if role=='verifier' else 5
    native_final_check=(root/'flow.py').is_file() and role in ('main','semantic','planner');optional_checks=1 if native_final_check else 2;last_validated_sha=None
    if native_final_check:
        role_folder=root/'runs'/run/('detection/'+role if round_number is None else 'round-'+str(round_number)+'/'+role)
        audit_folder=role_folder/('plan-checks' if role=='planner' else 'report-checks');prior_checks=sorted(audit_folder.glob('*/receipt.json'));checks=len(prior_checks)
        state_file=root/'runs'/run/'state.json'
        for receipt in prior_checks:
            saved=json.loads(receipt.read_text());validation=saved.get('result',{})
            if saved.get('state_sha256')==hashlib.sha256(state_file.read_bytes()).hexdigest() and not str(validation.get('status','')).startswith('invalid'):
                candidate=Path(saved['draft'])
                if candidate.parent==job and candidate.is_file() and not candidate.is_symlink() and hashlib.sha256(candidate.read_bytes()).hexdigest()==saved.get('draft_sha256'):
                    last_validated_sha=saved['draft_sha256'];messages.append({'role':'user','content':'Read-only recovery context: this same role previously produced the following draft, validated against the unchanged native state. It has not been submitted or accepted. Return it only if still appropriate; all original duties and evidence remain authoritative.\n'+candidate.read_text()})
    for turn in range(max_turns):
        active_tools=[t for t in tools if (t['function']['name']=='read_evidence' and reads<2) or (t['function']['name']=='draft_check' and checks<optional_checks)]
        if force_final or turn==max_turns-1:active_tools=[]
        financial_slot=slot(config,role+('/ROUND'+str(round_number) if round_number else '')+'/TURN'+str(turn))
        try:raw=request(config,provider,financial_slot,messages,lease,job/'api',active_tools)
        except AdmissionError as exc:
            if 'context/input bound' not in str(exc) or not active_tools:raise
            force_final=True;messages.append({'role':'user','content':'The tool conversation reaches the context envelope. Return the final single JSON object now using all original attached evidence; no further tool calls. No evidence has been removed.'});continue
        if protocol=='chat_completions' and raw.get('choices',[{}])[0].get('finish_reason')=='length':
            force_final=True;messages.append({'role':'user','content':'The preceding provider response was truncated and was not accepted or executed. Return one complete concise JSON object in the original schema, without prose or further tool calls. Keep every required finding and evidence binding.'});continue
        final,calls,assistant=extract(raw,protocol)
        if not calls:
            try:
                parsed=json.loads(final)
                if not isinstance(parsed,dict):raise ValueError('final response must be one JSON object')
                if role=='verifier' and (root/'flow.py').is_file():validate_verifier_output(parsed)
            except ValueError as exc:
                messages.extend([assistant,{'role':'user','content':'Protocol validation rejected the final response: '+str(exc)+'. Return exactly one complete JSON object matching the original role schema. No prose, Markdown or textual tool syntax. Use actual tool_calls when requesting a tool. Existing evidence and role duties remain unchanged.'}]);continue
            final_sha=hashlib.sha256(final.encode()).hexdigest()
            if native_final_check and final_sha!=last_validated_sha:
                if checks>=2:
                    messages.extend([assistant,{'role':'user','content':'Native validation budget is exhausted and these final bytes have not passed the native contract. Return the exact previously validated final JSON if available; do not invent new evidence hashes or alter tracked issue objects.'}]);continue
                draft=job/f'api-final-check-{checks}.json';draft.write_bytes(final.encode());checks+=1
                cmd=[python,'-B',str(root/'flow.py'),'--root',str(root),'check-plan' if role=='planner' else 'check-report',run]
                cmd+= [str(round_number)] if role=='planner' else [role];cmd += [str(draft)]
                checked=subprocess.run(cmd,env=clean_env(),capture_output=True,text=True,timeout=config.get('check_timeout_seconds',120))
                try:validation=json.loads(checked.stdout)
                except ValueError:validation={'status':'invalid_native_response','stderr':checked.stderr}
                dump(job/f'api-final-check-{checks-1}-receipt.json',{'returncode':checked.returncode,'result':validation,'draft_sha256':final_sha})
                if checked.returncode or str(validation.get('status','')).startswith('invalid'):
                    messages.extend([assistant,{'role':'user','content':'The actual native validator rejected this final JSON: '+json.dumps(validation)+'. Correct the report/plan under the original schema. Preserve exact source evidence hashes and tracked issue objects; do not weaken any checks.'}]);continue
                last_validated_sha=final_sha
            destination=job/'agent-output.json';destination.write_bytes(final.encode('utf-8'));return destination
        messages.append(assistant)
        image_results=[]
        for call in calls:
            args=json.loads(call['function']['arguments'])
            if call['function']['name']=='read_evidence':
                reads+=1
                if reads>2:answer,image={'error':'read call limit reached; use evidence already attached'},None
                else:
                    try:answer,image=read_evidence(catalog,args)
                    except AdmissionError as exc:
                        if not any(x in str(exc) for x in ('file outside closed optional catalog','invalid JSON pointer','invalid catalog page','invalid byte page','unknown evidence action')):raise
                        answer,image={'error':str(exc),'guidance':'Access denied. Required evidence is already attached with exact paths. Only exact catalog paths/IDs may be read; no data outside the closure was accessed.'},None
                messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(answer)})
                if image:image_results.extend([{'type':'text','text':'Exact read_evidence image result for tool '+call['id']},image])
                continue
            if call['function']['name']!='draft_check' or role=='verifier' or checks>=optional_checks:
                messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps({'error':'tool unavailable or validation-call limit reached','guidance':'No tool was executed. Submit the final JSON using the original schema and current validation feedback.'})});continue
            draft=job/f'api-draft-{checks}.json';draft.write_bytes(args['draft_json'].encode());checks+=1
            cmd=[python,'-B',str(root/'flow.py'),'--root',str(root),'check-plan' if role=='planner' else 'check-report',run]
            cmd+= [str(round_number)] if role=='planner' else [role];cmd += [str(draft)]
            result=subprocess.run(cmd,env=clean_env(),capture_output=True,text=True,timeout=config.get('check_timeout_seconds',120))
            try:
                validation=json.loads(result.stdout)
                if result.returncode==0 and not str(validation.get('status','')).startswith('invalid'):last_validated_sha=hashlib.sha256(args['draft_json'].encode()).hexdigest()
            except ValueError:pass
            messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps({'returncode':result.returncode,'stdout':result.stdout,'stderr':result.stderr})})
        if image_results:messages.append({'role':'user','content':image_results})
    raise AdmissionError('no final output within bounded continuations')

def run_first(spec,config,lease):
    out=Path(spec['output_root']).resolve();out.mkdir(parents=True,exist_ok=False);dump(out/'spec.json',spec)
    stderr=(out/'native-stderr.log').open('w')
    p=subprocess.Popen([config.get('native_python',sys.executable),'-B',str(Path(__file__).resolve()),'--first-child',str(out/'spec.json')],env=clean_env(),stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,text=True)
    calls=0
    try:
        for line in p.stdout:
            if not line.startswith('LIVE_CALLBACK:'):continue
            calls+=1
            if calls>1:raise AdmissionError('first stage requested more than once')
            payload=json.loads(line.split(':',1)[1]);evidence=inventory(payload['images'])
            messages=[{'role':'user','content':[{'type':'text','text':payload['prompt']}]+[x['content'] for x in evidence]}]
            provider=config.get('first_provider','openai')
            if config['providers'][provider]['protocol']!='responses':raise AdmissionError('first stage requires OpenAI Responses')
            raw=request(config,provider,slot(config,'first/TURN0'),messages,lease,out/'api');text,tools,_=extract(raw,'responses')
            if tools:raise AdmissionError('first stage tool calls forbidden')
            p.stdin.write(json.dumps({'text':text})+'\n');p.stdin.flush()
        if p.wait()!=0 or calls!=1:raise RuntimeError('native first stage failed; inspect preserved native stderr')
    except BaseException:p.kill();p.wait();raise
    finally:
        p.stdin.close();p.stdout.close();stderr.close()
    result=json.loads((out/'result.json').read_text());return result

def score_cell(original,final_svg,final_png,registry,cell_output,config,lease):
    out=Path(cell_output)/'scoring';out.mkdir(parents=True,exist_ok=False)
    registry_rows=json.loads(Path(registry).read_text())
    if not isinstance(registry_rows,list) or len(registry_rows)!=18 or {x.get('id') for x in registry_rows}!={f'D{i:02d}' for i in range(1,19)}:raise AdmissionError('full Foxv2 D01-D18 registry required')
    paths=[original,registry]+([final_png] if final_png is not None else [])
    evidence=inventory(paths);static={'svg_present':final_svg is not None,'png_present':final_png is not None,'human_editor_evidence':None}
    if final_svg:
        import xml.etree.ElementTree as ET
        tree=ET.parse(final_svg);nodes=list(tree.getroot().iter());static.update(elements=len(nodes),text_elements=sum(x.tag.rsplit('}',1)[-1]=='text' for x in nodes),image_elements=sum(x.tag.rsplit('}',1)[-1]=='image' for x in nodes))
    dump(out/'static.json',static);reviews=[];provider=config.get('score_provider','deepseek_score')
    for judge in range(2):
        prompt='Independently review source and final reconstruction using the entire attached Foxv2 registry. You are blinded to assignments and other judges. Return JSON {"items":[{"id":registry criterion id,"status":"pass|fail|unknown|NA","evidence":string}]} with exactly 18 items. Use unknown when evidence is missing. Static SVG structure cannot prove human editing or editor interaction. No invented evidence. Static evidence: '+json.dumps(static)
        messages=[{'role':'user','content':[{'type':'text','text':prompt}]+[y for x in evidence for y in ({'type':'text','text':'Blinded artifact '+str(evidence.index(x))},x['content'])]}]
        raw=request(config,provider,slot(config,f'score/JUDGE{judge}/TURN0'),messages,lease,out/f'judge-{judge}');text,calls,_=extract(raw,config['providers'][provider]['protocol']);review=json.loads(text)
        items=review.get('items',[])
        if calls or len(items)!=18 or len({x.get('id') for x in items})!=18 or any(x.get('status') not in ('pass','fail','unknown','NA') for x in items):raise AdmissionError('invalid 18-criterion scoring response')
        expected=[x['id'] for x in registry_rows]
        if expected is not None and (len(expected)!=18 or {x['id'] for x in items}!=set(expected)):raise AdmissionError('scoring criterion identity mismatch')
        reviews.append(review);(out/f'judge-{judge}.json').write_bytes(text.encode())
    result={'reviews':reviews,'static':static,'registry_sha256':hashlib.sha256(Path(registry).read_bytes()).hexdigest(),'aggregation':'independent judgments retained; no invented consensus'};dump(out/'scores.json',result);return result

def first_child(path):
    s=json.loads(Path(path).read_text());out=Path(s['output_root']);sys.path.insert(0,str(Path(s['native_source_root'])/'src'))
    runtime=json.loads(Path(s['runtime_json']).read_text());os.environ.update(runtime)
    # Reuse reviewed admission, validation and network denials without Harness waits.
    bridge=Path(s['adapter']).parent/'first-stage-harness-bridge-20261029';sys.path.insert(0,str(bridge));import first_stage
    manifest=first_stage.source_manifest(s['native_source_root'],Path(s['adapter'])/'source')
    first_stage.install_denials()
    from figfox_plus.native import pipeline
    original=Path(s['original_png']);policy=first_stage.capability(s['capabilities']);sam=None
    if policy['sam']:sam=first_stage.validate_sam(first_stage.read(s['sam_catalog']),original)
    def callback(prompt,images,run_dir,purpose):
        print('LIVE_CALLBACK:'+json.dumps({'prompt':prompt,'images':[str(x) for x in images],'purpose':purpose}),flush=True)
        return json.loads(sys.stdin.readline())['text']
    run=out/'pipeline';run.mkdir();root=pipeline.first(original,run,send=callback,sam=sam,capabilities=policy);pipeline.stage(root,original,run/'stage-0')
    if first_stage.source_manifest(s['native_source_root'])!=manifest:raise AdmissionError('native source changed during first stage')
    dump(out/'provenance.json',{'origin':'actual frozen native.pipeline.first automatic isolated provider callback','original_png_sha256':first_stage.sha(original),'initial_svg_sha256':first_stage.sha(run/'stage-0/scene.svg'),'capability_sha256':first_stage.digest(policy),'native_source_manifest_sha256':first_stage.digest(manifest)})
    dump(out/'runtime-binding.json',{'runtime_paths':{k:str(Path(v).resolve()) for k,v in runtime.items()}});dump(out/'sam-neutral.json',{'assets':[] if sam is None else [{k:a[k] for k in ('id','role','source_crop','path')}|{'sha256':a['asset_hash']} for a in sam['assets']],'missing_assets':[],'complete_available_catalog':True})
    dump(out/'result.json',{'stage0_scene':str(run/'stage-0/scene.svg'),'original':str(original),'runtime':s['runtime_json'],'runtime_binding':str(out/'runtime-binding.json'),'provenance':str(out/'provenance.json'),'sam_neutral':str(out/'sam-neutral.json')})

def transport_child():
    import urllib.request,urllib.error
    x=json.load(sys.stdin);pc=x['provider']
    pause_file=Path(pc.get('pause_file',str(PAUSE_FILE)))
    if pause_file.exists():
        rid=str(uuid.UUID(x['request_id']))
        dump(pause_file.parent/'paused-before-http'/(rid+'.json'),{'request_id':x['request_id'],'http_started':False,'reason':'explicit provider pause guard'})
        raise SystemExit(75)
    if pc.get('env_file'):
        for line in Path(pc['env_file']).read_text().splitlines():
            if line.strip() and not line.lstrip().startswith('#'):
                k,sep,v=line.partition('=')
                if not sep:raise ValueError('invalid explicit env file')
                os.environ[k.strip()]=v.strip().strip('"\'')
    key=os.environ.get(pc['key_env'])
    if not key:raise ValueError('configured credential unavailable in isolated provider')
    req=urllib.request.Request(pc['endpoint'],data=json.dumps(x['body']).encode(),headers={'Authorization':'Bearer '+key,'Content-Type':'application/json','X-Client-Request-Id':x['request_id']})
    try:
        with urllib.request.urlopen(req,timeout=pc.get('timeout_seconds',600)) as response:raw=response.read()
        json.loads(raw);sys.stdout.write(raw.decode())
    except urllib.error.HTTPError as exc:
        error={'transport_error':'HTTP','status':exc.code,'detail':exc.read(8192).decode('utf-8',errors='replace')}
        dump(PAUSE_FILE.parent/'transport-errors'/(str(uuid.UUID(x['request_id']))+'.json'),error)
        print(json.dumps(error));raise SystemExit(1)

if __name__=='__main__':
    if sys.argv[1]=='--transport':transport_child()
    elif sys.argv[1]=='--first-child':first_child(sys.argv[2])
