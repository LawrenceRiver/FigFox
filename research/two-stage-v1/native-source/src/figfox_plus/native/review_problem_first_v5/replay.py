"""Execute validated programs from a completed saved turn without another model call.

Inspection completeness remains an independent reported result. Never infer missing
observations or accept truncated model output. No unrestricted expression evaluation.
"""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from .compact import expand_observations
from .evidence import validate_observations
from .issues import validate_issues
from .programs import execute_programs,validate_programs
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
    return {'program_index':index,'program_id':program.get('id') if isinstance(program,dict) else None,
            'issue_ids':program.get('issue_ids',[]) if isinstance(program,dict) else [],
            'status':'rejected_before_execution','error':type(error).__name__+': '+str(error)}


def filter_program_shapes(programs):
    if not isinstance(programs,list):raise ValueError('programs must be array')
    valid=[];rejected=[]
    for index,program in enumerate(programs):
        try:_program_shape(program)
        except Exception as exc:rejected.append(_rejection(program,index,exc))
        else:valid.append(deepcopy(program))
    return valid,rejected


def select_valid_programs(programs,issues,images):
    accepted=[];rejected=[]
    for index,raw in enumerate(programs):
        try:
            _program_shape(raw)
            program=deepcopy(raw)
            im=program.get('image_id')
            if len(images)==1 and im in images and program.get('base_revision')!=images[im]['revision']:
                program.setdefault('host_normalizations',[]).append({'field':'base_revision','model_value':program.get('base_revision'),'host_value':images[im]['revision'],'basis':'single immutable input snapshot bound to saved request'})
                program['base_revision']=images[im]['revision']
            nested=program.get('convergence',{}).get('relations',[])
            if nested:
                rules=program.setdefault('relations',[])
                for r in nested:
                    if not any(x.get('id')==r.get('id') for x in rules):rules.append(r)
            refs=set(program.get('issue_ids',[]))
            allowed={t for q in issues if q['id'] in refs for t in q.get('target_ids',[])+q.get('neighbor_ids',[])}
            for op in program.get('convergence',{}).get('repairs',[]):
                for t in op.get('target_ids',[]):
                    if t in allowed and t not in program.get('target_ids',[]):
                        program.setdefault('host_normalizations',[]).append({'field':'target_ids','added':t,'basis':'explicit repair target already declared in issue scope'})
                        program['target_ids'].append(t)
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
            validate_programs(accepted+[program],issues,images)
        except Exception as exc:
            rejected.append(_rejection(raw,index,exc))
        else:accepted.append(program)
    return accepted,rejected


def run_saved_programs(task_dir,output_dir):
    root=Path(task_dir).resolve();out=Path(output_dir).resolve()
    if out.exists():raise ValueError('local replay output must be new')
    message=json.loads((root/'phase-1/message.json').read_text())
    calls=message.get('tool_calls',[])
    if len(calls)!=1 or calls[0]['function']['name']!='execute_review_program':raise ValueError('expected completed single tool call')
    raw=calls[0]['function']['arguments'];plan,edits=parse_saved_arguments(raw)
    inputs=json.loads((root/'inputs.json').read_text());schedule=json.loads((root/'schedule.json').read_text())
    if len(inputs['images'])!=1:raise ValueError('one_image_per_review')
    images={k:{'svg':i['current_svg']['path'],'png':i['current_png']['path'],'original':i['original_png']['path'],'revision':i['current_revision']} for k,i in inputs['images'].items()}
    plan['programs'],shape_rejected=filter_program_shapes(plan['programs'])
    validate_issues(plan['issues'],plan['programs'],images)
    out.mkdir(parents=True)
    write_json(out/'local-replay.json',{'source_task':str(root),'model_calls':0,'arguments_sha256':hashlib.sha256(raw.encode()).hexdigest(),'syntax_normalizations':edits})
    write_json(out/'plan.json',plan)
    from .inspection_contract import audit_inspection
    coverage=audit_inspection(schedule,plan,plan['issues'])
    accepted,rejected=select_valid_programs(plan['programs'],plan['issues'],images)
    rejected=shape_rejected+rejected
    write_json(out/'program-preflight.json',{'accepted':[p['id'] for p in accepted],'rejected':rejected})
    write_json(out/'normalized-programs.json',accepted)
    result=execute_programs(accepted,plan['issues'],images,out/'execution')
    result['rejected_programs']=rejected
    result.update(status='local_programs_executed_inspection_unverified',issues=plan['issues'],coverage=coverage,model_calls=0,visual_passed=False)
    write_json(out/'result.json',result)
    write_report(out,inputs,plan['issues'],result['rcd'],coverage,output_images=result['images'])
    return result
