"""Twelve-input handoff, complete inspection and at most one tool feedback turn."""
import base64
import io
from PIL import Image
from copy import deepcopy
import fcntl
import hashlib
import json
import re
from pathlib import Path
import shutil
from ...state import write_json
from .inputs import validate_bundle
from .inspection import make_schedule
from .evidence import validate_observations
from .inspection_contract import expand_observations, inspection_regions, audit_inspection, INSPECTION_SCHEMA, INSPECTION_PROMPT
from .methods import build_method_pack
from .transport import send
from .problem_first import PROMPT as PROBLEM_PROMPT, SCHEMA as PROBLEM_SCHEMA, category_itinerary, expand_category_sweeps, audit_problem_first
from .context_tables import compact_line_facts
from .input_encoding import compact_category_itinerary
from .lean_inspection import PROMPT as PROBLEM_PROMPT, REPAIR_PROMPT, build_schema as compact_schema, audit as audit_compact
from ..strict_review_envelope import build_schema, decode_envelope
from ..current_line_facts import build_line_facts
from ..review_photo_previews import collect_photo_previews
from .quality import POLICY
from .diagnostics import build_diagnostics
from ..tight_tp import measure_tight
import xml.etree.ElementTree as ET

TOOLS=[{'type':'function','function':{'name':'execute_review_program','description':'Submit all inspection observations, detected issues and executable programs. Host returns real execution and rendered images. No implicit model calls.',
 'parameters':{'type':'object','properties':{'observations':{'type':'array','items':{'type':'object'}},'observation_rows':{'type':'array','items':{'type':'object'}},'observation_evidence':{'type':'object'},'issues':{'type':'array','items':{'type':'object'}},'programs':{'type':'array','items':{'type':'object'}},'prior_issue_reviews':{'type':'array','items':{'type':'object'}}},'required':['issues','programs'],'additionalProperties':False}}}]
PROMPT=PROBLEM_PROMPT + '\n' + '''issues每项{id,image_id,category,description,original_evidence,current_evidence,target_ids,neighbor_ids,decision:confirmed|uncertain|preserved|duplicate}。第一次 programs 固定为 []。工具参数是 compact_category_sweeps、issues、programs 的 JSON，不要包一层 arguments。不要 other_sweep。
'''
PROGRAM_CONTRACT='''第二次才写程序。programs每项{id,issue_ids,image_id,base_revision,phase:preconstructor|reconstructor,route:module_program|generated_python,target_ids,depends_on:[],rcd_predescription,args?,source_code?,relations?,convergence?,when?}。模块程序args={operations:[{method,target_ids,args}]}。方法见已给的 method_pack。动态程序用 INPUT_SVG、OUTPUT_SVG 路径，ET.parse 后 tree.write。同对象必须 depends_on，其余 depends_on 为空。F、E、B、S1、D、S2 一起写。F 用 predicate，separate 的 min_gap、contain 的 padding 都要是正数。E 的端点或长度不对时改端点或长度，不能只平移到中心。B 只修编译失败、上下标和根号一类符号。字体不同但显示清晰的文字不要改。S1 没有分节用 SP cuboid，有分节或分节线折乱用 SP lattice，不要保留折线，不要手绘 polygon。主面要斜，侧面要看得见。D 用 sp_replace，kind 是 arrow，尖对尖，头的大小按像素，depends_on 为空。S2 是小贴块和原图完全不符，用 sp_photo 从原图切进来。relation 的 subject_id 和 object_id 必须是当前对象 id，或用 container_ids 与 target_ids，不要用 neighbor_ids。sp_photo 要有 crop_review 的 object_complete true、clipped false、full_object_xywh、edges_reviewed 四边 true、evidence，以及 source_location.basis 为 original_semantic。预检查失败的程序不会执行。
''' + POLICY
TOOLS[0]['function']['parameters']['properties']={
 **PROBLEM_SCHEMA,
 'issues':{'type':'array','items':{'type':'object'}},
 'programs':{'type':'array','items':{'type':'object'}},
 'prior_issue_reviews':{'type':'array','items':{'type':'object'}}}


def _tools_for(schedule,review_only=False):
    result=deepcopy(TOOLS)
    result[0]['function']['parameters']=compact_schema(schedule,review_only=review_only)
    return result


def _svg_text(value):
    return re.sub(r'data:image/[^"\s<>]+',lambda m:'embedded-resource:sha256:'+hashlib.sha256(m.group(0).encode()).hexdigest(),value)

def _feedback_brief(feedback):
    value=deepcopy(feedback)
    for row in value.get('execution_result',{}).get('rcd',[]):
        row.pop('measurement',None)
        row.pop('actual_parameters',None)
    value.get('execution_result',{}).pop('aliases',None)
    return value


def _hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _assets(inputs):
    for im in inputs['images'].values():
        for key in ('original_png','current_svg','current_png','current_tp'):yield im[key]
        for pair in im['crop_pairs']:
            yield pair['original_asset'];yield pair['current_asset']


def _image(asset):
    raw=Path(asset['path']).read_bytes();mime='image/png'
    # Transport only: lossless encoding, verified decoded pixels and dimensions.
    with Image.open(io.BytesIO(raw)) as original:
        rgba=original.convert('RGBA');out=io.BytesIO()
        rgba.save(out,format='WEBP',lossless=True,exact=True,method=4)
        encoded=out.getvalue()
        with Image.open(io.BytesIO(encoded)) as check:
            if check.size!=rgba.size or check.convert('RGBA').tobytes()!=rgba.tobytes():
                raise ValueError('lossless transport pixel mismatch')
        if len(encoded)<len(raw):raw=encoded;mime='image/webp'
    return [{'type':'text','text':json.dumps({'asset_id':asset['asset_id'],'sha256':asset['sha256'],'transport_encoding':mime,'pixels_unchanged':True})},
            {'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+base64.b64encode(raw).decode(),'detail':'original'}}]


def prepare(bundle, task_dir, *, upstream_arrow_specs=None):
    inputs=validate_bundle(bundle)
    if len(inputs['images']) != 1:
        raise ValueError('one_image_per_review: prepare each image as an independent task')
    root=Path(task_dir).resolve();root.mkdir(parents=True,exist_ok=False)
    assets=root/'inputs';assets.mkdir()
    for i,a in enumerate(_assets(inputs)):
        dest=assets/(f'{i:04d}'+Path(a['path']).suffix)
        shutil.copyfile(a['path'],dest);a['path']=str(dest)
    inputs=validate_bundle(inputs);schedule=make_schedule(inputs);methods=build_method_pack()
    write_json(root/'inputs.json',inputs);write_json(root/'schedule.json',schedule);write_json(root/'methods.json',methods)
    diagnostic_pack={}
    for key,im in inputs['images'].items():
        measured=measure_tight(ET.fromstring(Path(im['current_svg']['path']).read_text()))
        measured['current_revision']=im['current_revision']
        tp_file=root/(key+'-full-tight-tp.json');write_json(tp_file,measured)
        report=build_diagnostics(im['current_svg']['path'],tp_file)
        report['current_revision']=im['current_revision']
        # Geometric bounds can expose unclipped viewport overflow that raster TP cannot.
        coarse=build_diagnostics(im['current_svg']['path'],im['current_tp']['path'])
        report['unclipped_geometry_overflow_candidates']=[r for r in coarse['relation_candidates'] if r['kind']=='canvas_overflow']
        write_json(root/(key+'-diagnostics.json'),report)
        diagnostic_pack[key]={'current_revision':im['current_revision'],'coverage':report['coverage'],
            'relation_columns':['kind','object_ids','intersection_size','margins_ltrb'],
            'relation_candidates':[[r['kind'],r['object_ids'],r.get('intersection_size'),r.get('margins_ltrb')] for r in report['relation_candidates']],
            'structure_candidates':report['structure_candidates'],'unmeasurable':report['unmeasurable'],
            'unclipped_geometry_overflow_candidates':report['unclipped_geometry_overflow_candidates'],
            'normal_containment_count':len(report['normal_containment']),
            'instructions':report['instruction']}
    write_json(root/'current-diagnostics.json',diagnostic_pack)
    line_pack={}
    for key,im in inputs['images'].items():
        facts=build_line_facts(im['current_svg']['path']);facts['current_revision']=im['current_revision']
        write_json(root/(key+'-line-facts.json'),facts);line_pack[key]=facts
    write_json(root/'current-line-facts.json',line_pack)
    from ..line_alignment_candidates import summarize_line_alignment
    alignment_pack={key:summarize_line_alignment(facts) for key,facts in line_pack.items()}
    write_json(root/'current-line-alignment-candidates.json',alignment_pack)
    from ..coincident_path_candidates import build_coincident_path_candidates
    coincident_pack={key:build_coincident_path_candidates(inputs['images'][key]['current_svg']['path'],facts)
                     for key,facts in line_pack.items()}
    write_json(root/'current-coincident-path-candidates.json',coincident_pack)

    from .upstream_arrows import freeze_arrow_evidence
    arrow_context={};arrow_assets=[];arrow_provenance={}
    for key,im in inputs['images'].items():
        evidence=freeze_arrow_evidence((upstream_arrow_specs or {}).get(key),im['original_png'],root/'upstream-arrows'/key)
        for a in evidence['image_assets']:a['asset_id']=key+'/'+a['asset_id']
        for a in evidence['model_context']['arrows']:a['asset_id']=key+'/'+a['asset_id']
        arrow_context[key]=evidence['model_context'];arrow_assets.extend(evidence['image_assets']);arrow_provenance[key]=evidence['provenance']
    write_json(root/'upstream-arrow-provenance.json',arrow_provenance)
    write_json(root/'upstream-arrow-assets.json',arrow_assets)

    content=[{'type':'text','text':json.dumps({'input_inventory':{str(i):v for i,v in enumerate(['original Crop','current SVG','current PNG','original PNG','current Crop','current TP','SP library','BP library','Q list','Ask_data contract','Reconstructor interface','Preconstructor interface'],1)},
       'schedule':schedule,'upstream_arrow_evidence':arrow_context,'current_line_facts':{k:compact_line_facts(v) for k,v in line_pack.items()},'current_line_alignment_candidates':alignment_pack,'current_coincident_path_candidates':coincident_pack,'current_diagnostics':diagnostic_pack,'method_pack':methods,'program_contract':PROMPT},ensure_ascii=False)}]
    for key,im in inputs['images'].items():
        content.append({'type':'text','text':json.dumps({'image_id':key,'revision':im['current_revision'],
          'current_svg':Path(im['current_svg']['path']).read_text(),'current_tp':json.loads(Path(im['current_tp']['path']).read_text()),
          'crop_pairs':[{k:v for k,v in p.items() if k not in ('original_asset','current_asset')} for p in im['crop_pairs']]},ensure_ascii=False)})
        content.extend(_image(im['original_png']));content.extend(_image(im['current_png']))
        for pair in im['crop_pairs']:
            content.extend(_image(pair['original_asset']));content.extend(_image(pair['current_asset']))
    for arrow_asset in arrow_assets:content.extend(_image(arrow_asset))
    messages=[{'role':'system','content':PROMPT},{'role':'user','content':content}]
    resources={}
    for item in content:
        if item['type']!='text':continue
        data=json.loads(item['text'])
        if 'schedule' in data:
            data.update(compact_category_itinerary(data.pop('schedule')))
            data['schedule_encoding']='Region ids are only for citing a problem. Do not list every region. One look per category, then decide.'
        if 'current_svg' in data:
            def reference(match):
                raw=match.group(0);digest=hashlib.sha256(raw.encode()).hexdigest();resources[digest]=raw
                return 'embedded-resource:sha256:'+digest
            data['current_svg']=re.sub(r'data:image/[^\"\s<>]+',reference,data['current_svg'])
            data['svg_resource_encoding']='Opaque embedded image data URIs use host resource references. Exact original SVG/URIs remain with executor. View actual pixels in supplied PNG/Crops; never replace these references or report them as corruption.'
        item['text']=json.dumps(data,ensure_ascii=False,separators=(',',':'))
    write_json(root/'resource-uri-map.json',resources)
    from ..review_image_message_format import format_initial_image_messages
    messages,presentation_audit=format_initial_image_messages(messages,inputs,
        upstream_arrow_assets=arrow_assets,upstream_arrow_context=arrow_context)
    messages.append({'role':'user','content':'这是第一次请求，只找问题，programs 为空。整图、当前 SVG、1/2 Crop 各看一次。规则立方体、和原图完全不符，各自再单独扫一遍 1/2 Crop。紧急的对齐和交叠看见就记。不要复述推理。'})
    write_json(root/'image-presentation-audit.json',presentation_audit)
    # Transport-size guard, not a claim about provider token capacity. Never drop evidence.
    if len(json.dumps(messages,ensure_ascii=False).encode())>100_000_000:
        raise ValueError('input_capacity_exceeded: prepared messages exceed 100MB; no evidence discarded')
    write_json(root/'messages.json',messages)
    write_json(root/'frozen.json',{p.name:_hash(p) for p in [root/'inputs.json',root/'schedule.json',root/'methods.json',root/'messages.json',root/'current-diagnostics.json',root/'upstream-arrow-provenance.json',root/'upstream-arrow-assets.json',root/'current-line-facts.json',root/'current-line-alignment-candidates.json',root/'current-coincident-path-candidates.json',root/'image-presentation-audit.json']})
    return inputs


def _plan(message, schedule=None, *, review_only=False):
    calls=message.get('tool_calls',[])
    channel='tool_calls';call_id=None
    if calls:
        if len(calls)!=1 or calls[0].get('function',{}).get('name')!='execute_review_program':
            raise ValueError('expected_one_execute_review_program_tool_call')
        source=calls[0]['function']['arguments'];call_id=calls[0]['id']
    else:
        channel='content';source=message.get('content')
        if not isinstance(source,str) or not source.strip():raise ValueError('expected_review_json_content')
    raw_source=source
    if channel=='content':
        stripped=source.strip()
        if stripped.startswith('```'):
            match=re.fullmatch(r'```json\s*\n(.*?)\n```',stripped,re.DOTALL)
            if not match:raise ValueError('content must be pure JSON or one json fence')
            source=match.group(1)
    from ..review_json_syntax import parse_complete_json
    plan,syntax_edits=parse_complete_json(source)
    if not isinstance(plan,dict):raise ValueError('plan must be object')
    wrapped=any(isinstance(items,list) and any(isinstance(item,dict) and key in item for item in items) for items,key in ((plan.get('programs'),'program_json'),(plan.get('prior_issue_reviews'),'review_json')))
    legacy='category_checks' not in plan and not wrapped
    if legacy:
        if 'category_sweeps' in plan and not isinstance(plan['category_sweeps'],list):raise ValueError('category_sweeps must be array')
        if 'prior_issue_reviews' in plan and not isinstance(plan['prior_issue_reviews'],list):raise ValueError('prior_issue_reviews must be array')
        actual_review_only=not bool({'compact_category_sweeps','category_sweeps','other_sweep'} & plan.keys())
        contract='legacy_tool' if channel=='tool_calls' else 'legacy_content'
        if actual_review_only:contract+='_review_only'
        if actual_review_only!=review_only:
            plan['_inspection_envelope_error']={'error':'response mode mismatch','expected_review_only':review_only,'actual_review_only':actual_review_only}
            plan['_raw_inspection_envelope']={key:deepcopy(plan[key]) for key in ('category_sweeps','other_sweep') if key in plan}
            contract+='_inspection_mode_error'
    else:
        raw_plan=plan
        actual_review_only=not bool({'category_checks','other_sweep'} & raw_plan.keys())
        try:
            if actual_review_only!=review_only:raise ValueError('response mode mismatch')
            if schedule is not None:plan=decode_envelope(raw_plan,inspection_regions(schedule))
            contract='strict_review_only' if review_only else 'strict_full'
        except ValueError as exc:
            if schedule is None:raise
            # Strictly decode the existing execution fields independently. Never
            # create missing issue fields, observations, coordinates or programs.
            execution={key:raw_plan[key] for key in ('issues','programs','prior_issue_reviews') if key in raw_plan}
            plan=decode_envelope(execution,inspection_regions(schedule))
            plan['_inspection_envelope_error']={'error':str(exc),'expected_review_only':review_only,'actual_review_only':actual_review_only}
            plan['_raw_inspection_envelope']={key:deepcopy(raw_plan[key]) for key in ('category_checks','other_sweep') if key in raw_plan}
            contract='execution_only_after_envelope_error'
    for key in ('issues','programs'):
        if not isinstance(plan.get(key),list):raise ValueError('missing '+key)
    plan['_syntax_edits']=syntax_edits
    plan['_response_metadata']={'response_channel':channel,'contract':contract,'source_sha256':hashlib.sha256(raw_source.encode()).hexdigest()}
    return plan,call_id


def _reviews(plan,prior,images):
    rows=plan.get('prior_issue_reviews',[]);expected={i['id'] for i in prior};seen=set()
    current={i['id'] for i in plan['issues']}
    for row in rows:
        if row.get('issue_id') not in expected or row['issue_id'] in seen:raise ValueError('invalid prior issue review')
        issue=next(i for i in prior if i['id']==row['issue_id'])
        if row.get('revision')!=images[issue['image_id']]['revision']:raise ValueError('stale visual review')
        if row.get('status') not in ('resolved','persists','false_positive','uncertain') or not str(row.get('evidence','')).strip():raise ValueError('invalid visual review')
        if row['status']=='persists' and (not row.get('issue_ids') or not set(row['issue_ids'])<=current):raise ValueError('persisting issue omitted')
        seen.add(row['issue_id'])
    if seen!=expected:raise ValueError('missing prior issue disposition')


def _review_audit(plan,prior,images):
    try:_reviews(plan,prior,images)
    except Exception as exc:return {'status':'failed','error':type(exc).__name__+': '+str(exc),'visual_acceptance':'not_assessed'}
    return {'status':'records_valid','visual_acceptance':'not_assessed'}


def run(task_dir, *, sender=None, request_limit=2):
    if type(request_limit)!=int or request_limit not in (1,2):raise ValueError('request_limit must be 1 or 2')
    root=Path(task_dir).resolve()
    with (root/'pipeline.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        for name,digest in json.loads((root/'frozen.json').read_text()).items():
            if _hash(root/name)!=digest:raise ValueError('frozen input modified: '+name)
        for asset in json.loads((root/'upstream-arrow-assets.json').read_text()):
            if _hash(asset['path'])!=asset['sha256']:raise ValueError('frozen upstream arrow asset modified')
        inputs=validate_bundle(json.loads((root/'inputs.json').read_text()))
        if len(inputs['images']) != 1:raise ValueError('one_image_per_review')
        if build_method_pack()['version_hash']!=json.loads((root/'methods.json').read_text())['version_hash']:
            raise ValueError('method_library_changed_since_prepare')
        result_file=root/'result.json'
        if result_file.exists():return json.loads(result_file.read_text())
        messages=json.loads((root/'messages.json').read_text());schedule=json.loads((root/'schedule.json').read_text())
        images={k:{'svg':i['current_svg']['path'],'png':i['current_png']['path'],'original':i['original_png']['path'],'revision':i['current_revision']} for k,i in inputs['images'].items()}
        all_issues=[];all_rcd=[];all_rejected=[];review_audits=[];coverage={'records_complete':False,'visual_acceptance':'not_assessed'};first_issues=[]
        for n in range(request_limit):
            turn=root/f'phase-{n+1}';turn.mkdir(exist_ok=True)
            if (turn/'message.json').exists():message=json.loads((turn/'message.json').read_text())
            else:
                message=(sender or send)(messages,_tools_for(schedule,review_only=n>0 and coverage.get('records_complete',False)),root,request_limit=request_limit)
                write_json(turn/'message.json',message)
            expected_review_only=n>0 and coverage.get('records_complete',False)
            review_audit={'status':'not_required','visual_acceptance':'not_assessed'}
            raw_calls=message.get('tool_calls',[])
            call_id=raw_calls[0].get('id') if len(raw_calls)==1 else None;plan=None
            try:
                plan,call_id=_plan(message,schedule,review_only=expected_review_only)
                write_json(turn/'raw-plan.json',plan)
                from ..review_result_id_normalization import normalize_unreferenced_result_ids
                plan,id_audit=normalize_unreferenced_result_ids(plan)
                write_json(turn/'result-id-normalization.json',id_audit)
                for change in id_audit['changes']:
                    plan['programs'][change['program_index']].setdefault('host_normalizations',[]).append(
                        dict(change,kind='unreferenced_result_id_namespace'))
                if 'category_sweeps' in plan:
                    try:plan=expand_category_sweeps(plan,schedule)
                    except (ValueError,KeyError,TypeError) as exc:
                        write_json(turn/'category-audit-error.json',{'error':str(exc)})
                if n==0:
                    first_issues=plan['issues']
                    plan['programs']=[]
                write_json(turn/'plan.json',plan)
                if plan.get('_inspection_envelope_error'):
                    coverage={'records_complete':False,'inspection_complete':False,'visual_acceptance':'not_assessed','inspection_envelope_error':plan['_inspection_envelope_error']}
                    write_json(turn/'inspection-envelope-error.json',plan['_inspection_envelope_error'])
                elif n==0 or not coverage.get('records_complete'):
                    try:coverage=audit_compact(schedule,plan,plan['issues'])
                    except (ValueError,KeyError,TypeError) as exc:
                        coverage={'records_complete':False,'inspection_complete':False,'error':str(exc),'visual_acceptance':'not_assessed'}
                if n==0:
                    feedback={'execution_result':{'status':'discovery_only'},'coverage':coverage,'visual_passed':False}
                else:
                    from .replay import filter_program_shapes
                    plan['programs'],shape_rejected=filter_program_shapes(plan['programs'])
                    shape_rejected.extend(plan.get('_decode_rejections',[]))
                    all_rejected.extend(shape_rejected)
                    write_json(turn/'program-shape-rejections.json',shape_rejected)
                    from .issues import validate_issues
                    validate_issues(plan['issues'],plan['programs'],images)
                    from .programs import execute_programs
                    from .replay import select_valid_programs
                    accepted,rejected=select_valid_programs(plan['programs'],plan['issues'],images,prior_executed=all_rcd)
                    all_rejected.extend(rejected)
                    rejected=shape_rejected+rejected
                    write_json(turn/'program-preflight.json',{'accepted':[p['id'] for p in accepted],'rejected':rejected})
                    write_json(turn/'normalized-programs.json',accepted)
                    if not accepted:
                        feedback={'execution_result':{'status':'precheck_failed','rejected':rejected},'coverage':coverage,'visual_passed':False}
                    else:
                        result=execute_programs(accepted,plan['issues'],images,turn/'execution',prior_executed=all_rcd)
                        result['rejected_programs']=rejected
                        images={k:dict(v,original=images[k]['original']) for k,v in result['images'].items()};all_rcd.extend(result['rcd'])
                        feedback={'execution_result':result,'coverage':coverage,'visual_passed':False}
            except (ValueError,KeyError,TypeError) as exc:
                feedback={'execution_result':{'error':str(exc)},'coverage':coverage,'visual_passed':False}
            feedback['inspection_envelope_error']=plan.get('_inspection_envelope_error') if plan else None
            feedback['syntax_edits']=plan.get('_syntax_edits',[]) if plan else []
            feedback['review_audit']=review_audit
            feedback['response_metadata']=plan.get('_response_metadata',{}) if plan else {}
            review_audits.append(dict(review_audit,model_turn=n+1))
            if plan:
                all_issues.extend(dict(i,model_turn=n+1) for i in plan['issues'])
            write_json(turn/'feedback.json',feedback)
            found=[i for i in first_issues if i.get('decision') in ('confirmed','uncertain')]
            if n==0 and n+1<request_limit and found:
                messages.append(message)
                note=json.dumps({'issues':found},ensure_ascii=False)
                if raw_calls:
                    for raw_call in raw_calls:
                        messages.append({'role':'tool','tool_call_id':raw_call['id'],'content':note})
                messages.append({'role':'user','content':REPAIR_PROMPT+'\n'+PROGRAM_CONTRACT+'\n'+note})
        result={'status':('inspection_incomplete' if not coverage.get('records_complete') else 'execution_failed' if feedback['execution_result'].get('error') else 'partially_executed' if any(r.get('status') in ('failed','blocked') for r in all_rcd) else 'visual_review_pending'),
                'images':images,'issues':all_issues,'rcd':all_rcd,'coverage':coverage,'visual_passed':False,
                'rejected_programs':all_rejected,'review_audits':review_audits,'request_limit':request_limit,'final_model_visual_review':False,'last_feedback':feedback}
        critical=[i for i in all_issues if i.get('decision')=='confirmed' and i.get('category') in ('E','F','B','A','S1','D','S2')]
        critical_map={i['id']:i['category'] for i in critical}
        converged={q for r in all_rcd if r.get('status') in ('changed_unverified','executed_no_change') for q in r['issue_ids'] if critical_map.get(q) not in ('E','F') or r.get('final_scene_check',{}).get('status')=='measured_converged'}
        result['emergency_unresolved']=[i['id'] for i in critical if i['id'] not in converged]
        if result['emergency_unresolved']:result['status']='emergency_unresolved'
        write_json(result_file,result)
        from .report import write_report
        write_report(root,inputs,all_issues,all_rcd,coverage,output_images=images)
        from .followup import run_followup
        follow_dir=root.parent/(root.name+'-followup')
        try:
            result['followup']=run_followup(root,follow_dir,sender=sender)
        except Exception as exc:
            result['followup']={'opened':True,'status':'failed','error':type(exc).__name__+': '+str(exc)}
        write_json(result_file,result)
        return result
