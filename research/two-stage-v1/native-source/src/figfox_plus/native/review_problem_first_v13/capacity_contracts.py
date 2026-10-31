"""Explicit capacity wire schemas; the original method and quality gates still apply."""
from copy import deepcopy
import json
import math

from .execution_contract import build_execution_contract
from .methods import build_method_pack
from .quality import POLICY

TEXT={'type':'string','minLength':1}
IDS={'type':'array','items':TEXT,'uniqueItems':True}
DECISIONS=['repair','preserve','equivalent','outside_scope','uncertain','needs_localization','duplicate']


def obj(properties, required=None, *, extra=False):
    return {'type':'object','properties':properties,'required':list(properties) if required is None else required,'additionalProperties':extra}


def array(item):
    return {'type':'array','items':item}


def discovery_tools():
    row={'id':TEXT,'image_id':TEXT,'category':{'enum':['E','F','B','A','S1','C','D','S2','S3','S4']},'description':TEXT,
         'original_evidence':TEXT,'current_evidence':TEXT,'target_ids':IDS,'neighbor_ids':IDS,'read_ids':IDS,
         'evidence_pair_ids':IDS,'evidence_asset_ids':IDS,'decision':{'enum':DECISIONS}}
    schema=obj({'observations':array(obj({**row,'issue_ids':IDS})), 'issues':array(obj(row)),
                'inspected_pair_ids':IDS,'unresolved_pair_ids':IDS,
                'category_coverage':obj({c:{'enum':['inspected','unresolved']} for c in ('E','F','B','A','S1')})})
    return tool('submit_capacity_discovery',schema,'Record every observation and issue with explicit evidence, disposition and responsibility coverage; no programs.')


def tool(name,schema,description):
    return [{'type':'function','function':{'name':name,'description':description,'parameters':schema}}]


def repair_tools():
    location=obj({'basis':{'enum':['original_semantic']},'description':TEXT})
    crop=obj({'object_complete':{'type':'boolean'},'clipped':{'type':'boolean'},
              'full_object_xywh':array({'type':'number'}),'edges_reviewed':obj({k:{'type':'boolean'} for k in ('left','top','right','bottom')}),
              'evidence':TEXT,'frame_xywh':array({'type':'number'})},['object_complete','clipped','full_object_xywh','edges_reviewed','evidence'])
    # Method arguments are heterogeneous original BP/TP/SP parameters, including
    # recursive expressions. They remain literal JSON and are checked by the host.
    args=obj({'operations':array({'$ref':'#/$defs/operation'}),'crop_review':crop},[],extra=True)
    operation=obj({'id':TEXT,'method':TEXT,'target_ids':IDS,'args':args,'source_location':location,'crop_review':crop,'check_id':TEXT},['method','target_ids','args'])
    relation=obj({'id':TEXT,'predicate':{'enum':['contain','separate','legal_overlap']},'subject_id':TEXT,'object_id':TEXT,
                  'reference_evidence':TEXT,'padding':{'type':'number'},'min_gap':{'type':'number'}},['id','predicate','subject_id','object_id','reference_evidence'])
    check=obj({'id':TEXT,'target_ids':IDS,'reference_ids':IDS,'mode':{'enum':['center_x','center_y','left','right','top','bottom']},'tolerance':{'type':'number'},'reference_evidence':TEXT})
    program=obj({'id':TEXT,'component_id':TEXT,'image_id':TEXT,'issue_ids':IDS,'base_revision':TEXT,
                 'phase':{'enum':['preconstructor','reconstructor']},'route':{'enum':['module_program','generated_python']},
                 'target_ids':IDS,'created_target_ids':IDS,'read_ids':IDS,'depends_on':IDS,'rcd_predescription':TEXT,
                 'args':obj({'operations':array({'$ref':'#/$defs/operation'})}), 'source_code':TEXT,'relations':array(relation),
                 'source_location':location,
                 'convergence':obj({'max_iterations':{'type':'integer'},'alignment_checks':array(check),'repairs':array({'$ref':'#/$defs/operation'})}),
                 'when':obj({'program':TEXT,'status':{'enum':['failed','blocked','changed_unverified','executed_no_change']}})},
                ['id','component_id','image_id','issue_ids','base_revision','phase','route','target_ids','created_target_ids','read_ids','depends_on','rcd_predescription','relations'])
    decision=obj({'row_id':TEXT,'row_type':{'enum':['issue','observation']},'decision':{'enum':DECISIONS},'evidence':TEXT,'program_ids':IDS})
    schema=obj({'decisions':array(decision),'programs':array(program)})
    schema['$defs']={'operation':operation}
    return tool('submit_capacity_repair',schema,'Return a disposition for every assigned issue and observation, and exact-revision component-scoped programs.')


def contract(capabilities=None):
    return {'capacity_output_contract':{
        'precedence':'The active capacity tool schema replaces earlier compact/category_sweeps/execute_review_program output envelopes in the preserved source messages. Retain all original scientific, evidence, method, crop, arrow and quality requirements. Discovery uses only submit_capacity_discovery; repair uses only submit_capacity_repair.',
        'discovery':'Every potentially actionable observation must link at least one explicit issue. Unknown localization uses an issue with empty target_ids and needs_localization; never drop it. Preserve equivalent/outside_scope/uncertain rows with explicit dispositions. Coverage reports evidence actually supplied; captions alone are not images.',
        'repair':'Return exactly one decision per assigned (row_type,row_id), including keep and unlocalized rows. Program issue_ids are the supplied A::/B:: names. Program component_id must identify one supplied connected component. No widening of current write/read scope. created_target_ids lists every ID explicitly created by typed bp_add. No implicit created IDs. Every program uses the exact base_revision. Local program IDs, depends_on, when and result references will be consistently namespaced per batch; dependencies cannot cross batches.',
        'generated_python_scope':'Opaque generated Python reads the entire scene conservatively; allowed only when the planned component already covers every current ID as a read or write. All original sandbox and target guards still apply.',
        'discovery_example':{'observations':[{'id':'observation-local','image_id':'IMAGE_ID','category':'B','description':'Evidence-based finding','original_evidence':'Original observation','current_evidence':'Current observation','target_ids':['CURRENT_ID'],'neighbor_ids':[],'read_ids':[],'evidence_pair_ids':['SUPPLIED_PAIR_ID'],'evidence_asset_ids':[],'decision':'repair','issue_ids':['issue-local']}],
                             'issues':[{'id':'issue-local','image_id':'IMAGE_ID','category':'B','description':'Evidence-based finding','original_evidence':'Original observation','current_evidence':'Current observation','target_ids':['CURRENT_ID'],'neighbor_ids':[],'read_ids':[],'evidence_pair_ids':['SUPPLIED_PAIR_ID'],'evidence_asset_ids':[],'decision':'repair'}],
                             'inspected_pair_ids':['SUPPLIED_PAIR_ID'],'unresolved_pair_ids':[], 'category_coverage':{k:'inspected' for k in ('E','F','B','A','S1')}},
        'repair_example':{'decisions':[{'row_id':'A::issue-local','row_type':'issue','decision':'repair','evidence':'Original supports this exact correction','program_ids':['local-program']},
                                     {'row_id':'A::observation-local','row_type':'observation','decision':'preserve','evidence':'Observation retained','program_ids':[]}],
                          'programs':[{'id':'local-program','component_id':'SUPPLIED_COMPONENT_ID','image_id':'IMAGE_ID','issue_ids':['A::issue-local'],'base_revision':'EXACT_SUPPLIED_REVISION','phase':'reconstructor','route':'module_program','target_ids':['CURRENT_ID'],'created_target_ids':[],'read_ids':[],'depends_on':[],'rcd_predescription':'Source-supported literal patch','relations':[],
                                       'args':{'operations':[{'method':'bp_patch','target_ids':['CURRENT_ID'],'args':{'attributes':{'fill':'SOURCE_SUPPORTED_COLOR'}}}]}}]},
        'example_limits':'Uppercase placeholders are schema illustrations, never observed facts or executable values. A created object uses bp_add with explicit parent_id and svg IDs, followed only after creation by operations targeting those IDs. Relations use explicit id,predicate,subject_id,object_id,reference_evidence; convergence repairs use check_id matching a declared check/relation.',
        'method_pack':build_method_pack(capabilities=capabilities),'execution_contract':build_execution_contract(capabilities), 'quality_contract':POLICY}}


def validate_schema(value,schema,root=None,path='$'):
    """Validate the deliberately small schema vocabulary above without dependencies."""
    root=schema if root is None else root
    if '$ref' in schema:
        key=schema['$ref'].removeprefix('#/$defs/')
        return validate_schema(value,root['$defs'][key],root,path)
    kind=schema.get('type')
    types={'object':dict,'array':list,'string':str,'boolean':bool,'integer':int,'number':(int,float)}
    if kind and (not isinstance(value,types[kind]) or kind in ('integer','number') and isinstance(value,bool)):
        raise ValueError(path+' must be '+kind)
    if isinstance(value,float) and not math.isfinite(value):raise ValueError(path+' must be finite')
    if 'enum' in schema and value not in schema['enum']:raise ValueError(path+' has unsupported disposition/value')
    if kind=='string' and len(value)<schema.get('minLength',0):raise ValueError(path+' must be nonempty')
    if kind=='object':
        props=schema['properties']
        if set(schema.get('required',[]))-set(value):raise ValueError(path+' missing '+','.join(sorted(set(schema['required'])-set(value))))
        if not schema.get('additionalProperties',True) and set(value)-set(props):raise ValueError(path+' unknown fields '+','.join(sorted(set(value)-set(props))))
        for key,item in value.items():
            if key in props:validate_schema(item,props[key],root,path+'.'+key)
    if kind=='array':
        if schema.get('uniqueItems') and len({json.dumps(x,sort_keys=True) for x in value})!=len(value):raise ValueError(path+' contains duplicates')
        for index,item in enumerate(value):validate_schema(item,schema['items'],root,path+f'[{index}]')


def parse_response(raw,expected_tool, *, allow_content_json=False):
    """Parse one completed response; literal content JSON requires explicit opt-in.

    Content interoperability never extracts, repairs, or fabricates a tool call.
    The caller must apply the same active schema and responsibility checks.
    """
    if not isinstance(raw,dict):raise ValueError('response envelope must be object')
    choice=raw
    if 'choices' in raw:
        choices=raw['choices']
        if not isinstance(choices,list) or len(choices)!=1:raise ValueError('expected one response choice')
        choice=choices[0]
    if not isinstance(choice,dict) or choice.get('finish_reason') not in ('stop','tool_calls'):raise ValueError('incomplete or unknown finish state')
    message=choice.get('message')
    if not isinstance(message,dict) or message.get('role')!='assistant':raise ValueError('expected assistant message')
    calls=message.get('tool_calls')
    if allow_content_json:
        if message.get('function_call') is not None:
            raise ValueError('unsupported legacy function call')
        if message.get('refusal') not in (None,''):
            raise ValueError('conflicting refusal response')
        if calls is None or calls==[]:
            if choice['finish_reason']!='stop':raise ValueError('content JSON requires complete stop')
            if not isinstance(message.get('content'),str):raise ValueError('content JSON must be text')
            return _parse_json(message['content'],require_object=True)
        if message.get('content') not in (None,''):
            raise ValueError('conflicting content and tool response')
    if not isinstance(calls,list) or len(calls)!=1 or not isinstance(calls[0],dict):raise ValueError('expected one tool call')
    call=calls[0];function=call.get('function')
    if call.get('type')!='function' or not isinstance(call.get('id'),str) or not call['id'] or not isinstance(function,dict) or function.get('name')!=expected_tool:raise ValueError('unexpected tool identity')
    if not isinstance(function.get('arguments'),str):raise ValueError('tool arguments must be JSON text')
    return _parse_json(function['arguments'],require_object=allow_content_json)


def _parse_json(text, *, require_object=False):
    def unique(pairs):
        obj={}
        for key,value in pairs:
            if key in obj:raise ValueError('duplicate JSON key '+key)
            obj[key]=value
        return obj
    value=json.loads(text,object_pairs_hook=unique,parse_constant=lambda v:(_ for _ in ()).throw(ValueError('nonfinite literal')))
    if require_object:
        if not isinstance(value,dict):raise ValueError('response JSON must be one object')
        def finite(item):
            if isinstance(item,float) and not math.isfinite(item):raise ValueError('nonfinite JSON number')
            if isinstance(item,dict):
                for child in item.values():finite(child)
            elif isinstance(item,list):
                for child in item:finite(child)
        finite(value)
    return value
