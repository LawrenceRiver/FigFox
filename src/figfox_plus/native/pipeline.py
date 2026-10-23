"""Native SVG first pass, paired crops, audited diagnosis and local tool execution."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET
from .document import parse,serialize,measure,public_svg,extract_response,bind_assets,frame_ids
from .tools import execute,nodes,sp_element
from .pack import build
from .diagnosis import audit,CATEGORIES,normalize,coverage_audit
from ..state import PLUS_ROOT,new_run,write_json
from ..providers import call_deepseek,call_gpt55
from ..sp.catalog import manual
from ..pipeline import parse_json
from ..sam import prepare_assets

def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()
def _host_crop_proof(node,asset,original,requested_crop,folder):
    path=Path(asset['path']).resolve();source=Path(original).resolve()
    if not path.is_file() or not path.is_relative_to((Path(folder)/'assets').resolve()):raise ValueError('host crop asset is outside the run')
    if asset['source_hash']!=sha(source) or asset['requested_crop']!=requested_crop:raise ValueError('host crop source or request mismatch')
    if asset['representation'] not in ('raster','vector'):raise ValueError('host crop representation mismatch')
    return {'node_id':node.get('id'),'node_sha256':hashlib.sha256(ET.tostring(node)).hexdigest(),
            'asset_path':str(path),'asset_sha256':sha(path),'source_path':str(source),
            'source_sha256':sha(source),'requested_crop':requested_crop,'representation':asset['representation']}

def stage(root,original,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    (folder/'scene.svg').write_text(serialize(root));b=measure(root,folder/'preview.png');write_json(folder/'bounds.json',b)
    frames=build(original,folder/'preview.png',root,b,folder/'pack');return b,frames

def archived_first(original,source):
    source=Path(source).resolve();original=Path(original).resolve()
    if 'quarantine' in source.parts:raise ValueError('quarantined source forbidden')
    if sha(source/'work/ORIGINAL.png')!=sha(original):raise ValueError('archive original does not match input')
    response=source/'response-pass1.json';root=parse(extract_response(response))
    library=json.loads((source/'picture-library.json').read_text())
    assets={a['id']:source/'pictures'/a['file'] for a in library['pictures']}
    # Only asset IDs actually present in model output are bound. No positions copied.
    bind_assets(root,assets)
    provenance={'source_response':str(response),'response_sha256':sha(response),'original_sha256':sha(original),
        'archive_original':str(source/'work/ORIGINAL.png'),'asset_library_sha256':sha(source/'picture-library.json'),
        'assets':{k:{'path':str(v),'sha256':sha(v)} for k,v in assets.items()},
        'request_images_redacted':True,'limitations':'archive request uses IMAGE_OMITTED; original hash checked against saved archive original, not decoded HTTP payload',
        'manual_numeric_answers':False,'not_used':['R00.svg','R00.png','postprocessed outputs','quarantine']}
    return root,provenance

def first(original,run,send=call_gpt55,sam=None,*,capabilities=None,sam_service_url='http://127.0.0.1:18080'):
    from .capabilities import freeze_policy,trace_context
    policy=freeze_policy(run,capabilities)
    if capabilities is None and sam is not None and 'status' not in sam:
        # Historical injected offline fixtures predate status manifests.
        sam=dict(sam,status={'sam':'ok'},mock=True,legacy_injected_fixture=True)
    with trace_context(run,policy,'first'):
        return _first(original,run,send,sam,policy,sam_service_url)

def _first(original,run,send,sam,policy,sam_service_url):
    from .capabilities import invoke,trace_event,validate_svg_capabilities
    from .capability_prompts import common_prompt,block_hashes
    from PIL import Image
    if not policy['sam']:
        if sam and sam.get('assets'):raise ValueError('SAM disabled: supplied assets forbidden')
        sam={'assets':[],'status':'disabled_by_assignment','source_hash':sha(original)}
    else:
        sam=invoke('sam_intervention',prepare_assets,original,PLUS_ROOT/'runs/sam-cache',service_url=sam_service_url) if sam is None else sam
        status=sam.get('status')
        if not isinstance(status,dict) or not status or any(v!='ok' for v in status.values()):
            raise ValueError('SAM preparation failed before model generation')
        if not sam.get('legacy_injected_fixture'):
            if sam.get('source_hash')!=sha(original):raise ValueError('SAM source hash mismatch')
            for asset in sam.get('assets',[]):
                if asset.get('source_hash')!=sam['source_hash'] or asset.get('asset_hash')!=sha(asset['path']):
                    raise ValueError('SAM asset hash mismatch')
    write_json(run/'prompt-block-hashes.json',block_hashes(policy))
    write_json(run/'sam.json',sam)
    with Image.open(original) as im:W,H=im.size
    pictures=[a for a in sam['assets'] if a['role']!='arrow_hint'];arrows=[dict(a) for a in sam['assets'] if a['role']=='arrow_hint']
    from .arrow_hints import heads_in_crop,_head_pixels
    import cv2
    for a in arrows:
        im=cv2.imread(a['path'],cv2.IMREAD_UNCHANGED);mask=im[:,:,3] if im.ndim==3 and im.shape[2]==4 else None
        heads=invoke('sam_intervention',heads_in_crop,im[:,:,:3],mask);a['head_pixels']=invoke('sam_intervention',_head_pixels,heads);a['detected_heads']=len(heads)
    write_json(run/'arrow-head-evidence.json',[{k:a.get(k) for k in ('id','source_crop','head_pixels','detected_heads')} for a in arrows])
    def public(items):return json.dumps([{k:a[k] for k in ('id','role','source_crop','head_pixels','detected_heads') if k in a} for a in items],ensure_ascii=False)
    prompt=common_prompt(policy)+'\nCanvas: '+f'{W} x {H}'+"\nOutput only a single complete editable SVG. All base frames need stable IDs and data-plus-kind=frame. Native SVG rect positions do not position children; use transforms. Every use must have width/height matching its symbol viewBox. Keep true outer frames, text and borders not covered by replacement. Do not use a full-image screenshot as reconstruction."
    if policy['code_methods']:
        prompt+='\n'+manual()+"\nAvailable first declarations: data-plus-sp is JSON {kind,data} on a stable-ID g; data-plus-crop is original x,y,w,h with data-plus-representation=raster|vector; data-plus-color is JSON mapping fill/stroke to original pixel ROI [x,y,w,h]. Use complete interior ROIs, preserving gradients; omit color declarations on frames and text. Crop declarations must cover the complete independently located original object."
    boards={'images':[],'pictures':[]}
    if policy['sam']:
        from .sam_board import build_boards
        boards=invoke('sam_intervention',build_boards,original,pictures,run/'first-sam-boards')
        prompt+='\nSAM pictures: '+public(pictures)+'\nSAM arrows (head status and dimensions evidence only): '+public(arrows)
        prompt+='\nAttachment order: original, SAM pictures, SAM arrows, annotated overview. Asset mapping: '+json.dumps({a['id']:a['source_id'] for a in boards['pictures']})
        prompt+='\nFor confirmed SAM references use real asset IDs, preserve source_crop x/y/width/height and position with a shared outer group transform. Construct actual visible content first, then declare data-plus-replaces="space-separated construction IDs" and data-plus-keeps="uncovered IDs" on an independent replacement image/group. If true frames are completely covered, list their IDs in data-plus-covered-frames. Replacement and replaced nodes must not contain each other. False positive or uncertain assets need not be used.'
    response=send(prompt,[Path(original)]+[Path(a['path']) for a in pictures+arrows]+boards['images'],run/'gpt55','A-derived native SVG first pass')
    root=parse(response)
    validate_svg_capabilities(root,policy)
    for node in root.iter():
        forbidden=[key for key in ('data-plus-sp','data-plus-crop','data-plus-color') if key in node.attrib and not policy['code_methods']]
        if not policy['sam'] and any(key in node.attrib for key in ('data-plus-sam-group',)):
            forbidden.append('SAM binding')
        if not policy['sam'] and 'data-plus-replaces' in node.attrib and 'data-plus-crop' not in node.attrib:
            forbidden.append('SAM replacement')
        if forbidden:
            trace_event('rejected_request',','.join(forbidden),'rejected',node_id=node.get('id'))
            raise ValueError('disabled declaration: '+','.join(forbidden))
    (run/'before-sam-replacement.svg').write_text(serialize(root))
    from .sam_groups import restore_source_boxes,crop_target_box
    if policy['sam']:
        write_json(run/'first-sam-placement.json',invoke('sam_intervention',restore_source_boxes,root,pictures))
        invoke('sam_intervention',bind_assets,root,{a['id']:a['path'] for a in pictures+arrows})
    # SP declarations are executed by the same registered code used in repair.
    for n in list(root.iter()):
        if n.get('data-plus-sp'):
            spec=json.loads(n.get('data-plus-sp'));part=invoke('code_intervention',sp_element,spec['kind'],spec['data'],n.get('id'));n.extend(list(part));n.attrib.pop('data-plus-sp')
    host_crops={}
    for n in list(root.iter()):
        if n.get('data-plus-crop'):
            vals=[float(v) for v in n.get('data-plus-crop').split(',')]
            oid=n.get('id');declarations={key:n.get(key) for key in ('data-plus-replaces','data-plus-keeps','data-plus-covered-frames','data-plus-kind') if n.get(key) is not None}
            contained_frames={f.get('id') for f in n.iter() if f.get('data-plus-kind')=='frame' and f.get('id')}
            contained_frames.update(fid for f in n.iter() for fid in f.get('data-plus-host-frame-ids','').split())
            args={'source_crop':vals,'target_box':crop_target_box(n,vals),'classification':'photo' if n.get('data-plus-representation')=='raster' else 'complex_geometry'}
            if n.get('data-plus-backend') is not None:args['backend']=n.get('data-plus-backend')
            if n.get('data-plus-remove-background') is not None:
                flag=n.get('data-plus-remove-background')
                if flag not in ('true','false'):raise ValueError('data-plus-remove-background must be true or false')
                args['remove_background']=flag=='true'
            spec={'id':'crop_'+oid,'issue_id':'first','action':'asset','target_ids':[oid], 'args':args}
            root,log=invoke('code_intervention',execute,root,[spec],[{'id':'first','target_ids':[oid]}],original,run)
            node=nodes(root)[oid]
            for key,value in declarations.items():node.set(key,value)
            if contained_frames:node.set('data-plus-host-frame-ids',' '.join(sorted(contained_frames)))
            host_crops[oid]=_host_crop_proof(node,log[0]['result'],original,vals,run)
    color_log=[]
    for node in list(root.iter()):
        if not node.get('data-plus-color'):continue
        oid=node.get('id');samples=json.loads(node.get('data-plus-color'))
        if not isinstance(samples,dict) or not samples or set(samples)-{'fill','stroke'}:raise ValueError('invalid color sampling declaration')
        for attribute,roi in samples.items():
            op={'id':'color_'+oid+'_'+attribute,'issue_id':'first_color_'+oid,'action':'sample_color','target_ids':[oid],'args':{'source_crop':roi,'attribute':attribute}}
            root,log=invoke('code_intervention',execute,root,[op],[{'id':op['issue_id'],'target_ids':[oid]}],original,run/'first-color-tools');color_log.extend(log)
        nodes(root)[oid].attrib.pop('data-plus-color',None)
    from .sam_replace import apply_replacements
    if policy['sam'] or host_crops:
        write_json(run/'first-sam-replacement.json',invoke('sam_intervention' if policy['sam'] else 'code_intervention',apply_replacements,root,host_crops))
    write_json(run/'first-color-execution.json',color_log)
    validate_svg_capabilities(root,policy,terminal=True)
    return root

def run_archive(original,source,rounds=1):
    if rounds not in (0,1):raise ValueError('single-call repair accepts zero or one request')
    run=new_run(PLUS_ROOT/'runs','native');root,proof=archived_first(original,source)
    write_json(run/'provenance.json',proof);(run/'source.svg').write_text(serialize(root))
    write_json(run/'run.json',{'original':str(Path(original).resolve()),'execution_source':'archived-raw-gpt55-native','status':'building','visual_passed':False,'manual_numeric_answers':False})
    stage(root,original,run/'stage-0')
    state=json.loads((run/'run.json').read_text());state.update(latest_stage=str(run/'stage-0'),status='baseline_rendered',baseline_svg_sha256=sha(run/'stage-0/scene.svg'));write_json(run/'run.json',state)
    if rounds:resume(run,rounds)
    return run

def run_image(original,rounds=1):
    if rounds not in (0,1):raise ValueError('single-call repair accepts zero or one request')
    run=new_run(PLUS_ROOT/'runs','native');write_json(run/'run.json',{'original':str(Path(original).resolve()),'execution_source':'native-gpt55','status':'building','visual_passed':False})
    root=first(original,run);stage(root,original,run/'stage-0');state=json.loads((run/'run.json').read_text());state.update(latest_stage=str(run/'stage-0'),status='baseline_rendered',baseline_svg_sha256=sha(run/'stage-0/scene.svg'));write_json(run/'run.json',state)
    if rounds:resume(run,rounds)
    return run

def resume(run,rounds=1,send=call_deepseek):
    if send is call_deepseek:
        if rounds!=1:raise ValueError('single-call repair accepts exactly one request, not rounds')
        from .single_call.runner import prepare,run_prepared
        run=Path(run).resolve();state=json.loads((run/'run.json').read_text())
        if state.get('evaluation_eligible') is False:raise ValueError('assistant-provided image-specific guidance is not a clean input')
        task=run/'single-call'
        if not task.exists():
            # A fresh repair task starts at the GPT-5.5 first-stage output.
            # latest_stage may point to an arbitrarily iterated repair result.
            baseline=Path(state.get('first_stage_source') or run)/'stage-0/scene.svg'
            if not baseline.is_file():raise ValueError('missing first-stage SVG; recover the saved GPT-5.5 response, never use latest_stage')
            expected=state.get('baseline_svg_sha256')
            if expected and sha(baseline)!=expected:raise ValueError('first-stage SVG was overwritten; recover the saved GPT-5.5 response')
            prepare({'image':{'original':state['original'],'svg':str(baseline)}},task)
        result=run_prepared(task)
        # Keep the native stage contract usable for reports without launching a new request.
        latest=run/'stage-single-call'
        stage(parse(Path(result['images']['image']['svg']).read_text()),Path(state['original']),latest)
        state.update(latest_stage=str(latest),status='pending_review',single_call_task=str(task),repair_result=str(task/'result.json'),visual_passed=False)
        write_json(run/'run.json',state);return run
    raise ValueError('custom legacy transports are disabled; use the single-call task entry')


def _resume_offline(run,rounds=2,send=None):
    if send is None or send is call_deepseek:raise ValueError('offline fixture requires an injected non-live transport')
    # Historical fixture protocol only, never selected by the public entry.
    run=Path(run);state=json.loads((run/'run.json').read_text());original=Path(state['original']);current=Path(state['latest_stage']);root=parse((current/'scene.svg').read_text())
    if state.get('evaluation_eligible') is False:
        raise ValueError('This run contains assistant-provided image-specific guidance; restart from the locked first-stage SVG.')
    machine_feedback=None
    used=[int(p.name.split('-')[-1]) for p in run.glob('deepseek-*') if p.name.split('-')[-1].isdigit()];start=max(used,default=0)+1
    seen=set()
    for n in range(start,start+rounds):
        b=json.loads((current/'bounds.json').read_text());frames=json.loads((current/'pack/pack.json').read_text())['frames']
        prompt=(PLUS_ROOT/'prompts/repair.md').read_text()+'\n'+(PLUS_ROOT/'prompts/repair-legacy-guidance.md').read_text()+'\n'+(PLUS_ROOT/'docs/native-tools.md').read_text()+'\n'+manual()
        prompt+='\n原生SVG模式覆盖Scene模式：直接使用现SVG对象ID和原生坐标，不返回Scene。不受构造器限制的既有SVG保持原样。下面原图第一张，当前全图第二张；之后每张图左原右现，标题与frame_id顺序一致。\n'
        prompt+='\nFrame order:'+json.dumps([f['frame_id'] for f in frames])+'\nSVG:'+public_svg(root)
        evidence={i:{k:v for k,v in o.items() if k in ('tag','parent_id','geometry_bbox','world','bounds_complete','effects','text')} for i,o in b['objects'].items()}
        prompt+='\nTP measurements:'+json.dumps(evidence,ensure_ascii=False,separators=(',',':'))
        from .local_tp import build_local_tp
        local_tp=build_local_tp(b,frames,original,current/'preview.png')
        write_json(run/f'local-tp-{n}.json',local_tp)
        prompt+='\nLocal TP coordinate maps:'+json.dumps({'regions':[{k:v for k,v in r.items() if k!='objects'}|{'object_ids':list(r['objects'])} for r in local_tp['regions']],'canvas_to_object_local':local_tp['canvas_to_object_local'],'contract':local_tp['contract']},ensure_ascii=False,separators=(',',':'))

        # Only feedback produced inside this invocation by the executor may enter a request.
        # External files may contain assistant visual diagnoses or hand-authored answers.
        if machine_feedback is not None:
            prompt+='\nAutomatic execution feedback (applied operations are already applied):'+json.dumps(machine_feedback,ensure_ascii=False)
        prompt+='\n最终输出契约优先：issues中每个问题直接放ops数组，操作只需id/action/target_ids/args/depends_on；不要再返回全局ops，也不要手写op_ids或issue_id，宿主自动绑定。没有可执行操作则ops:[]并写unresolved_reason。coverage每行用frame_id/states/evidence，states严格14个C/I/U/N字符。\n'
        prompt+='\n优先完整检查每一个region的14项，列出全部问题；同批解决能解决的，不确定如实记录。只输出native-tools规定JSON。不得用自身检查表宣布通过。'
        images=[original,current/'preview.png']+[Path(f['pair']) for f in frames]
        from .sam_board import review_context
        board_prompt,board_images=review_context(original,root,run,run/f'tools-{n}')
        prompt+=board_prompt;images+=board_images
        prompt+='\n最终输出必须是诊断结果本身：{"coverage":[{"frame_id":"实际ID","states":"14个分类字符","evidence":"实际证据"}],"issues":[{"id":"问题ID","frame_id":"实际ID","category":"问题类别","target_ids":["实际对象ID"],"description":"问题","original_evidence":"原图证据","current_evidence":"现图证据","ops":[],"unresolved_reason":"不能修复时的具体原因"}]}。不要输出{type:json_object}等接口配置。有可执行修复就把native-tools操作放入该issue.ops，数值由你看图及测量推导。'

        raw=send(prompt,images,run/f'deepseek-{n}','native frame diagnosis and TP/SP repair')
        try:
            raw_reply=parse_json(raw);write_json(run/f'repair-{n}.json',raw_reply)
            reply=normalize(raw_reply);write_json(run/f'normalized-{n}.json',reply)
            coverage=coverage_audit(reply,frames);write_json(run/f'coverage-{n}.json',coverage)
            signature=hashlib.sha256((serialize(root)+json.dumps(reply['ops'],sort_keys=True)).encode()).hexdigest()
            if signature in seen:state['status']='repeated_state_and_ops';break
            seen.add(signature)
            candidate,log,local_failures=execute_issues(root,reply,original,run/f'tools-{n}')
            write_json(run/f'execution-{n}.json',log)
            target=run/f'stage-{n}';stage(candidate,original,target);root=candidate;current=target
            feedback={'coverage':coverage,'local_failures':local_failures,'applied_ops':[l['id'] for l in log],'joint_checks':[l for l in log if l.get('joint_relations')],'batch_applied':bool(log),'visual_passed':False}
            write_json(run/'feedback.json',feedback)
            machine_feedback=feedback
            state.update(latest_stage=str(current),status='local_execution_failed' if local_failures else ('needs_visual_review' if coverage['reporting_complete'] else 'coverage_incomplete'),visual_passed=False)
            if not reply['ops'] and coverage['reporting_complete'] and not local_failures:break
        except (ValueError,KeyError,TypeError,IndexError) as e:
            failure={'error_type':type(e).__name__,'error':str(e)[:2400],'batch_applied':False,'visual_passed':False}
            write_json(run/f'failure-{n}.json',failure);write_json(run/'feedback.json',failure);machine_feedback=failure;state.update(status='execution_failed',visual_passed=False)
        finally:write_json(run/'run.json',state)
    return run


def execute_issues(root,reply,original,folder):
    candidate=root;logs=[];failures=[]
    known={i['id'] for i in reply['issues']}
    if any(o.get('issue_id') not in known for o in reply['ops']):raise ValueError('orphan operation')
    for issue in reply['issues']:
        ops=[o for o in reply['ops'] if o.get('issue_id')==issue['id']]
        try:
            audit({'issues':[issue],'ops':ops,'coverage':[]},[],set(nodes(candidate)))
            candidate,log=execute(candidate,ops,[issue],original,folder,reply.get('relations',[]));logs.extend(log)
        except (ValueError,KeyError,TypeError,IndexError) as e:
            failures.append({'issue_id':issue['id'],'error':str(e),'applied':False})
    return candidate,logs,failures
