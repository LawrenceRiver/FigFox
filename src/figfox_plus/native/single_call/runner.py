"""Prepare all images first, send one request, then execute only locally."""
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import xml.etree.ElementTree as ET
from PIL import Image, ImageDraw
from ...state import PLUS_ROOT, write_json
from ...providers_tools import image_content
from ..document import validate, public_svg
from ..tool_repair import snapshot
from .qlist import QLIST, TOLERANCE, markdown
from .contract import PROTOCOL, validate_plan, normalize_plan
from .transport import request_plan
from ..tool_schema import operation as native_operation_schema


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def verify_inputs(folder, manifest):
    for filename,expected in manifest['files'].items():
        if digest(Path(folder)/filename)!=expected:raise ValueError('prepared input changed: '+filename)


def _pairs(snap, original, folder):
    """Same shared diagnostic region, each side normalized to one display size."""
    folder.mkdir(parents=True,exist_ok=True);out=[]
    for index,frame in enumerate(snap['frames']):
        images=[]
        for label,path in [('original',original),('current',snap['folder']/'preview.png')]:
            from ..tool_repair import world_crop
            dest=folder/f'{index:03d}-{label}.png'
            mapping=world_crop(path,frame['canvas_crop'],snap['tp']['canvas'],dest,
                               tp=snap['tp'] if label=='current' else None,label=label)
            with Image.open(dest) as im:images.append(im.convert('RGB').copy())
        w,h=images[0].size
        scale=min(3,max(1,1000/max(w,h)));size=(round(w*scale),round(h*scale))
        plate=Image.new('RGB',(2*size[0]+12,size[1]+30),'white')
        draw=ImageDraw.Draw(plate);draw.text((4,5),'ORIGINAL',fill='black');draw.text((size[0]+16,5),'CURRENT',fill='black')
        for i,im in enumerate(images):plate.paste(im.resize(size),(i*(size[0]+12),30))
        path=folder/f'{index:03d}-pair.png';plate.save(path)
        out.append({'id':frame['frame_id'],'path':str(path.resolve()),
                    'shared_diagnostic_region':frame['canvas_crop'],'display_size_each':list(size),
                    'purpose':'diagnostic_pair_only_not_material_source_crop'})
    return out


def prepare(sources, task_dir, *, observation='balanced_tiles_v1', prompt_profile='concise_v2', mechanical_hints=True, geometry_hints=False):
    if observation not in {'frames_v0','balanced_tiles_v1','fine_tiles_v4'}:raise ValueError('unknown observation strategy')
    if prompt_profile not in {'complete_v0','concise_v2'}:raise ValueError('unknown prompt profile')
    if not isinstance(sources,dict) or not sources:raise ValueError('sources must contain all task images')
    task_dir=Path(task_dir).resolve();task_dir.mkdir(parents=True,exist_ok=False)
    images={};content=[];files=[]
    for index,(image_id,source) in enumerate(sources.items()):
        if not isinstance(image_id,str) or not image_id or not isinstance(source,dict):raise ValueError('invalid image source')
        if set(source)-{'original','svg','current'}:raise ValueError('only clean original/current source fields accepted')
        original=Path(source['original']);svg=Path(source.get('svg') or Path(source['current']).parent/'scene.svg')
        folder=task_dir/f'image-{index:03d}';folder.mkdir()
        frozen=folder/'original.png';shutil.copyfile(original,frozen)
        root=ET.fromstring(svg.read_text());validate(root)
        snap=snapshot(root,frozen,folder/'baseline')
        if observation in {'balanced_tiles_v1','fine_tiles_v4'}:
            from .observation import balanced_pairs
            options={'edge':256,'zoom':4} if observation=='fine_tiles_v4' else {}
            pairs=balanced_pairs(frozen,snap['folder']/'preview.png',snap['tp']['canvas'],folder/'paired-crops',**options)
        else:
            pairs=_pairs(snap,frozen,folder/'paired-crops')
        regions=[p['id'] for p in pairs] or ['full']
        info={'revision':snap['revision'],'original':str(frozen),'svg':str(snap['folder']/'scene.svg'),
              'current_png':str(snap['folder']/'preview.png'),'region_ids':regions,
              'object_ids':[n.get('id') for n in root.iter() if n.get('id')],
              'parents':{r['id']:r.get('parent') for r in snap['rows']},'folder':str(folder)}
        images[image_id]=info
        rows=snap['rows']
        if prompt_profile=='concise_v2':
            rows=[{k:v for k,v in r.items() if k!='attributes'} for r in rows]
        payload={'image_id':image_id,'revision':snap['revision'],'current_svg':public_svg(root),
                 'current_tp':{'domain':'current_svg_world','canvas':snap['tp']['canvas'],'objects':rows},
                 'paired_crops':[{k:v for k,v in p.items() if k!='path'} for p in pairs],
                 'region_ids':regions}
        with Image.open(frozen) as im:payload['original_pixel_size']=list(im.size)
        if mechanical_hints:
            from .diagnostics import current_diagnostics
            payload['current_mechanical_candidates']=current_diagnostics(root,snap['tp'])
            if geometry_hints:
                from .geometry_observations import geometry_observations
                payload['current_mechanical_candidates'].update(geometry_observations(root))
            write_json(folder/'current-mechanical-candidates.json',payload['current_mechanical_candidates'])
        metadata={'type':'text','text':json.dumps(payload,ensure_ascii=False)}
        if observation!='fine_tiles_v4':content.append(metadata)
        paths=[frozen,Path(info['current_png'])]+[Path(p['path']) for p in pairs]
        blocks=image_content(paths,folder/'attachments')
        labels=['original_full','current_full']+[p['id']+' original_left_current_right' for p in pairs]
        for i,label in enumerate(labels):blocks[2*i]['text']=json.dumps({'image_id':image_id,'role':label},ensure_ascii=False)
        content.extend(blocks)
        if observation=='fine_tiles_v4':content.append(metadata)
        files.extend([frozen,Path(info['svg']),Path(info['current_png'])]+[Path(p['path']) for p in pairs])
    if prompt_profile=='concise_v2':
        from ...sp.catalog import serializable_catalog
        cards=[{k:c[k] for k in ('name','forward_description','parameters','preconditions')}
               for c in serializable_catalog() if c['name']!='group']
        prompt=(PLUS_ROOT/'prompts/single-call-concise.md').read_text()+'\n'+markdown()+'\n'+PROTOCOL+'\nSP data 参数卡：'+json.dumps(cards,ensure_ascii=False)
    else:
        prompt=(PLUS_ROOT/'prompts/single-call-plan.md').read_text()+'\n'+markdown()+'\n'+PROTOCOL
    if mechanical_hints:
        prompt+='\n现图机械候选检查：逐条核对 current_mechanical_candidates 的边界和开放填充候选。它们由现图通用代码计算，不是人工答案，也不证明原图关系。回看原图判断是否合法、该改谁；真实轮廓才是依据。尤其不要只根据对象仍能辨认就忽略结构变化。继续检查未列出的其他对象。额外输出 mechanical_review 数组，每条含 image_id、subject_id（或 source_id）、verdict=confirmed/clear/uncertain 和简短 evidence。只有确认的缺陷加入 issues，机械候选本身不自动进入 Ask_data。'
    if geometry_hints:
        prompt+='\n还需核对 shared_face_overlap_candidates 与 parallel_group_candidates：前者表示同层凸多边形共边却内部相交，若它们应是同一不透明立体的可见面，就要检查面连接和投影而不仅改填色；若原图是合法层叠则保留。后者给出同一起线的平行箭头及镜像长度差，先查原图是否要求成组对称，再决定E/D/C问题。数字事实本身不是原图意图，不能自动确认缺陷。'
    capabilities={'server_side_sandbox':False,'arbitrary_python':False,'bp_module_program':True,
                  'semantic_crop_loop':False,'visual_soft_acceptance':'pending_human_review',
                  'local_modules':['TP','SP','BP','OpenCV colors','RMBG','render','paired alarms']}
    content.insert(0,{'type':'text','text':json.dumps({'input_slots':list(range(1,13)),
        'qlist':QLIST if prompt_profile=='complete_v0' else 'system Q list A–F,S1–S4','tolerance':TOLERANCE,'capabilities':capabilities,
        'input_revisions':{im:obj['revision'] for im,obj in images.items()},
        'ask_data_contract':PROTOCOL if prompt_profile=='complete_v0' else 'system EXECUTABLE single-call-v1 contract',
        'native_operation_schema':native_operation_schema,
        'reconstructor':{'module':'figfox_plus.native.single_call.executor.execute_plan',
            'code_template':'from figfox_plus.native.single_call.executor import execute_plan\nresult = execute_plan(response, manifest, task_dir)',
            'parameters':['response: complete single-call-v1 JSON','manifest: frozen prepared inputs','task_dir: host directory'],
            'composition':'response.ask_data is the per-object ordered module program; it is not a fixed scene repair'},
        'preconstructor':{'phase':'preconstructor','method':'bp_program',
            'args_contract':{'operations':'array of native_operation_schema'},
            'execution':'atomic local module program; can compose SP construction, SVG additions/patches and TP operations'},
        'input_inventory':{
            '1':'paired_crops original side; shared diagnostic region',
            '2':'current_svg source', '3':'current_full regenerated PNG','4':'original_full PNG',
            '5':'paired_crops current side; same region and display format',
            '6':'current_tp plus TP rules and alarm code in system material',
            '7':'SP constructor reference in system material','8':'native_operation_schema and BP program contract',
            '9':'qlist plus tolerance','10':'ask_data_contract','11':'reconstructor code template and module contract',
            '12':'preconstructor program interface'}},ensure_ascii=False)})
    messages=[{'role':'system','content':prompt},{'role':'user','content':content}]
    write_json(task_dir/'messages.json',messages);files.append(task_dir/'messages.json')
    manifest={'version':'single-call-input-v1','request_budget':1,'input_slots':list(range(1,13)),
              'observation_strategy':observation,
              'prompt_profile':prompt_profile,
              'mechanical_hints':mechanical_hints,
              'geometry_hints':geometry_hints,
              'images':images,'capabilities':capabilities,'files':{str(p.relative_to(task_dir)):digest(p) for p in files}}
    write_json(task_dir/'input-manifest.json',manifest)
    return manifest


def run_prepared(task_dir, *, send=None, execute=True):
    task_dir=Path(task_dir).resolve()
    with (task_dir/'run.lock').open('a') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        manifest=json.loads((task_dir/'input-manifest.json').read_text());verify_inputs(task_dir,manifest)
        # Reopen an existing response only for local execution. Never re-send.
        path=task_dir/'response-plan.json'
        plan=json.loads(path.read_text()) if path.exists() else request_plan(json.loads((task_dir/'messages.json').read_text()),task_dir,send=send)
        from .compiler import compile_plan
        plan,compilation=compile_plan(plan,manifest)
        write_json(task_dir/'compilation.json',compilation)
        write_json(task_dir/'normalization.json',{'changes':compilation['normalizations'],'raw_response_preserved':True})
        validate_plan(plan,manifest);write_json(task_dir/'validated-plan.json',plan)
        if not execute:return plan
        from .executor import execute_plan
        return execute_plan(plan,manifest,task_dir)


def execute_saved(task_dir):
    task_dir=Path(task_dir).resolve()
    if not (task_dir/'response-plan.json').exists():raise ValueError('no saved response; execute never calls API')
    return run_prepared(task_dir,execute=True)


def execute_saved_safe_parts(task_dir):
    """Explicit isolated trial; never calls a model or reads acceptance labels."""
    from .compiler import compile_plan
    from .executor import execute_plan
    task_dir=Path(task_dir).resolve()
    manifest=json.loads((task_dir/'input-manifest.json').read_text());verify_inputs(task_dir,manifest)
    raw=json.loads((task_dir/'response-plan.json').read_text())
    plan,report=compile_plan(raw,manifest)
    write_json(task_dir/'compilation.json',report);write_json(task_dir/'execution-plan.json',plan)
    return execute_plan(plan,manifest,task_dir)


def replay_saved(task_dir, replay_dir):
    """Replay immutable model output after a generic adapter fix; zero model calls."""
    source=Path(task_dir).resolve();dest=Path(replay_dir).resolve()
    manifest=json.loads((source/'input-manifest.json').read_text());verify_inputs(source,manifest)
    if not (source/'response-plan.json').exists():raise ValueError('local replay needs a saved response')
    dest.mkdir(parents=True,exist_ok=False)
    write_json(dest/'local-replay.json',{'source':str(source),'model_calls_allowed':0,
        'response_sha256':digest(source/'response-plan.json')})
    for relative in manifest['files']:
        src=(source/relative).resolve()
        if not src.is_relative_to(source):raise ValueError('input manifest path escapes source')
        target=dest/relative;target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(src,target)
    shutil.copyfile(source/'response-plan.json',dest/'response-plan.json')
    for im in manifest['images'].values():
        for key in ('original','svg','current_png','folder'):
            im[key]=str(dest/Path(im[key]).relative_to(source))
    manifest['request_budget']=0
    write_json(dest/'input-manifest.json',manifest)
    return execute_saved(dest)
