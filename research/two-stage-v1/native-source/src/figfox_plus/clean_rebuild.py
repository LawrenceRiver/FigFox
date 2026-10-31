"""Rebuild solely from saved raw model text, SAM assets and fresh model decisions."""
import argparse
from copy import deepcopy
import hashlib,json,math
from pathlib import Path
from .state import PLUS_ROOT,new_run,write_json
from .pipeline import parse_json,fulfill,render_stage,repair,SCHEMA
from .providers import call_deepseek
from .tp.transforms import normalize_frame_origins


def digest(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def load_original(source):
    source=Path(source).resolve()
    if 'quarantine' in source.parts:raise ValueError('quarantine cannot be a reconstruction source')
    raw=source/'gpt55/response.txt';response=parse_json(raw.read_text())
    sam_path=source/'sam.json';sam=json.loads(sam_path.read_text())
    for a in sam['assets']:
        if 'quarantine' in Path(a['path']).resolve().parts:raise ValueError('quarantine asset rejected')
    return response['scene'],sam,{'raw_response':str(raw),'raw_sha256':digest(raw),'sam_manifest':str(sam_path),'sam_sha256':digest(sam_path),'intermediate_scene_used':False,'manual_answer_used':False}


def apply_coordinate_response(scene,response):
    out=deepcopy(scene);objects={o['id']:o for o in out['objects']}
    dialect=response.get('coordinate_space')
    if dialect not in ('frame-origin','svg-parent'):raise ValueError('model must declare coordinate_space')
    out['coordinate_space']=dialect
    seen=set()
    for item in response.get('child_origins',[]):
        oid=item['id'];origin=item['origin']
        if oid not in objects or objects[oid]['kind']!='frame' or oid in seen:raise ValueError('unknown/duplicate frame origin')
        if not isinstance(origin,list) or len(origin)!=2 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in origin):raise ValueError('invalid model child origin')
        objects[oid]['child_origin']=origin;seen.add(oid)
    seen=set()
    for patch in response.get('object_patches',[]):
        oid=patch['id']
        if oid not in objects or oid in seen or set(patch)-{'id','matrix','data','parent_id'}:raise ValueError('invalid coordinate patch target/fields')
        if 'parent_id' in patch and patch['parent_id'] is not None and patch['parent_id'] not in objects:raise ValueError('unknown parent')
        for k in ('matrix','data','parent_id'):
            if k in patch:objects[oid][k]=deepcopy(patch[k])
        seen.add(oid)
    return out


def rebuild(source,rounds=2):
    source=Path(source).resolve();scene,sam,provenance=load_original(source)
    request=json.loads((source/'gpt55/request.json').read_text());original=Path(request['images'][0]['path'])
    if digest(original)!=request['images'][0]['sha256']:raise ValueError('original image hash changed')
    run=new_run(PLUS_ROOT/'runs','api-only');print('RUN '+str(run),flush=True)
    state={'original':str(original),'source_run':str(source),'execution_source':'raw-api-rebuild','status':'coordinate_request','latest_stage':None,'visual_passed':False,'provenance':provenance,'manual_answer_used':False}
    write_json(run/'run.json',state);write_json(run/'source-scene.json',scene);write_json(run/'sam.json',sam);write_json(run/'provenance.json',provenance)
    prompt='''Resolve only the coordinate dialect of this original model-produced Scene against the original reference image. You, the API, must decide all numeric values; no human coordinate answers are provided. Preserve object IDs, content and overall design. Return JSON {coordinate_space:"frame-origin"|"svg-parent",child_origins:[{id,origin:[x,y]}],object_patches:[{id,matrix?,data?,parent_id?}],reasoning:"..."}. object_patches data replaces the COMPLETE object data; omit unnecessary patches. Do not return a new full Scene. frame-origin means each child inherits its parent rect x/y in addition to the parent's matrix; nonrect frames REQUIRE explicit child_origin. svg-parent means frame x/y does not offset child coordinates. Resolve mixed conventions using patches if needed. A polygon's bounding-box minimum is not necessarily the intended origin: inspect the image and its model coordinates. Do not invent a correction if the existing convention is valid. No arbitrary code/paths.\n'''+SCHEMA+'\nOriginal saved model Scene:\n'+json.dumps(scene,ensure_ascii=False,separators=(',',':'))
    try:
        answer=parse_json(call_deepseek(prompt,[original],run/'deepseek-coordinate','coordinate convention recovery from original API response'))
        write_json(run/'coordinate-response.json',answer)
        resolved=apply_coordinate_response(scene,answer);write_json(run/'resolved-input.json',resolved)
        canonical=normalize_frame_origins(resolved);canonical['assets']=sam['assets']
        raw=parse_json((source/'gpt55/response.txt').read_text())
        canonical=fulfill(canonical,raw.get('crop_requests',[]),original,run/'assets')
        render_stage(canonical,run/'stage-0',original)
        state.update(status='first_pass_rebuilt',latest_stage=str(run/'stage-0'));write_json(run/'run.json',state)
        _,stage,status=repair(original,canonical,run,rounds)
        state.update(status=status,latest_stage=str(stage.resolve()));write_json(run/'run.json',state)
    except Exception as e:
        current=json.loads((run/'run.json').read_text());current.update(status='failed',error_type=type(e).__name__,error=str(e)[:2000],visual_passed=False);write_json(run/'run.json',current);raise
    return run

if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',required=True);p.add_argument('--rounds',type=int,default=2,choices=range(4));args=p.parse_args();print(rebuild(args.source,args.rounds))


def retry_coordinates(run,rounds=2):
    """Explicitly requested, ledger-counted second coordinate attempt; no hidden retry."""
    run=Path(run).resolve();state=json.loads((run/'run.json').read_text());scene=json.loads((run/'source-scene.json').read_text());sam=json.loads((run/'sam.json').read_text())
    if state.get('execution_source')!='raw-api-rebuild' or state.get('manual_answer_used') is not False:raise ValueError('not a clean API rebuild')
    raw=Path(state['provenance']['raw_response'])
    if digest(raw)!=state['provenance']['raw_sha256']:raise ValueError('original API response changed')
    required=[{'frame_id':o['id'],'shape':o['data'].get('shape'),'children':[c['id'] for c in scene['objects'] if c.get('parent_id')==o['id']]} for o in scene['objects'] if o['kind']=='frame' and o['data'].get('shape')!='rect' and any(c.get('parent_id')==o['id'] for c in scene['objects'])]
    previous=json.loads((run/'coordinate-response.json').read_text())
    prompt='''Your previous coordinate response could not compile. Return a COMPLETE revised coordinate response applied to the ORIGINAL Scene below, not a patch to your last response. JSON {coordinate_space:"frame-origin"|"svg-parent",child_origins:[{id,origin:[x,y]}],object_patches:[{id,matrix?,data?,parent_id?}],reasoning:"..."}. When choosing frame-origin, EVERY nonrect parent with children must have explicit child_origin. Infer its values yourself from original image and original Scene, no human values will be supplied. Rect frames use their own x/y automatically. For root objects there is no parent offset. Check whether your previous object patches were justified, do not move already-correct routes. All coordinates must come from your analysis. No arbitrary paths or code.\nCompiler error: '''+state.get('error','coordinate failure')+'\nAutomatically enumerated nonrect parents:\n'+json.dumps(required)+'\nPrevious failed response:\n'+json.dumps(previous)+'\nOriginal Scene:\n'+json.dumps(scene,separators=(',',':'))
    folder=run/'deepseek-coordinate-2'
    if folder.exists():raise ValueError('second coordinate attempt already exists; inspect it, do not overwrite')
    answer=parse_json(call_deepseek(prompt,[Path(state['original'])],folder,'explicit second coordinate attempt with compiler evidence'))
    write_json(run/'coordinate-response-2.json',answer)
    resolved=apply_coordinate_response(scene,answer);write_json(run/'resolved-input-2.json',resolved)
    canonical=normalize_frame_origins(resolved);canonical['assets']=sam['assets'];source=parse_json(raw.read_text());canonical=fulfill(canonical,source.get('crop_requests',[]),state['original'],run/'assets')
    render_stage(canonical,run/'stage-0',state['original'])
    state.update(status='first_pass_rebuilt',latest_stage=str(run/'stage-0'));state.pop('error',None);state.pop('error_type',None);write_json(run/'run.json',state)
    _,stage,status=repair(state['original'],canonical,run,rounds)
    state.update(status=status,latest_stage=str(stage.resolve()));write_json(run/'run.json',state)
    return run
