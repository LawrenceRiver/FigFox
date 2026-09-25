"""Execute validated programs from a completed saved turn without another model call.

Inspection completeness remains an independent reported result. Never infer missing
observations or accept truncated model output. No unrestricted expression evaluation.
"""
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


def parse_saved_arguments(raw):
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


def select_valid_programs(programs,issues,images):
    accepted=[];rejected=[]
    for program in programs:
        try:validate_programs(accepted+[program],issues,images)
        except (ValueError,KeyError,TypeError) as exc:
            rejected.append({'program_id':program.get('id'),'issue_ids':program.get('issue_ids',[]),'status':'rejected_before_execution','error':str(exc)})
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
    validate_issues(plan['issues'],plan['programs'],images)
    out.mkdir(parents=True)
    write_json(out/'local-replay.json',{'source_task':str(root),'model_calls':0,'arguments_sha256':hashlib.sha256(raw.encode()).hexdigest(),'syntax_normalizations':edits})
    write_json(out/'plan.json',plan)
    coverage_plan=dict(plan)
    if coverage_plan.get('observations')==[] and 'observation_rows' in coverage_plan:
        del coverage_plan['observations']
    try:coverage=validate_observations(schedule,expand_observations(coverage_plan,schedule),plan['issues'])
    except (ValueError,KeyError,TypeError) as e:coverage={'records_complete':False,'inspection_complete':False,'error':str(e),'visual_acceptance':'not_assessed'}
    accepted,rejected=select_valid_programs(plan['programs'],plan['issues'],images)
    write_json(out/'program-preflight.json',{'accepted':[p['id'] for p in accepted],'rejected':rejected})
    result=execute_programs(accepted,plan['issues'],images,out/'execution')
    result['rejected_programs']=rejected
    result.update(status='local_programs_executed_inspection_unverified',issues=plan['issues'],coverage=coverage,model_calls=0,visual_passed=False)
    write_json(out/'result.json',result)
    write_report(out,inputs,plan['issues'],result['rcd'],coverage,output_images=result['images'])
    return result
