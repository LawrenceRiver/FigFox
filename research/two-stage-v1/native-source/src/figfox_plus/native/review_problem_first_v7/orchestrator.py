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
from ..strict_review_envelope import build_schema, decode_envelope
from ..current_line_facts import build_line_facts
from .quality import POLICY
from .diagnostics import build_diagnostics
from ..tight_tp import measure_tight
import xml.etree.ElementTree as ET

TOOLS=[{'type':'function','function':{'name':'execute_review_program','description':'Submit all inspection observations, detected issues and executable programs. Host returns real execution and rendered images. No implicit model calls.',
 'parameters':{'type':'object','properties':{'observations':{'type':'array','items':{'type':'object'}},'observation_rows':{'type':'array','items':{'type':'object'}},'observation_evidence':{'type':'object'},'issues':{'type':'array','items':{'type':'object'}},'programs':{'type':'array','items':{'type':'object'}},'prior_issue_reviews':{'type':'array','items':{'type':'object'}}},'required':['issues','programs'],'additionalProperties':False}}}]
PROMPT=PROBLEM_PROMPT + '\n' + '''issues每项{id,image_id,category,description,original_evidence,current_evidence,target_ids,neighbor_ids,decision:confirmed|uncertain|preserved|duplicate,duplicate_of?,unresolved_reason?}。工具参数必须是直接包含category_sweeps、other_sweep、issues、programs的JSON对象，不得再包一层arguments字符串。先语义定位再绑定现图ID；每个确认问题给程序或未解决原因。不同问题不因在同区域合并；重复问题引用保留。
programs每项{id,issue_ids,image_id,base_revision,phase:preconstructor|reconstructor,route:module_program|generated_python,target_ids,depends_on:[],rcd_predescription,args?,source_code?,source_location?,relations?,when?}。模块程序args={operations:[{id?,method,target_ids,args}]}，同程序取样/测量操作可给唯一id，后续用{"$result":{"step":该id,"path":["samples",0,"modal_hex"]}}引用真实返回；跨程序单操作结果也可用前序program id引用，必须声明依赖。方法与参数见method_pack。可用已有TP/SP/BP任意组合，使用最新测量。动态程序source_code为Python，INPUT_SVG和OUTPUT_SVG变量由隔离运行器提供；CURRENT_TP为执行前宿主实测的当前对象/邻居紧边界及revision，可在Python中编写多对象动态计算和条件逻辑。CURRENT_TP是该程序开始时快照，修改后不能冒称最新测量；需要每步最新测量用module_program的$measure表达式和后检查循环，可import figfox_plus.sp.geometry等纯构造方法和xml.etree.ElementTree重建目标，必须保留每个目标ID及目标外结构不变。动态程序不能联网、启动子进程或读取任意文件；需要公式/渲染等外部进程时改用宿主已有受限模块操作。SP方法源码是参考，不是已执行。无工具能力则明确未解决。
relations是本程序需要检查的原图关系列表，每项{id,subject_id,object_id,predicate:separate|contain|legal_overlap,reference_evidence,min_gap?,padding?}；位置或尺寸改变需给本体及邻居关系，contain表示subject在object内，当前TP无报警不等于视觉通过；不提供关系则检查标为not_assessed。机械执行失败可预声明when={program:前序程序ID,status:failed|blocked|changed_unverified|executed_no_change}，触发程序须列入depends_on；条件符合才执行回退，视觉失败不能靠代码自行猜测。检查先对齐和交叠，执行根据依赖：内容/公式/几何构造在前，最终对齐和交叠收敛在后；同对象修改必须声明依赖。每个程序base_revision为本批图像revision，实际执行读取最新场景；同对象连续程序必须有依赖。SP原图素材crop与上游诊断Crop不同。涉及原图素材裁取或取色时source_location={basis:original_semantic,description:独立语义定位}，禁止把现图TP作为原图素材坐标。

本任务只有一张图，最多两次模型请求。第一次完整检查并提交可执行动态程序，宿主真实运行后第二次给你执行结果和新PNG。第二次逐问题复核真实新图，可生成纠正程序；不允许第三次请求。生成的代码能调用方法库，不能把源码当作已执行。第二次后再执行的修改仍待人工视觉验收。
几何S1也包括原本照片却被误画成几何，或本来成立的几何结构被画成乱码；不把普通照片风格、纹理差异当主要问题。
检查按E/F/B/A/S1，执行按依赖决定：同对象先改内容/结构，再用最新TP处理对齐和交叠；整体绑定、多对象与邻居都要顾及。不要只选择最容易改的项目。发现问题不受你会不会修复影响，修不了仍明确报告。
''' + POLICY
TOOLS[0]['function']['parameters']['properties']={
 **PROBLEM_SCHEMA,
 'issues':{'type':'array','items':{'type':'object'}},
 'programs':{'type':'array','items':{'type':'object'}},
 'prior_issue_reviews':{'type':'array','items':{'type':'object'}}}


def _tools_for(schedule,review_only=False):
    result=deepcopy(TOOLS)
    if review_only:
        props=result[0]['function']['parameters']['properties']
        result[0]['function']['parameters']['properties']={key:props[key] for key in ('issues','programs','prior_issue_reviews')}
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
       'schedule':schedule,'upstream_arrow_evidence':arrow_context,'current_line_facts':{k:compact_line_facts(v) for k,v in line_pack.items()},'current_diagnostics':diagnostic_pack,'method_pack':methods,'program_contract':PROMPT},ensure_ascii=False)}]
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
            data['category_itinerary']=category_itinerary(data.pop('schedule'))
            data['schedule_encoding']='Finish each category across full PNG, SVG/TP diagnostics and both full upstream crop sweeps, then continue to the next category. Submit ordered category_sweeps, followed by other_sweep. Region identities bind unchanged evidence assets.'
        if 'current_svg' in data:
            def reference(match):
                raw=match.group(0);digest=hashlib.sha256(raw.encode()).hexdigest();resources[digest]=raw
                return 'embedded-resource:sha256:'+digest
            data['current_svg']=re.sub(r'data:image/[^\"\s<>]+',reference,data['current_svg'])
            data['svg_resource_encoding']='Opaque embedded image data URIs use host resource references. Exact original SVG/URIs remain with executor. View actual pixels in supplied PNG/Crops; never replace these references or report them as corruption.'
        item['text']=json.dumps(data,ensure_ascii=False,separators=(',',':'))
    write_json(root/'resource-uri-map.json',resources)
    # Transport-size guard, not a claim about provider token capacity. Never drop evidence.
    if len(json.dumps(messages,ensure_ascii=False).encode())>100_000_000:
        raise ValueError('input_capacity_exceeded: prepared messages exceed 100MB; no evidence discarded')
    write_json(root/'messages.json',messages)
    write_json(root/'frozen.json',{p.name:_hash(p) for p in [root/'inputs.json',root/'schedule.json',root/'methods.json',root/'messages.json',root/'current-diagnostics.json',root/'upstream-arrow-provenance.json',root/'upstream-arrow-assets.json',root/'current-line-facts.json']})
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
    def reject_constant(value):raise ValueError('non-JSON numeric constant: '+value)
    plan=json.loads(source,parse_constant=reject_constant)
    if not isinstance(plan,dict):raise ValueError('plan must be object')
    wrapped=any(isinstance(items,list) and any(isinstance(item,dict) and key in item for item in items) for items,key in ((plan.get('programs'),'program_json'),(plan.get('prior_issue_reviews'),'review_json')))
    legacy='category_checks' not in plan and not wrapped
    if legacy:
        if 'category_sweeps' in plan and not isinstance(plan['category_sweeps'],list):raise ValueError('category_sweeps must be array')
        if 'prior_issue_reviews' in plan and not isinstance(plan['prior_issue_reviews'],list):raise ValueError('prior_issue_reviews must be array')
        actual_review_only=not bool({'category_sweeps','other_sweep'} & plan.keys())
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
                if 'category_sweeps' in plan:
                    try:plan=expand_category_sweeps(plan,schedule)
                    except (ValueError,KeyError,TypeError) as exc:
                        write_json(turn/'category-audit-error.json',{'error':str(exc)})
                write_json(turn/'plan.json',plan)
                if n==0:first_issues=plan['issues']
                else:
                    review_audit=_review_audit(plan,first_issues,images)
                    if review_audit['status']=='failed':write_json(turn/'review-audit-error.json',review_audit)
                if plan.get('_inspection_envelope_error'):
                    coverage={'records_complete':False,'inspection_complete':False,'visual_acceptance':'not_assessed','inspection_envelope_error':plan['_inspection_envelope_error']}
                    write_json(turn/'inspection-envelope-error.json',plan['_inspection_envelope_error'])
                elif n==0 or not coverage.get('records_complete'):
                    try:coverage=audit_problem_first(schedule,plan,plan['issues'])
                    except (ValueError,KeyError,TypeError) as exc:
                        coverage={'records_complete':False,'inspection_complete':False,'error':str(exc),'visual_acceptance':'not_assessed'}
                from .replay import filter_program_shapes
                plan['programs'],shape_rejected=filter_program_shapes(plan['programs'])
                shape_rejected.extend(plan.get('_decode_rejections',[]))
                all_rejected.extend(shape_rejected)
                write_json(turn/'program-shape-rejections.json',shape_rejected)
                from .issues import validate_issues
                validate_issues(plan['issues'],plan['programs'],images)
                from .programs import execute_programs
                from .replay import select_valid_programs
                accepted,rejected=select_valid_programs(plan['programs'],plan['issues'],images)
                all_rejected.extend(rejected)
                rejected=shape_rejected+rejected
                write_json(turn/'program-preflight.json',{'accepted':[p['id'] for p in accepted],'rejected':rejected})
                write_json(turn/'normalized-programs.json',accepted)
                result=execute_programs(accepted,plan['issues'],images,turn/'execution')
                result['rejected_programs']=rejected
                images={k:dict(v,original=images[k]['original']) for k,v in result['images'].items()};all_rcd.extend(result['rcd'])
                feedback={'execution_result':result,'coverage':coverage,'visual_passed':False}
            except (ValueError,KeyError,TypeError) as exc:
                feedback={'execution_result':{'error':str(exc)},'coverage':coverage,'visual_passed':False}
            feedback['inspection_envelope_error']=plan.get('_inspection_envelope_error') if plan else None
            feedback['review_audit']=review_audit
            feedback['response_metadata']=plan.get('_response_metadata',{}) if plan else {}
            review_audits.append(dict(review_audit,model_turn=n+1))
            if plan:
                all_issues.extend(dict(i,model_turn=n+1) for i in plan['issues'])
            write_json(turn/'feedback.json',feedback)
            if n+1<request_limit:
                messages.append(message)
                if raw_calls:
                    for raw_call in raw_calls:
                        messages.append({'role':'tool','tool_call_id':raw_call['id'],'content':json.dumps(_feedback_brief(feedback),ensure_ascii=False)})
                else:messages.append({'role':'user','content':json.dumps(_feedback_brief(feedback),ensure_ascii=False)})
                parts=[{'type':'text','text':'这是实际执行结果。未刷新上游Crop；旧Crop仅作历史，不可称新revision证据。检查全图执行结果，逐条说明旧问题去向并提交纠正程序。若首次检查记录不完整，仍需在原始输入上补齐全部三轮记录。'}]
                for k,im in images.items():
                    parts.append({'type':'text','text':json.dumps({'image_id':k,'current_revision':im['revision'],'current_svg':_svg_text(Path(im['svg']).read_text())},ensure_ascii=False)})
                    parts.extend(_image({'asset_id':k+'/executed_current','sha256':_hash(im['png']),'path':im['png']}))
                messages.append({'role':'user','content':parts})
        result={'status':('inspection_incomplete' if not coverage.get('records_complete') else 'execution_failed' if feedback['execution_result'].get('error') else 'partially_executed' if any(r.get('status') in ('failed','blocked') for r in all_rcd) else 'visual_review_pending'),
                'images':images,'issues':all_issues,'rcd':all_rcd,'coverage':coverage,'visual_passed':False,
                'rejected_programs':all_rejected,'review_audits':review_audits,'request_limit':request_limit,'final_model_visual_review':False,'last_feedback':feedback}
        critical=[i for i in all_issues if i.get('decision')=='confirmed' and i.get('category') in ('E','F','B','A','S1')]
        critical_map={i['id']:i['category'] for i in critical}
        converged={q for r in all_rcd if r.get('status') in ('changed_unverified','executed_no_change') for q in r['issue_ids'] if critical_map.get(q) not in ('E','F') or r.get('final_scene_check',{}).get('status')=='measured_converged'}
        result['emergency_unresolved']=[i['id'] for i in critical if i['id'] not in converged]
        if result['emergency_unresolved']:result['status']='emergency_unresolved'
        write_json(result_file,result)
        from .report import write_report
        write_report(root,inputs,all_issues,all_rcd,coverage,output_images=images)
        return result
