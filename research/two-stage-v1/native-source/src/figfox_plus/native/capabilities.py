"""Frozen capability assignments and auditable execution boundaries.

Read-only host geometry checks remain common guards. This is an availability
ablation, not a claim that all geometry code has been removed from the host.
"""
from contextlib import contextmanager
from contextvars import ContextVar
import hashlib
import inspect
import json
from pathlib import Path
import time

VERSION = 'capabilities-v1'

def normalize_capabilities(value=None):
    if value is None:
        value = {'version': VERSION, 'sam': True, 'code_methods': True}
    if not isinstance(value, dict) or set(value) != {'version', 'sam', 'code_methods'}:
        raise ValueError('capabilities requires exactly version, sam, code_methods')
    if value['version'] != VERSION or any(type(value[k]) is not bool for k in ('sam', 'code_methods')):
        raise ValueError('capabilities version or strict boolean assignment invalid')
    return dict(value)

def capability_hash(value=None):
    return hashlib.sha256(json.dumps(normalize_capabilities(value), sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def freeze_policy(folder, value=None):
    policy = normalize_capabilities(value)
    path = Path(folder)/'capabilities.json'
    record = {'policy': policy, 'sha256': capability_hash(policy)}
    if path.exists() and json.loads(path.read_text()) != record:
        raise ValueError('frozen capabilities cannot change')
    path.write_text(json.dumps(record, sort_keys=True, indent=2))
    return policy

def load_policy(folder, requested=None):
    path = Path(folder)/'capabilities.json'
    saved = json.loads(path.read_text()) if path.exists() else None
    policy = normalize_capabilities(saved['policy'] if saved else None)
    if saved and saved['sha256'] != capability_hash(policy):
        raise ValueError('frozen capability hash mismatch')
    if requested is not None and normalize_capabilities(requested) != policy:
        raise ValueError('frozen capabilities cannot change')
    return policy

_TRACE = ContextVar('figfox_execution_trace', default=None)
_DETAILS = ContextVar('figfox_execution_details',default={})

def set_trace_details(**fields):
    _DETAILS.set(fields)

@contextmanager
def trace_context(folder, policy, stage):
    token = _TRACE.set((Path(folder)/'invocation-trace.jsonl', normalize_capabilities(policy), stage))
    details_token=_DETAILS.set({})
    try: yield
    finally:
        _TRACE.reset(token)
        _DETAILS.reset(details_token)

def trace_event(category, method, status, **fields):
    context = _TRACE.get()
    if context is None: return
    path, policy, stage = context
    fields={**_DETAILS.get(),**fields}
    row = dict(category=category, method=method, status=status, stage=stage,
               capability_hash=capability_hash(policy), at=time.time(), **fields)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a') as stream: stream.write(json.dumps(row, sort_keys=True)+'\n')

def invoke(category, function, *args, trace_method=None, **kwargs):
    method=trace_method or function.__module__+'.'+function.__name__
    try: source=inspect.getsource(function)
    except (TypeError, OSError): source=method
    metadata={'source_sha256':hashlib.sha256(source.encode()).hexdigest()}
    import xml.etree.ElementTree as ET
    before=args[0] if args and isinstance(args[0],ET.Element) else None
    if before is not None:metadata['before_revision']=hashlib.sha256(ET.tostring(before)).hexdigest()
    if len(args)>1 and isinstance(args[1],list) and args[1] and isinstance(args[1][0],dict) and args[1][0].get('action'):
        method=args[1][0]['action'];metadata['arguments_sha256']=hashlib.sha256(json.dumps(args[1],sort_keys=True).encode()).hexdigest()
    if method=='asset':metadata['asset_source']='model-specified original ROI'
    trace_event(category,method,'started',**metadata)
    try: result=function(*args,**kwargs)
    except Exception as exc:
        trace_event(category,method,'failed',error=str(exc),**metadata); raise
    after=result if isinstance(result,ET.Element) else result[0] if isinstance(result,tuple) and result and isinstance(result[0],ET.Element) else before
    if after is not None:metadata['after_revision']=hashlib.sha256(ET.tostring(after)).hexdigest()
    failed=isinstance(result,dict) and result.get('status')=='failed'
    trace_event(category,method,'failed' if failed else 'completed',**metadata)
    return result

def reject_disabled_program(program, policy):
    """Inspect every nested declaration before normalization or execution."""
    if normalize_capabilities(policy)['code_methods']: return
    def reject(what):
        trace_event('rejected_request',what,'rejected',program_id=program.get('id'))
        raise ValueError('code methods disabled: '+what)
    if program.get('route') != 'generated_python': reject(str(program.get('route')))
    def visit(value):
        if isinstance(value,dict):
            for key,item in value.items():
                if key in ('method','$measure','CURRENT_TP') or (key in ('operations','repairs') and item): reject(key)
                visit(item)
        elif isinstance(value,list):
            for item in value: visit(item)
    visit(program)


def validate_svg_capabilities(root, policy, *, terminal=False):
    policy=normalize_capabilities(policy)
    for node in root.iter():
        if not policy['code_methods'] and any(k in node.attrib for k in ('data-plus-sp','data-plus-crop','data-plus-color')):
            trace_event('rejected_request','SVG capability declaration','rejected',node_id=node.get('id'))
            raise ValueError('disabled SVG capability declaration')
        if node.tag.rsplit('}',1)[-1]=='image' and (terminal or not policy['sam']):
            href=node.get('href') or node.get('{http://www.w3.org/1999/xlink}href','')
            if not href.startswith('data:image/png;base64,') and not (not terminal and node.get('data-plus-crop')):
                raise ValueError('disabled or unbound image asset reference')
