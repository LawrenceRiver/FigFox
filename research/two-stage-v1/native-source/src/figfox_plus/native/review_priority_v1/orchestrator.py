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
from .compact import expand_observations
from .methods import build_method_pack
from .transport import send
from .quality import POLICY

TOOLS=[{'type':'function','function':{'name':'execute_review_program','description':'Submit all inspection observations, detected issues and executable programs. Host returns real execution and rendered images. No implicit model calls.',
 'parameters':{'type':'object','properties':{'observations':{'type':'array','items':{'type':'object'}},'observation_rows':{'type':'array','items':{'type':'object'}},'observation_evidence':{'type':'object'},'issues':{'type':'array','items':{'type':'object'}},'programs':{'type':'array','items':{'type':'object'}},'prior_issue_reviews':{'type':'array','items':{'type':'object'}}},'required':['issues','programs'],'additionalProperties':False}}}]
PROMPT='''你按用户方法检查并修复图像。上游提供的1/2 Crop已经完成，只读取全部配对证据，不重新分块。三轮检查：1原图全图vs现图全图并核SVG；2全部上游成对Crop；3再次全部相同成对Crop。每轮每图先E对齐、F交叠出框，再B字体公式、A知识内容、S1明显几何错误完整检查；按schedule逐条给观察，不只疑点、不跳过几何、不预设问题数量。代码检查只能证明记录完整，不能证明看对。不要输出隐藏思维过程，只提供可核验的图像观察。
每条observations原样保留schedule主键及current_revision、evidence_assets，添加state=clear|issue|uncertain|not_applicable，original_observation/current_observation为独立具体观察，issue_ids数组；不适用需applicability_reason。看不清记uncertain。
为避免重复字段占满输出，首次完整检查优先用紧凑格式替代observations：observation_evidence={证据ID:{original_observation:具体原图观察,current_observation:具体现图观察,applicability_reason?:不适用理由}}；observation_rows按schedule连续分组顺序每组一行，每行恰好六字段{image_id,pass,category,states,evidence_ids,issue_ids}。每组为同图同pass同category，组内按schedule区域顺序，states是逐区域字符C(clear)/I(issue)/U(uncertain)/N(not_applicable)，evidence_ids是逐区域证据ID数组，issue_ids是逐区域问题ID数组的数组。三个逐区域字段长度必须精确等于该组区域数。不得漏行或乱序。主键、revision、asset引用由宿主从schedule无损恢复，不能省略任何实际观察。只有具体观察确实完全一致时可复用证据文字；不能用“已检查/同上/正常”等替代证据，不能用第一轮结果代替重新检查。所有证据必须被引用。紧凑格式与observations不能同时给。第二请求首次覆盖已完整时可用observations=[]，并给逐问题复核。文字简洁具体，为所有检查、问题及程序留足输出空间。
issues每项{id,image_id,category,description,original_evidence,current_evidence,target_ids,neighbor_ids,decision:confirmed|uncertain|preserved|duplicate,duplicate_of?,unresolved_reason?}。先语义定位再绑定现图ID；每个确认问题给程序或未解决原因。不同问题不因在同区域合并；重复问题引用保留。
programs每项{id,issue_ids,image_id,base_revision,phase:preconstructor|reconstructor,route:module_program|generated_python,target_ids,depends_on:[],rcd_predescription,args?,source_code?,source_location?,relations?,when?}。模块程序args={operations:[{id?,method,target_ids,args}]}，同程序取样/测量操作可给唯一id，后续用{"$result":{"step":该id,"path":["samples",0,"modal_hex"]}}引用真实返回；跨程序单操作结果也可用前序program id引用，必须声明依赖。方法与参数见method_pack。可用已有TP/SP/BP任意组合，使用最新测量。动态程序source_code为Python，INPUT_SVG和OUTPUT_SVG变量由隔离运行器提供，可import figfox_plus.sp.geometry等纯构造方法和xml.etree.ElementTree重建目标，必须保留每个目标ID及目标外结构不变。动态程序不能联网、启动子进程或读取任意文件；需要公式/渲染等外部进程时改用宿主已有受限模块操作。SP方法源码是参考，不是已执行。无工具能力则明确未解决。
relations是本程序需要检查的原图关系列表，每项{id,subject_id,object_id,predicate:separate|contain|legal_overlap,reference_evidence,min_gap?,padding?}；位置或尺寸改变需给本体及邻居关系，contain表示subject在object内，当前TP无报警不等于视觉通过；不提供关系则检查标为not_assessed。机械执行失败可预声明when={program:前序程序ID,status:failed|blocked|changed_unverified|executed_no_change}，触发程序须列入depends_on；条件符合才执行回退，视觉失败不能靠代码自行猜测。检查先对齐和交叠，执行根据依赖：内容/公式/几何构造在前，最终对齐和交叠收敛在后；同对象修改必须声明依赖。每个程序base_revision为本批图像revision，实际执行读取最新场景；同对象连续程序必须有依赖。SP原图素材crop与上游诊断Crop不同。涉及原图素材裁取或取色时source_location={basis:original_semantic,description:独立语义定位}，禁止把现图TP作为原图素材坐标。
本任务仅有一张图，只允许一次模型请求。全部三轮发现、分类、方法选择、参数与程序都须在本次完整提交，不能把未完成工作寄望于第二次调用。完成后调用一次execute_review_program提交，本地宿主随后实际执行。本次请求内不能看到本地执行结果，也不能声称已执行或已目视验收。修复后由程序检查本体及邻居交叠，RCD由真实执行产生，你只写预描述。足够输出预算用于完整观察和程序，所有数组长度和顺序在提交前核对。不要把unknown改成clear，不要只检查预期有问题的类别。'''

PROMPT += POLICY + '''
本轮只解决五类重要问题。判断能用：知识内容正确、字体公式正确且可读、排列整齐、没有非原图有意的对齐错误或交叠出框、几何结构成立且比例没有明显失真。照片裁切风格、纹理、细小色差、细节相似度是次要项，本轮不要为这些单独修改或报为必须修复。S1现在仅指明显几何错误，不包括照片内容不同。
主动找问题：每轮先以挑错方式寻找一个最可疑的对齐候选和一个最可疑的交叠候选，再独立对照原图反证。候选必须记录成confirmed/uncertain/preserved，后两者说明不能确认或排除的依据；禁止为了凑数捏造确认错误。发现一个不能停止，继续检查所有区域和全部关联对象。一块Crop可有多个问题。优先寻找人眼可说清楚的结构性错误，不能只提交易改的小问题。
三轮保持不变：全图PNG对PNG并核SVG、既有全部Crop配对检查、再次全部Crop配对复查。所有五类都过，不能用上一轮结果替代。可以用每观察单独的observations数组，避免平行数组错位；必须提交完整检查记录。主问题必须给出实际执行程序，做不到明确未解决，不能因难修而不报告。
''' 

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


def prepare(bundle, task_dir):
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
    content=[{'type':'text','text':json.dumps({'input_inventory':{str(i):v for i,v in enumerate(['original Crop','current SVG','current PNG','original PNG','current Crop','current TP','SP library','BP library','Q list','Ask_data contract','Reconstructor interface','Preconstructor interface'],1)},
       'schedule':schedule,'method_pack':methods,'program_contract':PROMPT},ensure_ascii=False)}]
    for key,im in inputs['images'].items():
        content.append({'type':'text','text':json.dumps({'image_id':key,'revision':im['current_revision'],
          'current_svg':Path(im['current_svg']['path']).read_text(),'current_tp':json.loads(Path(im['current_tp']['path']).read_text()),
          'crop_pairs':[{k:v for k,v in p.items() if k not in ('original_asset','current_asset')} for p in im['crop_pairs']]},ensure_ascii=False)})
        content.extend(_image(im['original_png']));content.extend(_image(im['current_png']))
        for pair in im['crop_pairs']:
            content.extend(_image(pair['original_asset']));content.extend(_image(pair['current_asset']))
    messages=[{'role':'system','content':PROMPT},{'role':'user','content':content}]
    resources={}
    for item in content:
        if item['type']!='text':continue
        data=json.loads(item['text'])
        if 'schedule' in data:
            groups=[]
            for unit in data.pop('schedule'):
                identity=tuple(unit[k] for k in ('pass','image_id','category'))
                if not groups or identity!=tuple(groups[-1][k] for k in ('pass','image_id','category')):
                    groups.append({k:unit[k] for k in ('pass','image_id','category','current_revision')}|{'regions':[]})
                groups[-1]['regions'].append([unit['region_id'],unit['original_asset_id'],unit['current_asset_id']])
            data['schedule_groups']=groups
            data['schedule_encoding']='Expand groups in order; each regions tuple gives region_id, original_asset_id, current_asset_id; evidence_assets is the two asset IDs. Inherit group pass/image/category/revision. observation_rows follows exactly these group/region orders.'
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
    write_json(root/'frozen.json',{p.name:_hash(p) for p in [root/'inputs.json',root/'schedule.json',root/'methods.json',root/'messages.json']})
    return inputs


def _plan(message):
    calls=message.get('tool_calls',[])
    if len(calls)!=1 or calls[0].get('function',{}).get('name')!='execute_review_program':
        raise ValueError('expected_one_execute_review_program_tool_call')
    from .replay import parse_saved_arguments
    plan,normalizations=parse_saved_arguments(calls[0]['function']['arguments'])
    if normalizations:plan['_syntax_normalizations']=normalizations
    for key in ('issues','programs'):
        if not isinstance(plan.get(key),list):raise ValueError('missing '+key)
    return plan,calls[0]['id']


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


def run(task_dir, *, sender=None, request_limit=1):
    if type(request_limit)!=int or request_limit not in (1,2):raise ValueError('request_limit must be 1 or 2')
    root=Path(task_dir).resolve()
    with (root/'pipeline.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        for name,digest in json.loads((root/'frozen.json').read_text()).items():
            if _hash(root/name)!=digest:raise ValueError('frozen input modified: '+name)
        inputs=validate_bundle(json.loads((root/'inputs.json').read_text()))
        if len(inputs['images']) != 1:raise ValueError('one_image_per_review')
        if build_method_pack()['version_hash']!=json.loads((root/'methods.json').read_text())['version_hash']:
            raise ValueError('method_library_changed_since_prepare')
        result_file=root/'result.json'
        if result_file.exists():return json.loads(result_file.read_text())
        messages=json.loads((root/'messages.json').read_text());schedule=json.loads((root/'schedule.json').read_text())
        images={k:{'svg':i['current_svg']['path'],'png':i['current_png']['path'],'original':i['original_png']['path'],'revision':i['current_revision']} for k,i in inputs['images'].items()}
        all_issues=[];all_rcd=[];all_rejected=[];coverage={'records_complete':False,'visual_acceptance':'not_assessed'};first_issues=[]
        for n in range(request_limit):
            turn=root/f'phase-{n+1}';turn.mkdir(exist_ok=True)
            if (turn/'message.json').exists():message=json.loads((turn/'message.json').read_text())
            else:
                message=(sender or send)(messages,TOOLS,root,request_limit=request_limit)
                write_json(turn/'message.json',message)
            call_id=None;plan=None
            try:
                plan,call_id=_plan(message)
                write_json(turn/'plan.json',plan)
                if n==0:first_issues=plan['issues']
                else:_reviews(plan,first_issues,images)
                if n==0 or not coverage.get('records_complete'):
                    coverage_plan=dict(plan)
                    if coverage_plan.get('observations')==[] and 'observation_rows' in coverage_plan:
                        del coverage_plan['observations']
                    try:coverage=validate_observations(schedule,expand_observations(coverage_plan,schedule),plan['issues'])
                    except (ValueError,KeyError,TypeError) as exc:
                        coverage={'records_complete':False,'inspection_complete':False,'error':str(exc),'visual_acceptance':'not_assessed'}
                from .issues import validate_issues
                validate_issues(plan['issues'],plan['programs'],images)
                from .programs import execute_programs
                from .replay import select_valid_programs
                accepted,rejected=select_valid_programs(plan['programs'],plan['issues'],images)
                all_rejected.extend(rejected)
                write_json(turn/'program-preflight.json',{'accepted':[p['id'] for p in accepted],'rejected':rejected})
                result=execute_programs(accepted,plan['issues'],images,turn/'execution')
                result['rejected_programs']=rejected
                images={k:dict(v,original=images[k]['original']) for k,v in result['images'].items()};all_rcd.extend(result['rcd'])
                feedback={'execution_result':result,'coverage':coverage,'visual_passed':False}
            except (ValueError,KeyError,TypeError) as exc:
                feedback={'execution_result':{'error':str(exc)},'coverage':coverage,'visual_passed':False}
            if plan:
                all_issues.extend(dict(i,model_turn=n+1) for i in plan['issues'])
            write_json(turn/'feedback.json',feedback)
            if n+1<request_limit:
                messages.append(message)
                if call_id:messages.append({'role':'tool','tool_call_id':call_id,'content':json.dumps(feedback,ensure_ascii=False)})
                else:messages.append({'role':'user','content':json.dumps(feedback,ensure_ascii=False)})
                parts=[{'type':'text','text':'这是实际执行结果。未刷新上游Crop；旧Crop仅作历史，不可称新revision证据。检查全图执行结果，逐条说明旧问题去向并提交纠正程序。若首次检查记录不完整，仍需在原始输入上补齐全部三轮记录。'}]
                for k,im in images.items():
                    parts.append({'type':'text','text':json.dumps({'image_id':k,'current_revision':im['revision'],'current_svg':Path(im['svg']).read_text()},ensure_ascii=False)})
                    parts.extend(_image({'asset_id':k+'/executed_current','sha256':_hash(im['png']),'path':im['png']}))
                messages.append({'role':'user','content':parts})
        result={'status':('inspection_incomplete' if not coverage.get('records_complete') else 'execution_failed' if feedback['execution_result'].get('error') else 'partially_executed' if any(r.get('status') in ('failed','blocked') for r in all_rcd) else 'visual_review_pending'),
                'images':images,'issues':all_issues,'rcd':all_rcd,'coverage':coverage,'visual_passed':False,
                'rejected_programs':all_rejected,'request_limit':request_limit,'final_model_visual_review':False,'last_feedback':feedback}
        critical=[i for i in all_issues if i.get('decision')=='confirmed' and i.get('category') in ('E','F','B','A','S1')]
        critical_map={i['id']:i['category'] for i in critical}
        converged={q for r in all_rcd if r.get('status') in ('changed_unverified','executed_no_change') for q in r['issue_ids'] if critical_map.get(q) not in ('E','F') or r.get('final_scene_check',{}).get('status')=='measured_converged'}
        result['emergency_unresolved']=[i['id'] for i in critical if i['id'] not in converged]
        if result['emergency_unresolved']:result['status']='emergency_unresolved'
        write_json(result_file,result)
        from .report import write_report
        write_report(root,inputs,all_issues,all_rcd,coverage,output_images=images)
        return result
