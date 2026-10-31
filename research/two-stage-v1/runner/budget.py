"""Conservative raw-row reservations and durable at-most-once HTTP journals.
No credentials, network transport, default ledger, or default prices are provided.
"""
import contextlib
import base64
import binascii
import struct
import subprocess
import zlib
from decimal import Decimal
import fcntl
import hashlib
import json
import math
import os
import stat
from pathlib import Path
import tempfile
import time
import uuid

class BudgetError(ValueError): pass
class UnknownAttempt(BudgetError): pass
class OverflowCostError(BudgetError): pass
class SampleBudgetExceeded(BudgetError): pass
class ConditionBudgetExceeded(BudgetError): pass

def _condition_key(run_uuid,cell):return str(run_uuid)+'/'+str(cell)
def _condition_exposure(d,group):
    ids=[rid for rid,row in d['requests'].items() if row.get('run_uuid')==group['run_uuid'] and row.get('cell')==group['cell']]
    return _sample_exposure(d,{'request_ids':ids})
def _condition_setup(d,config,run_uuid):
    for cell,cap in config.get('condition_caps_usd',{}).items():
        key=_condition_key(run_uuid,cell);group={'run_uuid':run_uuid,'cell':cell,'cap_usd':money(cap)}
        existing=d.setdefault('condition_allocations',{}).get(key)
        if existing is not None and existing!=group:raise BudgetError('immutable condition cap changed')
        d['condition_allocations'][key]=group
    if config.get('condition_caps_usd') and run_uuid not in d.setdefault('concurrent_runs',[]):d['concurrent_runs'].append(run_uuid)

def _sample_exposure(d, allocation):
    total=Decimal(0)
    for rid in allocation['request_ids']:
        row=d['requests'][rid]
        actual=money(row['cost_usd']) if row.get('cost_usd') is not None else Decimal(0)
        total+=actual if row['status']=='finished' else max(actual,money(row['reserve_usd']),money(row.get('upper_bound_usd',row['reserve_usd'])))
    return total

def money(x):
    if isinstance(x, bool) or not isinstance(x, (int,float,Decimal)):
        raise BudgetError('finite nonnegative numeric value required')
    d=Decimal(str(x))
    if not d.is_finite() or d<0: raise BudgetError('finite nonnegative value required')
    return d

def _pairs(items):
    d={}
    for k,v in items:
        if k in d: raise BudgetError('duplicate JSON key')
        d[k]=v
    return d

def _read(p):
    return json.loads(Path(p).read_text(),parse_float=Decimal,object_pairs_hook=_pairs,
                      parse_constant=lambda x: (_ for _ in ()).throw(BudgetError('nonfinite JSON')))

def _encode(x):
    if isinstance(x,Decimal):
        money(x); return str(x)
    if isinstance(x,dict): return '{'+','.join(json.dumps(k)+':'+_encode(v) for k,v in x.items())+'}'
    if isinstance(x,list): return '['+','.join(map(_encode,x))+']'
    return json.dumps(x,allow_nan=False)

def _write(p,data):
    p=Path(p); payload=(_encode(data)+'\n').encode()
    fd,tmp=tempfile.mkstemp(dir=p.parent,prefix=p.name+'.')
    try:
        os.fchmod(fd,0o600)
        with os.fdopen(fd,'wb') as f: f.write(payload); f.flush(); os.fsync(f.fileno())
        os.replace(tmp,p)
        fd=os.open(p.parent,os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(tmp): os.unlink(tmp)

@contextlib.contextmanager
def _locks(paths, timeout=5):
    handles=[]; deadline=time.monotonic()+timeout
    try:
        for p in sorted(set(map(str,paths))):
            fd=os.open(p,os.O_CREAT|os.O_RDWR|getattr(os,'O_NOFOLLOW',0),0o600); handles.append(fd)
            if not stat.S_ISREG(os.fstat(fd).st_mode): raise BudgetError('lock must be regular persistent file')
            while True:
                try: fcntl.flock(fd,fcntl.LOCK_EX|fcntl.LOCK_NB); break
                except BlockingIOError:
                    if time.monotonic()>=deadline: raise BudgetError('accounting lock timeout')
                    time.sleep(.01)
        yield
    finally:
        for fd in reversed(handles): os.close(fd)

def _path(p):
    p=Path(p)
    if not p.is_absolute() or p.is_symlink() or not p.is_file(): raise BudgetError('explicit existing absolute ledger required')
    return p.parent.resolve()/p.name

@contextlib.contextmanager
def _tx(config):
    p=_path(config['ledger_path'])
    with _locks([p.with_suffix('.lock'),Path(str(p)+'.lock')], config.get('lock_timeout',5)):
        d=_read(p); s=_summary(d,config['expected_cap_usd']); yield p,d,s

def _summary(d,cap):
    if not isinstance(d,dict) or not isinstance(d.get('requests'),dict): raise BudgetError('malformed accounting')
    c=money(d.get('cap_peak_usd'))
    if c!=money(cap): raise BudgetError('cap mismatch; raising or resetting cap prohibited')
    known=Decimal(0); unknown=Decimal(0); counts={}; reasons={}
    def count(status): counts[status]=counts.get(status,0)+1
    def block(reason): reasons[reason]=reasons.get(reason,0)+1
    for row in d['requests'].values():
        if not isinstance(row,dict): raise BudgetError('malformed request row')
        r=money(row.get('reserve_usd')); status=row.get('status'); count(str(status))
        upper=money(row.get('upper_bound_usd',r))
        actual=money(row['cost_usd']) if row.get('cost_usd') is not None else Decimal(0)
        if status=='finished':
            actual=money(row.get('cost_usd')); known+=actual
            if actual>r: block('actual_cost_exceeds_reserved_bound')
        elif status in ('reserved','bounded_unknown','unknown_cost'):
            known+=actual; unknown+=max(r,upper,actual)-actual
            if status=='unknown_cost': block('unknown_cost_request_requires_receipt_reconciliation')
            if row.get('formal_state')=='attempted' and not (row.get('run_uuid') in d.get('concurrent_runs',[]) and row.get('deadline_at',0)>time.time()): block('attempted_request_unsettled_no_automatic_retry')
            if actual>r: block('actual_cost_exceeds_reserved_bound')
        else: raise BudgetError('unbounded/unrecognized request status: '+str(status))
    # Existing namespace reservations cannot silently disappear from exposure.
    ns=d.get('cohort_budget')
    if ns:
        if ns.get('version')!=1 or not isinstance(ns.get('allocations'),dict): raise BudgetError('invalid cohort namespace')
        for alloc in ns['allocations'].values():
            if not isinstance(alloc,dict) or alloc.get('status') not in ('open','closed'): raise BudgetError('invalid cohort allocation')
            slots=alloc.get('slots'); planned=Decimal(0)
            if not isinstance(slots,list): raise BudgetError('invalid cohort slots')
            for slot in slots:
                r=money(slot.get('reserve_usd')); planned+=r; st=slot.get('status'); count('cohort:'+str(st))
                if st in ('finished','overflow'):
                    actual=money(slot.get('cost_usd')); known+=actual
                    if st=='overflow' or actual>r: block('actual_cost_exceeds_reserved_bound')
                elif st in ('planned','attempted','unknown_cost'):
                    unknown+=r
                    if st=='attempted': block('attempted_request_unsettled_no_automatic_retry')
                    if st=='unknown_cost': block('unknown_cost_request_requires_receipt_reconciliation')
                elif st!='released': raise BudgetError('invalid cohort state')
            envelope=money(alloc.get('allocation_usd'))
            if envelope<planned: raise BudgetError('invalid cohort envelope')
            if alloc['status']=='open': unknown+=envelope-planned
    for key,allocation in d.get('sample_allocations',{}).items():
        if allocation.get('status') not in ('open','closed'): raise BudgetError('invalid sample allocation')
        cap=money(allocation['cap_usd']);exposure=_sample_exposure(d,allocation)
        if exposure>cap:block('sample_exposure_exceeds_cap')
        if allocation['status']=='open' and not allocation.get('superseded_by_condition_caps'):unknown+=max(Decimal(0),cap-exposure)
    for group in d.get('condition_allocations',{}).values():
        if _condition_exposure(d,group)>money(group['cap_usd']):block('condition_exposure_exceeds_cap')
    total=known+unknown
    if total>c: block('total_exposure_upper_exceeds_cap')
    return dict(cap_usd=c,known_cost_usd=known,unknown_reserved_upper_usd=unknown,
                total_exposure_upper_usd=total,charged_usd=total,
                charged_usd_semantics='legacy_exposure_alias_not_actual_expense',
                available_usd=c-total,blocked=bool(reasons),blocked_reasons=reasons,status_counts=counts)

def inspect_budget(path,expected_cap):
    # Read-only: atomic replacement makes each read coherent; do not create locks.
    return _summary(_read(_path(path)),expected_cap)

def _provider(config,name):
    p=config['providers'][name]
    if 'context_window' in p and p['context_window']!=p.get('context_tokens'): raise BudgetError('context aliases disagree')
    for k in ('input_usd_per_million','output_usd_per_million','cache_usd_per_million','context_tokens','max_output_tokens','max_input_tokens'):
        money(p[k])
    for k in ('context_tokens','max_output_tokens','max_input_tokens'):
        if type(p[k]) is not int or p[k]<=0: raise BudgetError('positive integer token bounds required')
    if not p.get('price_provenance'): raise BudgetError('explicit price provenance required')
    if p['max_input_tokens']+p['max_output_tokens']>p['context_tokens']: raise BudgetError('configured envelope exceeds context')
    return p

def plan_block(config,rows):
    result=[]
    role_max=config.get('transport_role_max_requests',5); verifier_max=config.get('transport_verifier_max_requests',3)
    if type(role_max) is not int or type(verifier_max) is not int or role_max!=5 or verifier_max!=3: raise BudgetError('fixed transport bounds require 5 role and 3 verifier requests')
    names=['first/TURN0']+[f'{a}/TURN{t}' for a in ('main','semantic') for t in range(role_max)]+[f'planner/ROUND{r}/TURN{t}' for r in range(1,4) for t in range(role_max)]+[f'verifier/ROUND{r}/TURN{t}' for r in range(1,4) for t in range(verifier_max)]+[f'score/JUDGE{j}/TURN0' for j in range(2)]
    for row in rows:
        for slot in names:
            provider=row.get('slot_providers',{}).get(slot.split('/')[0],row['provider']); p=_provider(config,provider)
            cost=(money(p['max_input_tokens'])*max(money(p['input_usd_per_million']),money(p['cache_usd_per_million']))+money(p['max_output_tokens'])*money(p['output_usd_per_million']))/1000000
            result.append(dict(sample_id=str(row['sample_id']),cell=str(row['cell']),slot=slot,provider=provider,reserve_usd=cost))
    if money(config.get('sam_fee_usd',0))>0:
        raise BudgetError('positive external SAM fee unsupported: configure an exact fixed-fee receipt adapter before preflight')
    keys=[(s['sample_id'],s['cell'],s['slot']) for s in result]
    if len(keys)!=len(set(keys)): raise BudgetError('duplicate slot')
    return result

def plan_budget_summary(config,rows):
    """Explicit maximum slot exposure, never an expected-actual price quote."""
    slots=plan_block(config,rows)
    by_provider={}
    for s in slots:
        item=by_provider.setdefault(s['provider'],{'slots':0,'max_reserved_usd':Decimal(0)})
        item['slots']+=1; item['max_reserved_usd']+=s['reserve_usd']
    return {'slot_count':len(slots),'max_reserved_usd':sum((s['reserve_usd'] for s in slots),Decimal(0)),
            'cost_kind':'maximum_reserved_exposure_not_expected_actual','by_provider':by_provider}


def reserve_block(config,run_uuid,rows,run_dir):
    run_uuid=str(uuid.UUID(str(run_uuid))); slots=plan_block(config,rows)
    for s in slots: s['request_id']=str(uuid.uuid5(uuid.UUID(run_uuid),json.dumps([s['sample_id'],s['cell'],s['slot']])))
    run_dir=Path(run_dir).resolve(); run_dir.mkdir(parents=True,exist_ok=True)
    capped='sample_cap_usd' in config
    if capped:
        if len({s['sample_id'] for s in slots})!=1:raise BudgetError('one sample required per capped block')
        cap=money(config['sample_cap_usd'])
        if cap<=0:raise BudgetError('positive sample cap required')
        allocation_key=run_uuid+'/'+slots[0]['sample_id']
    with _tx(config) as (p,d,summary):
        _condition_setup(d,config,run_uuid)
        existing=[s['request_id'] in d['requests'] for s in slots]
        if any(existing):
            if not all(existing): raise BudgetError('partial block identity collision')
            for s in slots:
                row=d['requests'][s['request_id']]
                for k in ('run_uuid','provider','slot','sample_id','cell')+(() if capped else ('reserve_usd',)):
                    if row.get(k)!=(run_uuid if k=='run_uuid' else s[k]): raise BudgetError('immutable reservation changed')
            if capped:
                allocation=d.get('sample_allocations',{}).get(allocation_key)
                if not allocation or allocation['cap_usd']!=cap or any(s['request_id'] not in allocation['request_ids'] for s in slots):raise BudgetError('immutable sample allocation changed')
        else:
            required=Decimal(0) if config.get('condition_caps_usd') else cap if capped else sum((s['reserve_usd'] for s in slots),Decimal(0))
            if summary['blocked'] or required>summary['available_usd']:
                raise BudgetError('block unavailable: '+_encode(dict(available=summary['available_usd'],required_first_block=required,shortfall=max(Decimal(0),required-summary['available_usd']),blocked=summary['blocked'])))
            for s in slots:
                amount=Decimal(0) if capped else s['reserve_usd']
                d['requests'][s['request_id']]={**s,'reserve_usd':amount,'run_uuid':run_uuid,'status':'reserved','formal_state':'planned','upper_bound_usd':amount,**({'sample_allocation':allocation_key} if capped else {})}
            if capped:d.setdefault('sample_allocations',{})[allocation_key]={'status':'open','cap_usd':cap,'request_ids':[s['request_id'] for s in slots],**({'superseded_by_condition_caps':True} if config.get('condition_caps_usd') else {})}
            _write(p,d)
    return Lease(config,slots,run_dir)

def reserve_recovery(config,run_uuid,rows,run_dir,namespace):
    """Explicit new attempts share the original image cap and all prior costs."""
    if not isinstance(namespace,str) or not namespace or any(c not in 'abcdefghijklmnopqrstuvwxyz0123456789-' for c in namespace):raise BudgetError('explicit safe recovery namespace required')
    run_uuid=str(uuid.UUID(str(run_uuid)));slots=plan_block(config,rows)
    if len({s['sample_id'] for s in slots})!=1:raise BudgetError('recovery requires one source image')
    key=run_uuid+'/'+slots[0]['sample_id'];run_dir=Path(run_dir).resolve();run_dir.mkdir(parents=True,exist_ok=True)
    for s in slots:
        s['slot']=namespace+'/'+s['slot'];s['request_id']=str(uuid.uuid5(uuid.UUID(run_uuid),json.dumps([s['sample_id'],s['cell'],s['slot']])))
    with _tx(config) as (p,d,summary):
        _condition_setup(d,config,run_uuid)
        allocation=d.get('sample_allocations',{}).get(key)
        if not allocation or money(allocation['cap_usd'])!=money(config['sample_cap_usd']):raise BudgetError('original sample cap required for recovery')
        if summary['blocked']:raise BudgetError('unresolved accounting blocks recovery')
        existing=[s['request_id'] in d['requests'] for s in slots]
        if any(existing):
            if not all(existing) or any(s['request_id'] not in allocation['request_ids'] for s in slots):raise BudgetError('partial recovery identity')
        else:
            remaining=money(allocation['cap_usd'])-_sample_exposure(d,allocation)
            if remaining<=0:raise SampleBudgetExceeded('original image cap exhausted; recovery cannot reset it')
            if allocation['status']=='closed' and remaining>summary['available_usd'] and not config.get('condition_caps_usd'):raise BudgetError('global cap prevents reopening original image envelope')
            for s in slots:
                d['requests'][s['request_id']]={**s,'reserve_usd':0,'upper_bound_usd':0,'run_uuid':run_uuid,'status':'reserved','formal_state':'planned','sample_allocation':key,'recovery_namespace':namespace}
                allocation['request_ids'].append(s['request_id'])
            allocation['status']='open';_write(p,d)
    return Lease(config,slots,run_dir)

def _image_dimensions(url):
    if not isinstance(url,str) or not url.startswith(('data:image/png;base64,','data:image/jpeg;base64,')):
        raise BudgetError('only inline verified PNG/JPEG images have declared dimensions')
    try: raw=base64.b64decode(url.split(',',1)[1],validate=True)
    except (ValueError,binascii.Error) as e: raise BudgetError('invalid image base64') from e
    if raw.startswith(b'\x89PNG\r\n\x1a\n'):
        pos=8; dimensions=None; ended=False; saw_data=False
        while pos<len(raw):
            if pos+12>len(raw): raise BudgetError('truncated PNG')
            n=struct.unpack('>I',raw[pos:pos+4])[0]; kind=raw[pos+4:pos+8]; end=pos+12+n
            if end>len(raw): raise BudgetError('truncated PNG chunk')
            payload=raw[pos+8:pos+8+n]
            if zlib.crc32(kind+payload)&0xffffffff != struct.unpack('>I',raw[pos+8+n:end])[0]: raise BudgetError('invalid PNG CRC')
            if pos==8:
                if kind!=b'IHDR' or n!=13: raise BudgetError('invalid PNG header')
                dimensions=struct.unpack('>II',payload[:8])
            if kind==b'IDAT': saw_data=True
            if kind==b'IEND':
                if n or end!=len(raw): raise BudgetError('invalid PNG end')
                ended=True; break
            pos=end
        if not ended or not saw_data: raise BudgetError('incomplete PNG')
    elif raw.startswith(b'\xff\xd8') and raw.endswith(b'\xff\xd9'):
        pos=2; dimensions=None; saw_scan=False
        while pos<len(raw)-2:
            if raw[pos]!=255: raise BudgetError('invalid JPEG marker')
            while pos<len(raw) and raw[pos]==255: pos+=1
            marker=raw[pos]; pos+=1
            if marker==0xda: saw_scan=True; break
            if marker in (0xd8,0xd9) or 0xd0<=marker<=0xd7: continue
            if pos+2>len(raw): raise BudgetError('truncated JPEG')
            n=int.from_bytes(raw[pos:pos+2],'big')
            if n<2 or pos+n>len(raw): raise BudgetError('invalid JPEG segment')
            if marker in (0xc0,0xc1,0xc2):
                if n<8: raise BudgetError('invalid JPEG frame')
                h,w=struct.unpack('>HH',raw[pos+3:pos+7]); dimensions=(w,h)
            pos+=n
        if not saw_scan or dimensions is None: raise BudgetError('missing JPEG frame/scan')
    else: raise BudgetError('image format/signature mismatch')
    if not dimensions or min(dimensions)<=0: raise BudgetError('invalid image dimensions')
    return dimensions


def _text_token_count(text,provider_config):
    tokenizer=provider_config.get('text_tokenizer')
    if tokenizer is None: return len(text.encode('utf-8'))
    if not isinstance(tokenizer,dict): raise BudgetError('invalid explicit text tokenizer')
    python=Path(tokenizer.get('python','')); model=Path(tokenizer.get('tokenizer_json',''))
    expected=tokenizer.get('sha256'); margin=tokenizer.get('safety_margin_tokens')
    if (not python.is_absolute() or not python.is_file() or not os.access(python,os.X_OK)
            or not model.is_absolute() or not model.is_file() or model.is_symlink()
            or not isinstance(expected,str) or len(expected)!=64
            or type(margin) is not int or margin<4096
            or not isinstance(tokenizer.get('source_url'),str) or not tokenizer['source_url'].startswith('https://')):
        raise BudgetError('explicit pinned tokenizer/interpreter/provenance and >=4096 safety margin required')
    if hashlib.sha256(model.read_bytes()).hexdigest()!=expected: raise BudgetError('tokenizer data SHA256 mismatch')
    # Execute only our worker, never downloaded Python/config or remote code.
    # -I isolates Python import configuration; an empty environment cannot pass keys.
    worker="from tokenizers import Tokenizer; import sys; t=Tokenizer.from_file(sys.argv[1]); print(len(t.encode(sys.stdin.read(),add_special_tokens=False).ids))"
    try:
        result=subprocess.run([str(python),'-I','-c',worker,str(model)],input=text,
                              text=True,capture_output=True,env={},cwd='/',timeout=60)
    except (OSError,subprocess.SubprocessError) as exc: raise BudgetError('isolated tokenizer worker failed') from exc
    count=result.stdout.strip()
    if result.returncode or not count.isascii() or not count.isdecimal(): raise BudgetError('isolated tokenizer returned invalid token count')
    return int(count)+margin


def estimate_input_tokens(body,provider_config):
    """Full text estimate plus explicitly declared full-resolution image tiles.

    Default text uses UTF-8 bytes; optional pinned official tokenizer adds an
    explicit safety margin and is an estimate, not a billed-token guarantee.

    image_token_bound requires positive tile_size, tokens_per_tile and base_tokens.
    Inline image payload bytes are excluded, while their metadata is retained.
    Remote/unsupported images fail closed because dimensions cannot be verified.
    """
    if not isinstance(body,dict) or not (isinstance(body.get('messages'),list) or isinstance(body.get('input'),(list,str))):
        raise BudgetError('complete messages or Responses input required')
    image_cost=0
    def walk(x):
        nonlocal image_cost
        if isinstance(x,dict):
            if x.get('type') in ('image_url','input_image'):
                field=x.get('image_url'); url=field.get('url') if isinstance(field,dict) else field
                width,height=_image_dimensions(url)
                bound=provider_config.get('image_token_bound',{})
                for k in ('tile_size','tokens_per_tile','base_tokens'):
                    if type(bound.get(k)) is not int or bound[k]<=0: raise BudgetError('explicit positive image tile token bounds required')
                tile=bound['tile_size']; image_cost+=bound['base_tokens']+math.ceil(width/tile)*math.ceil(height/tile)*bound['tokens_per_tile']
                result={k:walk(v) for k,v in x.items() if k!='image_url'}
                result['image_url']=({**field,'url':'data:image/[payload excluded]'} if isinstance(field,dict) else 'data:image/[payload excluded]')
                return result
            return {k:walk(v) for k,v in x.items()}
        if isinstance(x,list): return [walk(v) for v in x]
        return x
    text=walk(body)
    return _text_token_count(_encode(text),provider_config)+image_cost


class Lease:
    def __init__(self,config,slots,run_dir): self.config=config; self.slots=slots; self.run_dir=run_dir
    def check_context(self,provider,body):
        p=_provider(self.config,provider)
        output=body.get('max_tokens',body.get('max_completion_tokens',body.get('max_output_tokens')))
        if output!=p['max_output_tokens']: raise BudgetError('configured maximum output must be supplied unchanged')
        tokens=estimate_input_tokens(body,p)
        if tokens>p['max_input_tokens'] or tokens+output>p['context_tokens']: raise BudgetError('complete request exceeds configured context/input envelope')
    def _find(self,provider,slot):
        matches=[s for s in self.slots if s['provider']==provider and (s['slot']==slot or '/'.join([s['sample_id'],s['cell'],s['slot']])==slot)]
        if len(matches)!=1: raise BudgetError('use unambiguous sample_id/cell/slot')
        return matches[0]
    def _cost(self,provider,response):
        p=_provider(self.config,provider); u=response.get('usage')
        if not isinstance(u,dict): return None
        inp=u.get('prompt_tokens',u.get('input_tokens')); out=u.get('completion_tokens',u.get('output_tokens'))
        if inp is None or out is None: return None
        cached=u.get('prompt_cache_hit_tokens',u.get('prompt_tokens_details',{}).get('cached_tokens',u.get('input_tokens_details',{}).get('cached_tokens',0)))
        if any(type(value) is not int or value<0 for value in (inp,out,cached)): raise BudgetError('usage token counts must be nonnegative integers')
        inp=money(inp); out=money(out); cached=money(cached)
        if cached>inp: raise BudgetError('invalid cached usage')
        return ((inp-cached)*money(p['input_usd_per_million'])+cached*money(p['cache_usd_per_million'])+out*money(p['output_usd_per_million']))/1000000
    def send(self,provider,slot,body,send):
        s=self._find(provider,slot); rid=s['request_id']; raw=self.run_dir/(rid+'.response.json')
        self.check_context(provider,body)
        digest=hashlib.sha256(json.dumps(body,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()
        with _locks([self.run_dir/(rid+'.lock')],self.config.get('lock_timeout',5)):
            with _tx(self.config) as (p,d,summary):
                row=d['requests'][rid]; state=row['formal_state']
                if row.get('body_sha256') not in (None,digest): raise BudgetError('changed request body cannot replay')
                if state!='planned' and not raw.exists(): raise UnknownAttempt('attempted request has no saved raw response; no retry')
                if state=='released': raise BudgetError('slot released')
                if state=='planned':
                    if summary['blocked']: raise BudgetError('unknown/overflow blocks HTTP')
                    if row.get('sample_allocation'):
                        allocation=d['sample_allocations'][row['sample_allocation']]
                        pc=_provider(self.config,provider)
                        upper=(money(estimate_input_tokens(body,pc))*max(money(pc['input_usd_per_million']),money(pc['cache_usd_per_million']))+money(pc['max_output_tokens'])*money(pc['output_usd_per_million']))/1000000
                        available=money(allocation['cap_usd'])-_sample_exposure(d,allocation)
                        group=d.get('condition_allocations',{}).get(_condition_key(row['run_uuid'],row['cell']))
                        if group is not None:
                            available=money(group['cap_usd'])-_condition_exposure(d,group)
                            if upper>available:raise ConditionBudgetExceeded('condition cap prevents HTTP: '+_encode({'condition':row['cell'],'remaining_usd':available,'next_request_upper_usd':upper,'cap_usd':group['cap_usd']}))
                            if upper>summary['available_usd']:raise BudgetError('global remaining cap prevents HTTP')
                        elif allocation['status']!='open' or upper>available:raise SampleBudgetExceeded('sample cap prevents HTTP: '+_encode({'remaining_usd':available,'next_request_upper_usd':upper,'cap_usd':allocation['cap_usd']}))
                        row.update(reserve_usd=upper,upper_bound_usd=upper)
                    row.update(formal_state='attempted',body_sha256=digest,attempted_at=time.time(),deadline_at=time.time()+self.config['providers'][provider].get('timeout_seconds',600)+60); _write(p,d)
            if not raw.exists():
                # Any exception leaves durable attempted state; never automatically retry.
                response=send(rid)
                if not isinstance(response,dict): raise BudgetError('provider JSON must be object')
                _write(raw,dict(request_id=rid,body_sha256=digest,response=response))
            saved=_read(raw)
            if saved.get('request_id')!=rid or saved.get('body_sha256')!=digest: raise BudgetError('raw response identity mismatch')
            response=saved['response']; cost=self._cost(provider,response)
            with _tx(self.config) as (p,d,_):
                row=d['requests'][rid]
                if row['formal_state']=='attempted':
                    row.update(formal_state='settled',status='unknown_cost' if cost is None else 'finished',cost_usd=cost,settled_at=time.time()); _write(p,d)
                elif row.get('cost_usd')!=cost: raise BudgetError('saved usage settlement mismatch')
            if cost is None: raise UnknownAttempt('usage missing; full reservation retained')
            if cost>row['reserve_usd']: raise OverflowCostError('actual cost durably recorded above reserve; blocked')
            # Ledger arithmetic stays Decimal; provider payloads cross a normal
            # JSON boundary (including fractional metadata such as temperature).
            return json.loads(_encode(response))
    def retire_cell(self,sample_id,cell):
        """Retire only genuinely unsent slots belonging to one terminal cell."""
        matches=[s for s in self.slots if s['sample_id']==str(sample_id) and s['cell']==str(cell)]
        if not matches: raise BudgetError('cell is not part of this reservation')
        with _tx(self.config) as (p,d,_):
            for s in matches:
                row=d['requests'][s['request_id']]
                if row['formal_state']=='planned': row.update(formal_state='released',status='finished',cost_usd=0)
            self._close_allocations(d)
            _write(p,d)
    def _close_allocations(self,d):
        keys={d['requests'][s['request_id']].get('sample_allocation') for s in self.slots}-{None}
        for key in keys:
            allocation=d['sample_allocations'][key]
            if all(d['requests'][rid]['formal_state'] in ('settled','released','quarantined') for rid in allocation['request_ids']):allocation['status']='closed'
    def inspect_attempts(self):
        """Read-only unresolved attempt snapshot; valid raw receipts may replay."""
        data=_read(_path(self.config['ledger_path']))
        _summary(data,self.config['expected_cap_usd'])
        result=[]
        for s in self.slots:
            row=data['requests'][s['request_id']]
            if row.get('formal_state')!='attempted' and row.get('status')!='unknown_cost': continue
            raw=self.run_dir/(s['request_id']+'.response.json'); valid=False
            if raw.is_file():
                try:
                    saved=_read(raw)
                    valid=(saved.get('request_id')==s['request_id'] and saved.get('body_sha256')==row.get('body_sha256') and isinstance(saved.get('response'),dict))
                except (ValueError,OSError): pass
            result.append({k:s[k] for k in ('sample_id','cell','slot','request_id')} | dict(state=row.get('formal_state'),status=row.get('status'),body_sha256=row.get('body_sha256'),raw_response_exists=raw.is_file(),raw_response_valid=valid))
        return result
    def close(self):
        with _tx(self.config) as (p,d,_):
            for s in self.slots:
                row=d['requests'][s['request_id']]
                if row['formal_state']=='planned': row.update(formal_state='released',status='finished',cost_usd=0)
            self._close_allocations(d)
            _write(p,d)
