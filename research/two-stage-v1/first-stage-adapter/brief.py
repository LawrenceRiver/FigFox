"""Assignment-aware briefs; common quality is invariant, availability is explicit."""
import argparse
import hashlib
import json
from pathlib import Path
import time
import assignment_policy
from category_profile import CONTRACT_SOURCES

P=Path(__file__).resolve().parent

def project_native_result(raw):
    """Public status-only tree, preserving every outcome and exclusion location."""
    if not isinstance(raw,dict) or not isinstance(raw.get('rcd'),list):raise ValueError('unknown native result shape')
    if any(not isinstance(row,dict) or not isinstance(row.get('program_id'),str) or not isinstance(row.get('status'),str) for row in raw['rcd']):raise ValueError('unknown native record shape')
    if set(raw)-{'images','rcd','aliases','visual_acceptance','rejected_programs','paint_effect_batch_rollback'}:raise ValueError('unknown native result fields')
    if 'rejected_programs' in raw and (not isinstance(raw['rejected_programs'],list) or any(not isinstance(row,dict) for row in raw['rejected_programs'])):raise ValueError('unknown rejected-program shape')
    keep={'status','error','errors','reason','program_id','issue_ids','target_ids','image_id','before_revision','after_revision','revision','rolled_back','visual_acceptance','id','check_id','check_ids','method','tool_status','program_sha256','source_sha256','sha256','final_valid'}
    excluded=[];outcomes=[]
    def walk(value,path):
        if isinstance(value,dict):
            result={}
            for key,item in value.items():
                where=path+'/'+key
                if key in keep:
                    if isinstance(item,(dict,list)) and key not in ('issue_ids','target_ids','check_ids','errors'):result[key]=walk(item,where)
                    elif isinstance(item,(str,bool,type(None))) or isinstance(item,list) and all(isinstance(x,str) for x in item):result[key]=item
                    else:raise ValueError('unknown public status field shape: '+where)
                    if key in ('status','error','errors','reason'):outcomes.append({'path':where,'value':result[key]})
                elif isinstance(item,(dict,list)):
                    nested=walk(item,where)
                    if nested:result[key]=nested
                    excluded.append(where)
                else:excluded.append(where)
            return result
        if isinstance(value,list):
            return [walk(item,path+'/'+str(i)) if isinstance(item,(dict,list)) else {} for i,item in enumerate(value)]
        raise ValueError('unknown nested result shape')
    public=walk(raw,'')
    return {'format':'off-native-status-projection-v1','raw_sha256':hashlib.sha256(json.dumps(raw,sort_keys=True,separators=(',',':')).encode()).hexdigest(),'record_count':len(raw['rcd']),'rejected_program_count':len(raw.get('rejected_programs',[])),'records':public,'all_outcomes':outcomes,'excluded_field_index':excluded,'policy':'All record entries and statuses/errors retained; nonstatus values and numerical measurement values withheld. Exclusion paths are field indices, not accessible files.'}

def finite_evidence(folder, output, label):
    """Copy no scene data; publish only image paths and SVG ID/frame navigation."""
    import xml.etree.ElementTree as ET
    folder=Path(folder);output=Path(output)
    paths=[folder/name for name in ('original.png','current.png','current.svg','public.svg') if (folder/name).is_file()]
    pairs=sorted((folder/'pack').glob('*-pair.png'));paths+=pairs
    ids=[]
    if (folder/'current.svg').exists():
        ids=[{'id':node.get('id'),'tag':node.tag.rsplit('}',1)[-1]} for node in ET.parse(folder/'current.svg').getroot().iter() if node.get('id')]
    frames=[]
    if (folder/'pack/pack.json').exists():
        raw=json.loads((folder/'pack/pack.json').read_text())
        if not isinstance(raw,dict) or not isinstance(raw.get('frames'),list):raise ValueError('unknown pack catalog')
        for row in raw['frames']:
            if not isinstance(row,dict) or not isinstance(row.get('frame_id'),str) or not isinstance(row.get('pair'),str):raise ValueError('unknown frame catalog entry')
            pair=folder/'pack'/Path(row['pair']).name
            if pair not in pairs:raise ValueError('missing finite pair image')
            frames.append({'frame_id':row['frame_id'],'pair':str(pair.resolve())})
    catalog=output/(label+'-navigation.json');catalog.write_text(json.dumps({'ids':ids,'frames':frames},indent=2))
    return paths+[catalog]

def prepare_off_views(root,run,role,round_,out):
    root=Path(root).resolve();r=root/'runs'/run;out=Path(out);stage=[r/'state.json']
    stage+=finite_evidence(r/'checkpoint',out,'checkpoint')
    if role=='planner':
        stage += [r/'merged.json']
        if round_>1:
            prev=r/f'round-{round_-1}'
            feedback=prev/'verifier/raw.json'
            if feedback.is_symlink() or (feedback.exists() and (not feedback.is_file() or feedback.resolve()!=feedback)):
                raise ValueError('previous verifier feedback must be exact same-run regular file')
            stage += [prev/name for name in ('raw-plan.json','plan.json','verification.json','necessity-review-requests.json','verifier/raw.json') if (prev/name).is_file()]
    if role=='verifier' or role=='planner' and round_>1:
        number=round_ if role=='verifier' else round_-1;folder=r/f'round-{number}'
        rawpath=folder/'native-result.json'
        if not rawpath.is_file():raise ValueError('missing native result for status projection')
        target=out/'native-status.json';projection=project_native_result(json.loads(rawpath.read_text()));projection['raw_sha256']=hashlib.sha256(rawpath.read_bytes()).hexdigest();target.write_text(json.dumps(projection,indent=2));stage += [target]
        if role=='verifier':
            raw=json.loads((folder/'candidate.json').read_text())
            def sha256(value):
                return isinstance(value,str) and len(value)==64 and all(c in '0123456789abcdef' for c in value)
            if not isinstance(raw,dict) or not sha256(raw.get('revision')):
                raise ValueError('invalid candidate evidence revision')
            hashes=raw.get('evidence_hashes');regions=raw.get('required_regions')
            if not isinstance(hashes,dict) or not hashes or any(not isinstance(k,str) or not k or not sha256(v) for k,v in hashes.items()) or hashes.get('current_svg')!=raw['revision']:
                raise ValueError('invalid candidate evidence hashes')
            if not isinstance(regions,list) or any(not isinstance(x,str) or not x for x in regions) or len(set(regions))!=len(regions):
                raise ValueError('invalid candidate required regions')
            envelope=out/'candidate-evidence.json'
            envelope.write_text(json.dumps({key:raw[key] for key in ('revision','evidence_hashes','required_regions')},indent=2))
            stage += [envelope]+finite_evidence(folder/'candidate',out,'candidate')
    return stage

def render_brief(root, run, role, round_=None, *, state=None, off_stage=None, connector_stage=None, connector_context=None):
    root=Path(root).resolve(); policy=assignment_policy.load(root)
    if role not in ('main','semantic','planner','verifier'):raise ValueError('unknown role')
    if (role in ('planner','verifier')) != (round_ in (1,2,3)):raise ValueError('invalid role round')
    enabled=policy['code_methods'];r=root/'runs'/run;tag=role+(f'-{round_}' if round_ else '')
    out=r/'jobs'/tag
    neutral=[root/'inputs'/name for name in ('capabilities.json','observer-assignment.json','policy.json','sam.json','sam','method-pack.json','native-contract.json')]
    if not policy['sam']:
        neutral=[path for path in neutral if path!=root/'inputs/sam']
    if not enabled:
        neutral=[path for path in neutral if path!=root/'inputs/sam']
        neutral += sorted(path for path in (root/'inputs/sam').rglob('*') if path.is_file())
    neutral += [root/'docs'/name for name in ('category-profile.md','native-contract.md','common-quality.md','common-conditional-policy.md')]
    if not enabled and off_stage is None:raise ValueError('off briefing requires finite prepared evidence')
    if enabled and role=='verifier' and (not connector_stage or not connector_context):raise ValueError('enabled verifier requires connected observer briefing')
    stage=[r/'state.json',r/'checkpoint']
    if role=='semantic' and enabled:stage += [root/'inputs/analysis/manifest.json',root/'inputs/analysis/proposals.json'];neutral += [root/'docs/observation-contract.md']
    if role=='planner':stage += [r/'merged.json']+([r/f'round-{round_-1}'] if round_>1 else [])
    if role=='verifier':stage += [r/f'round-{round_}'/name for name in ('candidate.json','candidate','native-result.json','preflight.json','insertion-scope-checks.json')]
    if not enabled:stage=list(off_stage)
    if enabled and role=='verifier':stage+=list(connector_stage);neutral += [root/'docs/connector-paint-observation-contract.md']
    if role in ('planner','verifier'):neutral += [root/'docs'/name for name in ('pending-observation-contract.md','necessity-review-contract.md')]
    if role=='verifier':neutral += [root/'docs/promotion-patch-contract.md']
    availability={**policy,'repair_routes':['module_program','generated_python'] if enabled else ['generated_python'],'semantic_extra_observations':'enabled' if enabled else 'disabled_by_assignment','common_host_services':['SVG rendering','same paired images','ID navigation','read-only scope and quality guards']}
    rolefile={'planner':'repair','verifier':'verify'}.get(role,role)+'.md'
    sections=[f'Fresh {role} role. External enhancement bundle assignment; flow and quality duties are unchanged.', 'availability_manifest: '+json.dumps(availability,sort_keys=True)]
    for name in ('common.md',rolefile):sections += [(root/'prompts'/name).read_text()]
    for name in ('common-quality.md','common-conditional-policy.md'):sections += [(root/'docs'/name).read_text()]
    if role=='main':sections += [(root/'prompts/main-native.txt').read_text()]
    if enabled:
        sources=[root/'source/src/figfox_plus'/name for name in CONTRACT_SOURCES]
        sections += ['Read every listed enabled authoritative source and supplied method manual: '+', '.join(map(str,sources))]
    sections += ['Allowed neutral inputs: '+', '.join(map(str,neutral)), 'Allowed current stage inputs: '+', '.join(map(str,stage)), f'Write raw role JSON to {out}/agent-output.json and actual-view/timing metadata to {out}/agent-meta.json. Only your own output directory is writable. No other runs, historical reports, evaluations, credentials or provider calls. Only the host executes repair programs; maximum three rounds.']
    from flow import PYTHON
    if role in ('main','semantic'):sections += [f'At most two read-only draft checks: "{PYTHON}" "{P}/flow.py" --root "{root}" check-report {run} {role} ABSOLUTE_DRAFT_PATH.']
    if role=='planner':sections += [f'At most two read-only draft checks: "{PYTHON}" "{P}/flow.py" --root "{root}" check-plan {run} {round_} ABSOLUTE_DRAFT_PATH.']
    if connector_context:sections += ['Host connector context: '+json.dumps(connector_context,sort_keys=True)]
    if not enabled:sections += ['Finite input policy: read only the exact listed files, never their parent directories or raw bounds/pack/native-result files. Navigation catalogs expose IDs/frame-image mapping only. Numerical native diagnostics are withheld by assignment.']
    return '\n\n'.join(sections)+'\n'

def prepare_contracts(cell):
    """Prepare generic docs/prompts only; no input/case or native execution."""
    import shutil
    root=Path(cell).resolve();policy=assignment_policy.load(root)
    for folder in ('docs','prompts'):
        (root/folder).mkdir(parents=True,exist_ok=True)
        for src in (P/folder).iterdir():
            if src.is_file() and src.name!='brief-contract-plan.md':
                if not policy['code_methods'] and src.name in ('observation-contract.md','connector-paint-observation-contract.md','connector-paint-provenance.md'):continue
                shutil.copyfile(src,root/folder/src.name)
    from figfox_plus.native.capability_prompts import COMMON_CONDITIONAL_POLICY,METHOD_APPLICABILITY
    from figfox_plus.native.review_problem_first_v13 import lean_inspection
    (root/'docs/common-quality.md').write_text((P/'prompts/common.md').read_text()+'\n'+lean_inspection.PROMPT+'\n'+(P/'docs/category-profile.md').read_text())
    (root/'docs/common-conditional-policy.md').write_text(COMMON_CONDITIONAL_POLICY+'\n'+METHOD_APPLICABILITY)
    # Inspection duties remain common; native method repair help is assignment-specific.
    from figfox_plus.native.review_problem_first_v13 import lean_inspection
    (root/'prompts/main-native.txt').write_text(lean_inspection.PROMPT)
    hashes={name:hashlib.sha256((root/'docs'/name).read_bytes()).hexdigest() for name in ('common-quality.md','common-conditional-policy.md')}
    return {'policy':policy,'common_hashes':hashes}

def main():
    a=argparse.ArgumentParser();a.add_argument('run');a.add_argument('role');a.add_argument('--round',type=int);a.add_argument('--root',type=Path,required=True);v=a.parse_args()
    from flow import Flow,prompt_hashes
    state=Flow(v.root).active_state(v.run)
    tag=v.role+(f'-{v.round}' if v.round else '');out=v.root/'runs'/v.run/'jobs'/tag;out.mkdir(parents=True,exist_ok=False)
    kwargs={}
    if assignment_policy.disabled(v.root):kwargs['off_stage']=prepare_off_views(v.root,v.run,v.role,v.round,out)
    elif v.role=='verifier':
        import connector_paint_bridge
        kwargs['connector_stage'],kwargs['connector_context']=connector_paint_bridge.briefing(Flow(v.root),v.run,v.round,out)
    prompt=render_brief(v.root,v.run,v.role,v.round,state=state,**kwargs)
    target=out/'dispatch-prompt.md';target.write_text(prompt)
    record={'run':v.run,'role':v.role,'round':v.round,'brief':str(target),'sha256':hashlib.sha256(prompt.encode()).hexdigest(),'prepared_monotonic_ns':time.monotonic_ns(),'frozen_prompt_hashes':prompt_hashes(v.root)}
    (v.root/'reports').mkdir(exist_ok=True)
    with (v.root/'reports/actual-dispatches.jsonl').open('a') as f:f.write(json.dumps(record)+'\n')
    print(json.dumps(record))

if __name__=='__main__':main()
