"""End-to-end Plus orchestration. Only a separate visual review can pass a run."""
import json
from copy import deepcopy
import re
import hashlib
from pathlib import Path
from PIL import Image
from .state import PLUS_ROOT,new_run,write_json
from .sam import prepare_assets
from .assets import crop_asset, remove_background_asset
from .vectorize import vectorize_asset
from .sp.catalog import manual
from .sp.compiler import compile_scene
from .render import measure
from .providers import call_gpt55,call_deepseek
from .pack import build_pack
from .executor import execute,descendants
from .tp.transforms import normalize_frame_origins
from .model_evidence import compact_evidence,public_scene

SCHEMA='''Scene={version:"plus-0.1",canvas:{width,height},objects:[{id,name,kind,parent_id:null,data,matrix:[1,0,0,1,0,0]}],relations:[{id,subject_ids,object_ids,predicate,params,description,priority}],assets:[]}. kind only frame/geometry/text/formula/arrow/picture/vector_asset/group; geometry constructors go in data.shape. All coordinates are local to parent unless matrix transforms. Preserve all text, formulas and frame-outside elements. Relations need actual image evidence. Do not invent alignment. picture/vector_asset data={asset_id,x,y,width,height}; retain source crop separately. Geometry may use rect/ellipse/polygon/cuboid/cylinder/array/cluster/lattice. Assets are compiled locally, no external URLs or arbitrary code.'''


def parse_json(text):return json.loads(re.sub(r'^```(?:json)?\s*|\s*```$','',text.strip()))


def fulfill(scene,requests,original,folder,*,remove_background=False):
    assets={a['id']:a for a in scene.get('assets',[])}
    for req in requests:
        aid=req['asset_id']
        if aid in assets:raise ValueError('crop would overwrite asset ID')
        if not any(o.get('data',{}).get('asset_id')==aid for o in scene['objects']):raise ValueError('crop has no target object')
        asset=crop_asset(original,req['source_crop'],folder)
        if remove_background:asset=remove_background_asset(asset,folder)
        if req.get('representation','raster')=='vector':asset=vectorize_asset(asset,req.get('backend','imagetracerjs'),folder)
        asset['id']=aid;assets[aid]=asset
    scene['assets']=list(assets.values());return scene


def render_stage(scene,folder,original):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    svg,index=compile_scene(scene);(folder/'scene.svg').write_text(svg);write_json(folder/'scene.json',scene)
    bounds=measure(svg,index,folder/'preview.png');write_json(folder/'bounds.json',bounds)
    pack=build_pack(original,folder/'preview.png',scene,bounds,folder/'pack')
    return pack


def first_pass(original,run,send=call_gpt55,sam=None):
    if send is call_gpt55:
        raise ValueError('Legacy Scene first pass retired; use native.pipeline.run_image for the shared first-stage prompt')
    original=Path(original)
    sam=prepare_assets(original,PLUS_ROOT/'runs/sam-cache') if sam is None else sam
    write_json(run/'sam.json',sam)
    with Image.open(original) as im:W,H=im.size
    public_assets=[{k:v for k,v in a.items() if k in ('id','source_crop','role','representation')} for a in sam['assets']]
    prompt=(PLUS_ROOT/'prompts/first_pass.md').read_text().replace('{{CANVAS}}',f'{W} x {H}').replace('{{ARROW_LIBRARY}}',json.dumps(public_assets,ensure_ascii=False))
    prompt+='\n'+SCHEMA+'\n'+manual()+'\n'+(PLUS_ROOT/'docs/tp-manual.md').read_text()+'\n'+(PLUS_ROOT/'docs/observation-protocol.md').read_text()
    prompt+='\nCoordinate declaration required: set scene.coordinate_space to frame-origin if child coordinates are relative to the top-left of their parent rect frame, or svg-parent if frame x/y does NOT offset child coordinates. Prefer frame-origin consistently for nested rect frames. Do not mix.\n'
    prompt+='\nImage order: full original, then SAM assets in listed order. SAM may miss objects or detect letters as arrows. assets field may be [] as host attaches existing assets.\n'+json.dumps(public_assets,ensure_ascii=False)
    response=parse_json(send(prompt,[original]+[Path(a['path']) for a in sam['assets']],run/'gpt55','formal first pass'))
    scene=normalize_frame_origins(response['scene']);scene['assets']=sam['assets']  # host-owned paths; never accept model-supplied filesystem paths
    if scene['canvas']!={'width':W,'height':H}:raise ValueError('model canvas differs from input dimensions')
    write_json(run/'first-response.json',response)
    scene=fulfill(scene,response.get('crop_requests',[]),original,run/'assets')
    render_stage(scene,run/'stage-0',original);return scene


def repair(original,scene,run,max_rounds=3,send=call_deepseek,start_round=1):
    raise ValueError('legacy multi-round repair disabled; use native single-call repair-prepare / repair-once')


def _repair_offline(original,scene,run,max_rounds=3,send=call_deepseek,start_round=1):
    if send is call_deepseek:
        raise ValueError('legacy multi-round repair disabled; use native single-call repair-prepare / repair-once')
    history=run/'repair-history.json'
    seen=set(json.loads(history.read_text())) if history.exists() else set()
    current=scene;last_stage=run/f'stage-{start_round-1}'
    used=[int(p.name.split('-')[-1]) for p in run.glob('deepseek-*') if p.name.split('-')[-1].isdigit()]
    start_round=max([start_round]+[n+1 for n in used])
    for number in range(start_round,start_round+max_rounds):
        pack=json.loads((last_stage/'pack/pack.json').read_text())
        images=[Path(original),last_stage/'preview.png']
        labels=['full original','full current']
        for frame in pack['frames']:
            for im in frame['images']:images.append(Path(im['path']));labels.append(frame['frame_id']+' '+im['label'])
        prompt='''Compare original/current images and frame crops. Diagnose freely: omissions, text, formulas, geometry/count/projection, arrows and connections, photos, frame-inside/outside relationships. Return ONLY {checks:[{id,target_ids,status:pass|uncertain,evidence}],issues:[{id,target_ids,description,evidence,op_ids,unresolved_reason?}],ops:[{id,issue_id,action,target_ids,args,depends_on:[]}],crop_requests:[]}. Each operation must reference an issue and real targets; create may introduce one fresh ID under an issue-scoped parent using args.object; missing-object issues target the existing parent frame; unknown problems must remain unresolved. Use currently registered tools; if insufficient, record extension_request and unresolved_reason for a scoped local SVG/sandbox extension. Do not invoke unregistered code in this operation batch. Do not claim success from alert counts. Aim at immediately usable output: slight unobtrusive displacement acceptable; incorrect arrows, missing text or frame relationships not acceptable. Empty ops is only ready for human visual review, not passed.\n'''+SCHEMA+'\n'+manual()+'\n'+(PLUS_ROOT/'docs/tp-manual.md').read_text()
        prompt+='\nPut normal findings in checks with status pass; uncertain observations use status uncertain. Only actual defects belong in issues. Neither passing checks nor empty issues imply final visual acceptance.\n'
        feedback=run/'repair-feedback.json'
        if feedback.exists():prompt+='\nPrevious local execution failure (fix the cause, do not repeat blindly):'+feedback.read_text()
        prompt+='\n'+(PLUS_ROOT/'prompts/repair.md').read_text()+'\n'
        prompt+='\nAsset fallback: reconstruct an existing geometry using args={kind:vector_asset,data:{asset_id,x,y,width,height}}, plus crop_requests=[{asset_id,source_crop:[x,y,w,h],representation:vector,backend:imagetracerjs}]. Source crop is original-image absolute coordinates; target placement stays object-local. Use picture/raster for ordinary photos. Preserve ID,parent,matrix; never cover neighbors or replace whole image. Before text-only edits, compare every region for lost texture, missing faces, counts, projection and connections. Do not claim a character absent when present in the scene and image. Missing-object create issues must target its existing parent frame.\n'
        review=run/'visual-feedback.json'
        if review.exists():
            note=json.loads(review.read_text())
            if note.get('quantitative_answers_provided') is not False:raise ValueError('visual feedback must not provide quantitative answers')
            prompt+='\nAssistant qualitative visual review only; infer every correction value yourself from the reference:\n'+json.dumps(note,ensure_ascii=False)
        prompt+='\nImage order:'+json.dumps(labels,ensure_ascii=False)+'\nScene:'+json.dumps(public_scene(current),ensure_ascii=False,separators=(',',':'))+'\nEvidence:'+json.dumps(compact_evidence(pack),ensure_ascii=False,separators=(',',':'))
        prompt+='''\nExecutable operation contract reminder: reconstruct requires EXACTLY ONE existing target and args.data containing that object's COMPLETE data; retain unspecified geometry values by reading current Scene, not by returning partial data. To change an arrow's thickness/head/dash, use reconstruct, not reroute. reroute requires EXACTLY ONE arrow and only route/waypoints/radius; no style fields. translate permits several targets and args.dx/dy. align uses reference_ids/mode; scale uses sx/sy/pivot. Every op.id must occur in its own issue.op_ids; multiple operations require multiple IDs. A vector_asset needs a real vector source or a NEW crop_request with representation=vector. Unknown texture parameters do not create texture: use a local asset. If a previous batch failed, NONE of its proposed operations were applied. The current image is the actual executed state, not your intended fix.\n'''
        raw_response=send(prompt,images,run/f'deepseek-{number}','formal batch repair')
        try:
            response=parse_json(raw_response)
            write_json(run/f'repair-{number}.json',response)
            for check in response.get('checks',[]):
                if check.get('status') not in ('pass','uncertain') or not check.get('evidence'):raise ValueError('invalid check status/evidence')
                if not check.get('target_ids') or not set(check['target_ids']) <= {o['id'] for o in current['objects']}:raise ValueError('unknown check target')
            write_json(run/f'checks-{number}.json',response.get('checks',[]))
            issues=response['issues'];ops=response['ops'];by_issue={i['id']:i for i in issues}
            if len(by_issue)!=len(issues):raise ValueError('duplicate issue ID')
            objects={o['id']:o for o in current['objects']};scope=set()
            for issue in issues:
                if not issue.get('description') or not issue.get('evidence'):raise ValueError('issue missing evidence')
                if not issue.get('target_ids') or not set(issue['target_ids'])<=objects.keys():raise ValueError('unknown issue target')
                scope.update(*[descendants(i,objects) for i in issue['target_ids']])
                if not issue.get('op_ids') and not issue.get('unresolved_reason'):raise ValueError('issue needs operations or unresolved reason')
            scope.update(o['id'] for o in objects.values() if o['kind']=='arrow' and any(o['data'].get(e,{}).get('object_id') in scope for e in ('start','end')))
            for op in ops:
                issue=by_issue.get(op.get('issue_id'))
                if issue is None or op['id'] not in issue['op_ids']:raise ValueError('operation not bound to issue')
            if not ops:
                if feedback.exists():feedback.unlink()
                return current,last_stage,'needs_review' if not issues else 'unresolved'
            signature=hashlib.sha256(json.dumps([current,ops],sort_keys=True).encode()).hexdigest()
            if signature in seen:return current,last_stage,'repeated_state_and_ops'
            seen.add(signature)
            write_json(history,sorted(seen))
            prepared=deepcopy(current)
            planned=deepcopy(current)
            for op in ops:
                if op['action']=='create':
                    new=op['args']['object']
                    if new.get('parent_id') not in scope:raise ValueError('new object must attach to an issue-scoped parent')
                    if new['id'] in objects:raise ValueError('create cannot overwrite existing object')
                    scope.add(new['id']);planned['objects'].append(new)
            for op in ops:
                if op['action']=='reconstruct' and op['args'].get('kind') in ('picture','vector_asset'):
                    for obj in planned['objects']:
                        if obj['id'] in op['target_ids']:
                            obj['data']=deepcopy(op['args']['data'])
            planned=fulfill(planned,response.get('crop_requests',[]),original,run/'assets',remove_background=True)
            prepared['assets']=planned['assets']
            candidate,log=execute(prepared,ops,scope)
            candidate_stage=run/f'stage-{number}';render_stage(candidate,candidate_stage,original);write_json(candidate_stage/'execution.json',log)
            last_stage=candidate_stage
            if feedback.exists():feedback.unlink()
            current=candidate
            state_path=run/'run.json'
            if state_path.exists():
                state=json.loads(state_path.read_text());state.update(latest_stage=str(last_stage),status='repairing',visual_passed=False);write_json(state_path,state)
        except (ValueError,KeyError,TypeError) as error:
            failure={'round':number,'error_type':type(error).__name__,'error':str(error)[:2000],'latest_stage':str(last_stage),'batch_applied':False,'visual_passed':False}
            write_json(run/f'failure-{number}.json',failure);write_json(feedback,failure)
            if number==start_round+max_rounds-1:return current,last_stage,'execution_failed'
    return current,last_stage,'round_limit_needs_review'


def run_image(original,max_rounds=3,send_first=call_gpt55,send_repair=call_deepseek,sam=None):
    source='real-model' if send_first is call_gpt55 and send_repair is call_deepseek and sam is None else 'injected-test-transport'
    run=new_run(PLUS_ROOT/'runs','formal' if source=='real-model' else 'fixture')
    base=dict(original=str(Path(original).resolve()),execution_source=source,visual_passed=False)
    write_json(run/'run.json',dict(base,status='running'))
    print('RUN '+str(run),flush=True)
    try:
        scene=first_pass(original,run,send_first,sam)
        write_json(run/'run.json',dict(base,status='first_pass_complete',latest_stage=str(run/'stage-0')))
        current,stage,status=_repair_offline(original,scene,run,max_rounds,send_repair)
        write_json(run/'run.json',dict(base,status=status,latest_stage=str(stage)))
    except Exception as error:
        state=json.loads((run/'run.json').read_text());state.update(status='failed',error_type=type(error).__name__,error=str(error)[:1000]);write_json(run/'run.json',state);raise
    return run
