"""Execute validated programs from a completed saved turn without another model call.

Inspection completeness remains an independent reported result. Never infer missing
observations or accept truncated model output. No unrestricted expression evaluation.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from ..sp_v2 import box as tp_box
from .compact import expand_observations
from .evidence import validate_observations
from .issues import validate_issues
from .programs import execute_programs,validate_programs
from .source_geometry import SourceGeometryUnverified
from .report import write_report
from ...state import write_json


def _parse_literal_arguments(raw):
    decoder=json.JSONDecoder();edits=[];source=raw
    for _ in range(33):
        try:return json.loads(source),edits
        except json.JSONDecodeError as error:
            pos=error.pos
            if len(edits)>=32 or not source.startswith('.replace(',pos):raise
            start=None;value=None
            for candidate in range(pos-1,-1,-1):
                if source[candidate]!='"':continue
                try:v,end=decoder.raw_decode(source,candidate)
                except json.JSONDecodeError:continue
                if end==pos and isinstance(v,str) and re.search(r'"(?:states|base_revision)"\s*:\s*$',source[:candidate]):
                    start=candidate;value=v;break
            if start is None:raise error
            cursor=pos+len('.replace(')
            while source[cursor].isspace():cursor+=1
            old,cursor=decoder.raw_decode(source,cursor)
            while source[cursor].isspace():cursor+=1
            if source[cursor]!=',':raise error
            cursor+=1
            while source[cursor].isspace():cursor+=1
            new,cursor=decoder.raw_decode(source,cursor)
            while source[cursor].isspace():cursor+=1
            if source[cursor]!=')' or not isinstance(old,str) or not isinstance(new,str):raise error
            cursor+=1
            replacement=json.dumps(value.replace(old,new),ensure_ascii=False)
            edits.append({'kind':'literal_string_replace','offset':start,'original':source[start:cursor],'replacement':replacement})
            source=source[:start]+replacement+source[cursor:]
    raise ValueError('too many syntax normalizations')


def parse_saved_arguments(source):
    original=source;edits=[]
    for _ in range(3):
        try:
            plan,prior=_parse_literal_arguments(source)
            if isinstance(plan,dict) and set(plan)=={'arguments'} and isinstance(plan['arguments'],str):
                plan=json.loads(plan['arguments'])
                edits.append({'kind':'literal_arguments_envelope','raw_sha256':hashlib.sha256(original.encode()).hexdigest()})
            return plan,edits+prior
        except json.JSONDecodeError as exc:
            # Only remove a parser-rejected surplus closer; never add missing/truncated data.
            if exc.msg!="Expecting ',' delimiter" or source[exc.pos:exc.pos+1] not in ('}',']') or len(edits)==2:raise
            edits.append({'kind':'parser_rejected_surplus_closer','offset':exc.pos,'removed':source[exc.pos],'raw_sha256':hashlib.sha256(original.encode()).hexdigest()})
            source=source[:exc.pos]+source[exc.pos+1:]
    raise ValueError('invalid arguments')


def _program_shape(program):
    if not isinstance(program,dict):raise ValueError('program must be object')
    for key in ('id','image_id','base_revision','phase','route'):
        if not isinstance(program.get(key),str) or not program[key]:raise ValueError(key+' must be nonempty string')
    for key in ('issue_ids','target_ids','depends_on'):
        value=program.get(key,[] if key=='depends_on' else None)
        if not isinstance(value,list) or any(not isinstance(v,str) or not v for v in value):raise ValueError(key+' must be array of strings')
    for key in ('convergence','args','when'):
        if key in program and not isinstance(program[key],dict):raise ValueError(key+' must be object')
    for key in ('relations','host_normalizations'):
        if key in program and (not isinstance(program[key],list) or any(not isinstance(v,dict) for v in program[key])):raise ValueError(key+' must be array of objects')
    for key in ('relations','repairs','alignment_checks'):
        value=program.get('convergence',{}).get(key,[])
        if not isinstance(value,list) or any(not isinstance(v,dict) for v in value):raise ValueError('convergence.'+key+' must be array of objects')


def _rejection(program,index,error):
    row = {'program_index':index,'program_id':program.get('id') if isinstance(program,dict) else None,
            'issue_ids':program.get('issue_ids',[]) if isinstance(program,dict) else [],
            'status':'rejected_before_execution','error':type(error).__name__+': '+str(error)}
    if isinstance(error, SourceGeometryUnverified):
        row.update(status='deferred_source_geometry', source_geometry_check=error.check,
                   original_preserved=True, automatic_network_retry=False)
    return row


def filter_program_shapes(programs):
    if not isinstance(programs,list):raise ValueError('programs must be array')
    valid=[];rejected=[]
    for index,program in enumerate(programs):
        try:
            program=deepcopy(program)
            normalize_optional_fields(program)
            _program_shape(program)
        except Exception as exc:rejected.append(_rejection(program,index,exc))
        else:valid.append(program)
    return valid,rejected


def normalize_optional_fields(program):
    """Normalize absent options and bounded work limits; never supply visual parameters."""
    if not isinstance(program,dict):return
    changes=[]
    for key in ('when','args','convergence','relations'):
        if key in program and program[key] is None:
            program.pop(key);changes.append({'kind':'omit_null_option','field':key})
    if program.get('depends_on','missing') is None:
        program['depends_on']=[]
        changes.append({'kind':'null_dependencies','value':[]})
    convergence=program.get('convergence')
    if convergence is None and program.get('relations'):
        convergence={};program['convergence']=convergence
    if isinstance(convergence,dict):
        for key in ('repairs','alignment_checks','relations'):
            if convergence.get(key,'missing') is None:
                convergence[key]=[]
                changes.append({'kind':'null_optional_array','field':'convergence.'+key})
        value=convergence.get('max_iterations')
        limit=6 if value is None else max(2,min(8,value)) if type(value) is int and value>0 else value
        if value!=limit:
            convergence['max_iterations']=limit
            changes.append({'kind':'bounded_runtime_limit','field':'convergence.max_iterations',
                            'model_value':value,'host_value':limit})
    def optional_anchors(operations,path):
        if not isinstance(operations,list):return
        for index,op in enumerate(operations):
            if not isinstance(op,dict) or not isinstance(op.get('args'),dict):continue
            args=op['args'];here=path+[index,'args']
            for key in ('parent_id','before_id','after_id'):
                if key in args and args[key] in (None,''):
                    args.pop(key)
                    changes.append({'kind':'omit_empty_anchor','field':here+[key]})
            if op.get('source_location','missing') is None:
                op.pop('source_location')
                changes.append({'kind':'omit_null_option','field':path+[index,'source_location']})
            if op.get('method')=='bp_program':optional_anchors(args.get('operations'),here+['operations'])
    optional_anchors(program.get('args',{}).get('operations'),['args','operations'])
    if isinstance(convergence,dict):
        optional_anchors(convergence.get('repairs'),['convergence','repairs'])
    if changes:
        program.setdefault('host_normalizations',[]).extend(changes)


def canonicalize_program(program):
    """Relocate existing declarations without inventing observations or parameters."""
    if program.get('route')!='module_program':return
    args=program.get('args',{})
    if 'convergence' in args:
        nested=args['convergence']
        if not isinstance(nested,dict):raise ValueError('args.convergence must be object')
        duplicate='convergence' in program
        if duplicate and program['convergence']!=nested:raise ValueError('conflicting convergence fields')
        program['convergence']=args.pop('convergence')
        program.setdefault('host_normalizations',[]).append({
            'kind':'canonical_convergence','source_path':['args','convergence'],
            'destination_path':['convergence'],'duplicate_removed':duplicate,
            'basis':'verbatim model declaration; no parameter changes'})
    def visit(operations,path):
        if not isinstance(operations,list):return
        for index,op in enumerate(operations):
            if not isinstance(op,dict) or not isinstance(op.get('args'),dict):continue
            here=path+[index]
            fields={'sp_replace':('measurement_viewport','target_tp'),
                    'sp_photo':('target_tp',),'tp_fit':('target_tp',)}.get(op.get('method'),())
            for field in fields:
                value=op['args'].get(field)
                if isinstance(value,list):
                    if len(value)!=4:raise ValueError(field+' requires four edges in left,top,right,bottom order')
                    # TP fields denote edges. source_crop remains original-pixel xywh.
                    converted=dict(zip(('left','top','right','bottom'),value))
                    if not any(isinstance(edge,dict) for edge in value):tp_box(converted)
                    op['args'][field]=converted
                    program.setdefault('host_normalizations',[]).append({
                        'kind':'tp_edge_array_to_object','field':here+['args',field],
                        'model_value':deepcopy(value),'host_value':deepcopy(converted),
                        'basis':'declared TP edge order; values unchanged; no coordinates inferred'})
            if op.get('method')=='bp_program':visit(op['args'].get('operations'),here+['args','operations'])
            if op.get('method')!='sp_photo' or 'source_location' in op or 'source_location' in program:continue
            proof=op.get('crop_review',op['args'].get('crop_review'))
            if not isinstance(proof,dict):continue
            evidence=proof.get('evidence')
            if not isinstance(evidence,str) or not evidence.strip():continue
            source_path=here+(['crop_review'] if 'crop_review' in op else ['args','crop_review'])+['evidence']
            op['source_location']={'basis':'original_semantic','description':evidence}
            program.setdefault('host_normalizations',[]).append({
                'kind':'photo_source_evidence_alias','source_path':source_path,
                'destination_path':here+['source_location','description'],
                'basis':'sp_photo crop_review is contractually original-only; existing evidence copied verbatim'})
    visit(args.get('operations'),['args','operations'])
    visit(program.get('convergence',{}).get('repairs'),['convergence','repairs'])


def select_valid_programs(programs,issues,images,prior_executed=None, *, candidate_only=False):
    accepted=[];rejected=[]
    for index,raw in enumerate(programs):
        try:
            program=deepcopy(raw)
            normalize_optional_fields(program)
            _program_shape(program)
            canonicalize_program(program)
            normalize_optional_fields(program)
            _program_shape(program)
            im=program.get('image_id')
            if len(images)==1 and im in images and program.get('base_revision')!=images[im]['revision']:
                program.setdefault('host_normalizations',[]).append({'field':'base_revision','model_value':program.get('base_revision'),'host_value':images[im]['revision'],'basis':'single immutable input snapshot bound to saved request'})
                program['base_revision']=images[im]['revision']
            nested=program.get('convergence',{}).get('relations',[])
            if nested:
                rules=program.setdefault('relations',[])
                for r in nested:
                    if not any(x.get('id')==r.get('id') for x in rules):rules.append(r)
            if program.get('route')=='module_program':
                def normalize_measure_args(operations,path):
                    if not isinstance(operations,list):return
                    for op_index,op in enumerate(operations):
                        if not isinstance(op,dict):continue
                        op_path=path+[op_index]
                        if op.get('method') in ('measure','check_tp') and 'args' not in op:
                            op['args']={}
                            program.setdefault('host_normalizations',[]).append({'field':op_path+['args'],'value':{},'basis':'parameterless measurement operation; targets unchanged'})
                        if op.get('method')=='bp_program' and isinstance(op.get('args'),dict):
                            normalize_measure_args(op['args'].get('operations'),op_path+['args','operations'])
                normalize_measure_args(program.get('args',{}).get('operations'),['args','operations'])
            validate_programs(accepted+[program],issues,images,prior_executed=prior_executed,candidate_only=candidate_only)
        except Exception as exc:
            rejected.append(_rejection(raw,index,exc))
        else:accepted.append(program)
    return accepted,rejected


def run_saved_programs(task_dir,output_dir):
    root=Path(task_dir).resolve();out=Path(output_dir).resolve()
    if out.exists():raise ValueError('local replay output must be new')
    out.mkdir(parents=True)
    write_json(out/'local-replay.json',{'source_task':str(root),'model_calls':0})
    try:
        message=json.loads((root/'phase-1/message.json').read_text(encoding='utf-8'))
        inputs=json.loads((root/'inputs.json').read_text(encoding='utf-8'));schedule=json.loads((root/'schedule.json').read_text(encoding='utf-8'))
        from .orchestrator import _plan
        plan,_=_plan(message,schedule,review_only=False)
    except Exception as exc:
        write_json(out/'parse-error.json',{'error':type(exc).__name__+': '+str(exc),'model_calls':0,'source_task':str(root)})
        raise
    write_json(out/'raw-plan.json',plan)
    if len(inputs['images'])!=1:raise ValueError('one_image_per_review')
    images={k:{'svg':i['current_svg']['path'],'png':i['current_png']['path'],'original':i['original_png']['path'],'revision':i['current_revision']} for k,i in inputs['images'].items()}
    plan['programs'],shape_rejected=filter_program_shapes(plan['programs'])
    write_json(out/'program-shape-rejections.json',shape_rejected)
    try:validate_issues(plan['issues'],plan['programs'],images)
    except Exception as exc:
        write_json(out/'issue-validation-error.json',{'error':type(exc).__name__+': '+str(exc),'model_calls':0})
        raise
    write_json(out/'local-replay.json',{'source_task':str(root),'model_calls':0,'response_metadata':plan['_response_metadata']})
    write_json(out/'plan.json',plan)
    from .problem_first import audit_problem_first,expand_category_sweeps
    if plan.get('_inspection_envelope_error'):
        coverage={'records_complete':False,'inspection_complete':False,'visual_acceptance':'not_assessed','inspection_envelope_error':plan['_inspection_envelope_error']}
    else:
        try:
            if 'category_sweeps' in plan:plan=expand_category_sweeps(plan,schedule)
            coverage=audit_problem_first(schedule,plan,plan['issues'])
        except (ValueError,TypeError,KeyError) as exc:
            coverage={'records_complete':False,'inspection_complete':False,'visual_acceptance':'not_assessed','error':str(exc)}
    write_json(out/'coverage.json',coverage)
    accepted,rejected=select_valid_programs(plan['programs'],plan['issues'],images)
    rejected=shape_rejected+plan.get('_decode_rejections',[])+rejected
    write_json(out/'program-preflight.json',{'accepted':[p['id'] for p in accepted],'rejected':rejected})
    write_json(out/'normalized-programs.json',accepted)
    from .candidates import source_candidates
    candidates=source_candidates(plan['programs'],plan['issues'],images,out/'source-candidates',rejected)
    result=execute_programs(accepted,plan['issues'],images,out/'execution')
    result['rejected_programs']=rejected
    result['repair_candidates']=candidates
    result.update(status='local_programs_executed_inspection_unverified',issues=plan['issues'],coverage=coverage,model_calls=0,visual_passed=False)
    write_json(out/'result.json',result)
    write_report(out,inputs,plan['issues'],result['rcd']+rejected,coverage,output_images=result['images'],candidates=candidates)
    return result
