"""Closed-loop local tool execution, with real model tool calls and saved evidence."""
import base64,hashlib,html,json,math,time,xml.etree.ElementTree as ET
from copy import deepcopy
from pathlib import Path
from PIL import Image,ImageDraw
from .document import serialize,validate,measure,public_svg,tag
from .pack import build
from .tight_tp import measure_tight,union_tight
from .tool_schema import TOOLS
from .diagnosis import CATEGORIES
from ..providers_tools import image_content,send_deepseek_tools,redact
from ..state import PLUS_ROOT,write_json
from ..sp.catalog import manual

def revision(root):return hashlib.sha256(serialize(root).encode()).hexdigest()
def read(p):return json.loads(Path(p).read_text())

def repair_progress(diagnosis, calls):
    """Execution coverage only. A changed SVG is never a visual acceptance."""
    ids = set((diagnosis or {}).get('confirmed_ids', []))
    attempted, changed, latest = set(), set(), {}
    for call in calls:
        if call.get('name') != 'apply_repairs':
            continue
        arguments = call.get('arguments') or {}
        if not isinstance(arguments, dict):
            # Preserve the malformed-call error in the tool log without letting
            # progress bookkeeping crash after the executor has returned it.
            continue
        result = call.get('result') or {}
        entries = result.get('issues', [])
        if result.get('error'):
            entries = [{'id':i.get('id'), 'status':'error', 'errors':[result.get('detail','')]} 
                       for i in arguments.get('issues', []) if isinstance(i,dict)]
        for entry in entries:
            oid = entry.get('id')
            if oid not in ids:
                continue
            attempted.add(oid)
            mutated = entry.get('status') == 'applied' and bool(entry.get('baseline_revision')) and entry.get('baseline_revision') != entry.get('resulting_revision')
            if mutated:
                changed.add(oid)
            latest[oid] = {'status':'changed_unverified' if mutated else ('no_change' if entry.get('status')=='applied' else 'failed'), 'errors':entry.get('errors', [])}
    return {'unattempted':sorted(ids-attempted),
            'failed':sorted(i for i,v in latest.items() if v['status']=='failed'),
            'no_change':sorted(i for i,v in latest.items() if v['status']=='no_change'),
            'changed_unverified':sorted(changed), 'latest_execution':latest,
            'visual_acceptance':False}

def object_table(root,tp):
    parents={c:p for p in root.iter() for c in p};rows=[]
    for n in root.iter():
        oid=n.get('id');o=tp['objects'].get(oid)
        if not o:continue
        attrs={k:v for k,v in n.attrib.items() if k not in ('id','d','points','href','{http://www.w3.org/1999/xlink}href')}
        rows.append({'id':oid,'tag':tag(n),'parent':parents.get(n,root).get('id'),'text':''.join(n.itertext())[:130] if tag(n) in ('text','g') else '', 'attributes':attrs,'tp':o.get('tight_bbox'),'status':o['status']})
    return rows

def snapshot(root,original,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);validate(root)
    (folder/'scene.svg').write_text(serialize(root));bounds=measure(root,folder/'preview.png');write_json(folder/'bounds.json',bounds)
    frames=build(original,folder/'preview.png',root,bounds,folder/'pack')
    tp=measure_tight(root,scale=4);write_json(folder/'tp.json',tp);rows=object_table(root,tp);write_json(folder/'objects.json',rows)
    frames=remap_frame_pairs(frames,original,folder/'preview.png',tp,folder/'tool-pack',revision(root))
    return {'folder':folder,'frames':frames,'tp':tp,'rows':rows,'revision':revision(root)}

def crop_pixels(path,box,dest,label='original'):
    if len(box)!=4 or any(isinstance(x,bool) or not isinstance(x,(int,float)) or not math.isfinite(x) for x in box):raise ValueError('crop box requires finite xywh')
    x,y,w,h=box
    if w<=0 or h<=0:raise ValueError('empty crop')
    with Image.open(path) as im:
        rect=[max(0,math.floor(x)),max(0,math.floor(y)),min(im.width,math.ceil(x+w)),min(im.height,math.ceil(y+h))]
        if rect[2]<=rect[0] or rect[3]<=rect[1]:raise ValueError('crop outside image')
        crop=im.crop(rect);zoom=min(3,max(1,1000/max(crop.size)));crop=crop.resize((round(crop.width*zoom),round(crop.height*zoom)));crop.save(dest)
    return {'requested_xywh':box,'actual_image_pixel_ltrb':rect,'display_scale':zoom,
            'pixel_mapping':f'{label}_x=display_x/display_scale+left; {label}_y=display_y/display_scale+top',
            **({'actual_original_pixel_ltrb':rect} if label=='original' else {})}

def world_to_image(path,canvas,*,tp=None):
    with Image.open(path) as im:width,height=im.size
    if tp is None:
        sx,sy=width/canvas['width'],height/canvas['height']
        return [sx,0,0,sy,-canvas['x']*sx,-canvas['y']*sy]
    m=tp['world_to_viewport'];viewport=tp['viewport']
    sx,sy=width/viewport['width'],height/viewport['height']
    return [m[0]*sx,m[1]*sy,m[2]*sx,m[3]*sy,m[4]*sx,m[5]*sy]

def world_crop(path,box,canvas,dest,*,tp=None,label=None):
    if len(box)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in box):raise ValueError('world box requires finite xywh')
    x,y,w,h=box
    if w<=0 or h<=0:raise ValueError('empty world crop')
    matrix=world_to_image(path,canvas,tp=tp)
    corners=[(x,y),(x+w,y),(x,y+h),(x+w,y+h)]
    points=[(matrix[0]*u+matrix[2]*v+matrix[4],matrix[1]*u+matrix[3]*v+matrix[5]) for u,v in corners]
    left,top=min(p[0] for p in points),min(p[1] for p in points)
    right,bottom=max(p[0] for p in points),max(p[1] for p in points)
    m=crop_pixels(path,[left,top,right-left,bottom-top],dest,label=label or ('current' if tp else 'original'))
    return {**m,'world_xywh':list(box),'world_to_image':matrix,
            'mapping_basis':'rendered_svg_viewport' if tp else 'original_image_to_viewbox'}

def remap_frame_pairs(frames,original,current,tp,folder,current_revision):
    """Tool-runner frame pairs with distinct original and rendered-current maps."""
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    out=[]
    for i,frame in enumerate(frames):
        world=frame['canvas_crop'];crops=[];mappings={}
        for label,path in [('original',original),('current',current)]:
            dest=folder/f'frame-{i:03d}-{label}.png'
            mapping=world_crop(path,world,tp['canvas'],dest,tp=tp if label=='current' else None,label=label)
            mappings[label]=mapping
            with Image.open(dest) as im:crops.append(im.convert('RGB').copy())
        scale=max(1,min(3,1200/max(crops[0].width,crops[0].height)))
        display=[im.resize((round(im.width*scale),round(im.height*scale))) for im in crops]
        plate=Image.new('RGB',(sum(im.width for im in display)+12,max(im.height for im in display)+34),'white')
        draw=ImageDraw.Draw(plate);draw.text((5,5),'ORIGINAL',fill='black');draw.text((display[0].width+17,5),'CURRENT',fill='black')
        plate.paste(display[0],(0,34));plate.paste(display[1],(display[0].width+12,34))
        pair=folder/f'frame-{i:03d}-pair.png';plate.save(pair)
        out.append({**frame,'pair':str(pair.resolve()),'revision':current_revision,
                    'crop_mappings':mappings,'display_scale':scale})
    write_json(folder/'pack.json',{'frames':out,'canvas':tp['canvas'],'mapping':'original image to viewBox; current rendered SVG viewport'})
    return out

def inspect(root,snap,original,args,folder):
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);images=[];result={'revision':snap['revision'],'regions':[],'objects':[]};c=snap['tp']['canvas']
    frame_ids=args.get('frame_ids',[]);ids=args.get('object_ids',[])
    if len(frame_ids)>8 or len(ids)>40:raise ValueError('inspect at most 8 frames / 40 objects per call')
    frames={f['frame_id']:f for f in snap['frames']};by={n.get('id'):n for n in root.iter() if n.get('id')}
    for fid in frame_ids:
        if fid not in frames:raise ValueError('unknown frame ID '+fid)
        f=frames[fid];images.append({'path':f['pair'],'label':'frame_pair','frame_id':fid,'revision':snap['revision'],'crop_mappings':f['crop_mappings']});result['regions'].append({'frame_id':fid,**f,'note':'left original, right current; canvas_crop is SVG world xywh, not pair pixels'})
    for oid in ids:
        if oid not in by or oid not in snap['tp']['objects']:raise ValueError('unknown drawable ID '+oid)
        svg=public_svg(by[oid]);result['objects'].append({'id':oid,'tp':snap['tp']['objects'][oid],'svg':svg[:40000],'svg_truncated':len(svg)>40000})
    boxes=list(args.get('current_boxes',[]))
    if ids:
        b=union_tight(snap['tp'],ids)
        if b:
            w=b['right']-b['left'];h=b['bottom']-b['top'];boxes.append([b['left']-w*.5,b['top']-h*.5,w*2,h*2])
    if len(boxes)>8 or len(args.get('original_boxes',[]))>8:raise ValueError('inspect at most 8 explicit boxes per image')
    for i,b in enumerate(boxes):
        for label,path in [('original',original),('current',snap['folder']/'preview.png')]:
            dest=folder/f'{i:02d}-{label}.png';mapping=world_crop(path,b,c,dest,tp=snap['tp'] if label=='current' else None,label=label)
            record={'image':str(dest),'label':label,'revision':snap['revision'],**mapping}
            images.append({'path':str(dest),**record});result['regions'].append(record)
    for i,b in enumerate(args.get('original_boxes',[])):
        dest=folder/f'original-explicit-{i:02d}.png';mapping=crop_pixels(original,b,dest)
        record={'image':str(dest),'label':'original_only_explicit_correspondence','revision':snap['revision'],**mapping}
        images.append({'path':str(dest),**record});result['regions'].append(record)
    return result,images

def colors(original,regions):
    if len(regions)>30:raise ValueError('at most 30 color regions')
    out=[]
    with Image.open(original) as im:
        im=im.convert('RGB')
        for b in regions:
            if len(b)!=4 or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v) for v in b):raise ValueError('invalid color region')
            x,y,w,h=b;r=(math.floor(x),math.floor(y),math.ceil(x+w),math.ceil(y+h))
            if w<=0 or h<=0 or r[0]<0 or r[1]<0 or r[2]>im.width or r[3]>im.height:raise ValueError('color region outside original')
            patch=im.crop(r);hist=patch.getcolors(patch.width*patch.height);count,rgb=max(hist);pixels=list(patch.getdata());mean=[round(sum(p[k] for p in pixels)/len(pixels),2) for k in range(3)]
            out.append({'original_xywh':b,'modal_rgb':rgb,'modal_hex':'#%02x%02x%02x'%rgb,'modal_fraction':count/len(pixels),'mean_rgb':mean})
    return out


def compact_result(result):
    """Keep full execution on disk; avoid repeating thousands of pair records in chat."""
    brief=deepcopy(result)
    for issue in brief.get('issues',[]):
        checks=issue.get('checks',{});objects=checks.get('objects',{})
        checks['objects']={k:v for k,v in objects.items() if v.get('moved') or v.get('vanished') or v.get('new')}
        checks['measured_neighborhood_count']=len(objects)
        for key in ('before_pairs','after_pairs'):
            pairs=checks.pop(key,[]);checks[key+'_count']=len(pairs)
        candidates=checks.get('candidates',[]);checks['candidates']=candidates[:60];checks['candidate_count']=len(candidates);checks['candidates_truncated']=len(candidates)>60
    return brief

def source_candidates(name):
    pointer=PLUS_ROOT/'runs/independent-crop-diagnosis-latest.json'
    if not pointer.exists():return []
    prior=Path(read(pointer)['run']);records=read(prior/'all-findings.json');recovery=prior/'format-recovery/all-findings.json'
    if recovery.exists():records+=read(recovery)
    return [{'candidate_id':f'prior-{i}','frame_id':r['frame_id'],'crop_index':r['crop_index'],**r['finding']} for i,r in enumerate(records) if r['source']==name]

def user_snapshot(snap,original,folder,extra_images=(),extra_text=''):
    payload={'revision':snap['revision'],'canvas':snap['tp']['canvas'],'objects':snap['rows'],'frames':[{'id':f['frame_id'],'world_crop_xywh':f['canvas_crop']} for f in snap['frames']]}
    with Image.open(original) as im:payload['original_size_pixels']=list(im.size)
    extras=[item if isinstance(item,dict) else {'path':str(item),'label':'unlabeled'} for item in extra_images]
    payload['feedback_crops']=[{k:v for k,v in item.items() if k!='path'} for item in extras]
    content=image_content([original,snap['folder']/'preview.png',*(item['path'] for item in extras)],folder)
    labels=[{'label':'original_full','revision':snap['revision']},{'label':'current_full','revision':snap['revision']},*extras]
    for i,item in enumerate(labels):
        content[2*i]['text']='Image '+str(i+1)+': '+json.dumps({k:v for k,v in item.items() if k!='path'},ensure_ascii=False,separators=(',',':'))
    return {'role':'user','content':[{'type':'text','text':'Current actual state. First image ORIGINAL full; second image CURRENT full. Additional images carry issue/revision/crop mappings in their labels. '+extra_text+'\n'+json.dumps(payload,ensure_ascii=False,separators=(',',':'))}]+content}

def crop_feedback(items,folder,current_revision):
    content=image_content([item['path'] for item in items],folder)
    for i,item in enumerate(items):
        content[2*i]['text']='Image '+str(i+1)+': '+json.dumps({k:v for k,v in item.items() if k!='path'},ensure_ascii=False,separators=(',',':'))
    return {'role':'user','content':[{'type':'text','text':'Tool crop images with exact image labels and mappings. Current revision '+current_revision+'\n'+json.dumps([{k:v for k,v in item.items() if k!='path'} for item in items],ensure_ascii=False,separators=(',',':'))}]+content}

def compact_history(messages):
    """Drop superseded visual snapshots, retaining native assistant/tool protocol.

    All original/current evidence for the latest revision stays available; prior
    model diagnoses and actual tool results stay intact. This is not new advice.
    """
    snapshots=[]
    for i,m in enumerate(messages):
        c=m.get('content')
        if m.get('role')=='user' and isinstance(c,list) and c and c[0].get('text','').startswith('Current actual state.'):
            snapshots.append(i)
    if not snapshots:return messages
    latest=snapshots[-1];out=[]
    for i,m in enumerate(messages):
        c=m.get('content')
        if i<latest and m.get('role')=='user' and isinstance(c,list):
            out.append({'role':'user','content':'Earlier visual evidence is superseded by the latest actual SVG snapshot below. The native tool calls and their recorded results remain in this conversation.'})
        else:out.append(m)
    return out

def restored_conversation(path,image_store=None):
    """Rehydrate only saved local image attachments from our redacted history."""
    path=Path(path);messages=compact_history(read(path));needed=set()
    def collect(v):
        if isinstance(v,dict):
            if set(v)=={'embedded_image_sha256','bytes_encoded'}:needed.add(v['embedded_image_sha256'])
            else:
                for x in v.values():collect(x)
        elif isinstance(v,list):
            for x in v:collect(x)
    collect(messages);images={}
    for jpg in path.parent.rglob('*.jpg'):
        uri='data:image/jpeg;base64,'+base64.b64encode(jpg.read_bytes()).decode();key=hashlib.sha256(uri.encode()).hexdigest()
        if key in needed:
            images[key]=uri
            if image_store:
                Path(image_store).mkdir(parents=True,exist_ok=True);(Path(image_store)/(key+'.jpg')).write_bytes(jpg.read_bytes())
        if len(images)==len(needed):break
    if needed-set(images):raise ValueError('saved conversation image files incomplete; cannot silently discard evidence')
    def restore(v):
        if isinstance(v,dict):
            if set(v)=={'embedded_image_sha256','bytes_encoded'}:return images[v['embedded_image_sha256']]
            return {k:restore(x) for k,x in v.items()}
        if isinstance(v,list):return [restore(x) for x in v]
        return v
    return restore(messages)

def submitted_issues(messages):
    """Recover submitted issues from each assistant's matching native results."""
    pending={};issues=[]
    for m in messages:
        if m.get('role')=='assistant':
            pending={c.get('id'):c for c in m.get('tool_calls') or []}
        elif m.get('role')=='tool':
            c=pending.pop(m.get('tool_call_id'),None)
            if not c or c.get('function',{}).get('name')!='apply_repairs':continue
            try:args=json.loads(c['function']['arguments'])
            except (ValueError,KeyError,TypeError):continue
            for i in args.get('issues',[]) if isinstance(args,dict) else []:
                if isinstance(i,dict) and isinstance(i.get('id'),str):issues.append(i)
    return issues

def matched_tool_results(messages,name):
    """Read native results across the entire saved conversation, including prior resumes."""
    pending={}
    for message in messages:
        if message.get('role')=='assistant':pending.update({c.get('id'):c for c in message.get('tool_calls') or []})
        elif message.get('role')=='tool':
            call=pending.pop(message.get('tool_call_id'),None)
            if not call or call.get('function',{}).get('name')!=name:continue
            try:yield json.loads(call['function']['arguments']),json.loads(message['content'])
            except (ValueError,KeyError,TypeError):continue

def validate_diagnosis(observations,frame_ids,delivered,known_ids=None,earlier_confirmed=()):
    if set(frame_ids)-set(delivered):raise ValueError('baseline crop coverage incomplete: '+str(sorted(set(frame_ids)-set(delivered))))
    if not isinstance(observations,list):raise ValueError('observations must be a list')
    seen={};confirmed=set(earlier_confirmed)
    for o in observations:
        if not isinstance(o,dict) or not isinstance(o.get('id'),str) or not o['id'] or o['id'] in seen:raise ValueError('observation IDs must be unique nonempty strings')
        if o.get('decision') not in ('confirmed','dismissed','duplicate'):raise ValueError('invalid observation decision')
        if not all(isinstance(o.get(k),str) and o[k].strip() for k in ('description','original_evidence')):raise ValueError('observation lacks description or original evidence')
        for key in ('frame_ids','target_ids','neighbor_ids','types'):
            if not isinstance(o.get(key),list) or any(not isinstance(v,str) for v in o[key]):raise ValueError('invalid observation '+key)
        if set(o['frame_ids'])-set(delivered):raise ValueError('observation references undelivered frame')
        if not o['types'] or set(o['types'])-set(CATEGORIES):raise ValueError('invalid observation types')
        if known_ids is not None and (set(o['target_ids'])|set(o['neighbor_ids']))-set(known_ids):raise ValueError('observation references unknown SVG object ID')
        if o['decision']=='confirmed' and not o['target_ids'] and ('missing' not in o['types'] or not o['neighbor_ids']):raise ValueError('confirmed observation requires a target, or a missing-element neighbor anchor')
        if o['decision']=='duplicate':
            if o.get('duplicate_of') not in confirmed:raise ValueError('duplicate_of must refer to an earlier confirmed observation')
        elif o.get('duplicate_of'):raise ValueError('duplicate_of only applies to duplicates')
        if o['decision']=='confirmed':confirmed.add(o['id'])
        seen[o['id']]=o
    return confirmed

def restore_survey_state(prior_dir,messages,current_revision):
    prior_dir=Path(prior_dir);status=read(prior_dir/'status.json');diagnosis=read(prior_dir/'diagnosis.json')
    if not status.get('survey_first') or status['final_revision']!=current_revision:raise ValueError('survey continuation does not match saved final SVG')
    coverage=status['coverage'];required=set(coverage['required_frame_ids']);delivered=set(coverage['delivered_frame_ids'])
    if not delivered<=required:raise ValueError('invalid saved survey coverage')
    confirmed={o['id'] for o in diagnosis['observations'] if o['decision']=='confirmed'} if diagnosis['status']=='submitted' else set()
    allowed={o['id']:set(o['target_ids']+o['neighbor_ids']) for o in diagnosis['observations'] if o['decision']=='confirmed'}
    applied=set();boxes={}
    for _,result in matched_tool_results(messages,'apply_repairs'):
        if not isinstance(result,dict):continue
        for item in result.get('issues',[]):
            oid=item.get('id')
            if oid not in allowed or item.get('status')!='applied':continue
            if item.get('resulting_revision')!=item.get('baseline_revision'):applied.add(oid)
            for op in item.get('applied_operations',[]):
                outcome=op.get('result') or {};allowed[oid].update(outcome.get('added_ids',[]))
                if outcome.get('replacement_id'):allowed[oid].add(outcome['replacement_id'])
        for focus in result.get('focus_inspections',[]):
            oid=focus.get('issue_id')
            for region in focus.get('regions',[]):
                if oid in allowed and region.get('world_xywh'):boxes[oid]=region['world_xywh'];break
    focus_delivered={};paired={}
    for message in messages:
        content=message.get('content')
        if message.get('role')!='user' or not isinstance(content,list):continue
        for item in content:
            if item.get('type')!='text' or not item.get('text','').startswith('Image '):continue
            try:meta=json.loads(item['text'].split(': ',1)[1])
            except (ValueError,IndexError):continue
            oid=meta.get('issue_id')
            if oid in confirmed and meta.get('revision')==current_revision:paired.setdefault(oid,set()).add(meta.get('label'))
    for oid,labels in paired.items():
        if {'original','current'}<=labels:focus_delivered[oid]=current_revision
    return status,diagnosis,required,delivered,confirmed,allowed,applied,focus_delivered,boxes


def run_one(*args, **kwargs):
    raise ValueError('legacy multi-turn repair disabled; use single-call repair-prepare / repair-once')


def _run_one_offline(name,source,folder,max_turns=8,send=send_deepseek_tools,continue_unresolved=False,survey_first=False):
    if send is send_deepseek_tools:
        raise ValueError('legacy multi-turn repair disabled; use single-call repair-prepare / repair-once')
    from .repair_toolbox import execute_batch
    survey_resume=Path(source['survey_resume_dir']) if source.get('survey_resume_dir') else None
    if survey_first and (continue_unresolved or source.get('previous_model_review') or (source.get('previous_conversation') and not survey_resume)):raise ValueError('survey-first requires a fresh baseline or explicit survey continuation')
    if survey_resume and not survey_first:raise ValueError('survey continuation requires survey-first')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=False);original=Path(source['original']);svg=Path(source.get('svg') or Path(source['current']).parent/'scene.svg');root=ET.fromstring(svg.read_text());validate(root)
    write_json(folder/'source.json',{**source,'svg':str(svg),'sha256':hashlib.sha256(svg.read_bytes()).hexdigest(),'original_sha256':hashlib.sha256(original.read_bytes()).hexdigest()})
    snap=snapshot(root,original,folder/'stage-0');initial_rev=snap['revision'];revision_seen=None;issues_log=[];calls=[];concluded=None;stop='turn_limit';read_duplicates={};mutation_duplicates={}
    priors=(PLUS_ROOT/'experiments/diagnosis-priors.txt').read_text().split('\n\n',1)[-1]
    prompt=(PLUS_ROOT/'prompts/tool-repair.md').read_text()+'\n问题类型枚举（本轮必须按类型，可多选）：typesetting/content/overlap/overflow/alignment/relative_size/planar_shape/arrow_geometry/arrow_route/fill_spill/missing/color/count/geometry。\n'+priors+'\n'+manual()
    # Shared operating method lives in tool-repair.md; do not append conflicting duplicate policy.
    if survey_first:prompt+='\n本轮先独立全图调查：观察原图和当前图，使用inspect_regions读取每个基线frame_id的原图/现图成对crop。每个inspect_regions最多8帧，但可以在同一次回复中并列调用多次，尽快覆盖全部帧；工具会送达所有请求的成对图。确认所有crop实际送达后，用submit_diagnosis一次提交完整观察清单。每项给全局唯一id、简洁原图证据、frame_ids、对象和邻居ID、类型，并标记confirmed/dismissed/duplicate；重复项指向先前confirmed项。frame_ids可为空，表示只依据已提供的原图/现图全图；这不免除所有基线frame crop覆盖。提交前不要修复；之后apply_repairs的问题id、types和对象范围须对应confirmed项；缺失对象以已有邻居作锚点。若后续发现需要纳入新的真实对象ID，再调用submit_diagnosis，传需修订的已确认观察或新观察完整记录，明确新的target_ids/neighbor_ids及证据；旧观察保留。修复后逐项复查，finish_review覆盖所有confirmed项，包括未修复项；未真正修复的项不能写resolved。工具报错时读反馈并在同一次运行中修正。图像已送达只表示可供观察，不自动证明你理解其语义。'
    (folder/'system-prompt.txt').write_text(prompt)
    candidates=[]  # Fresh runs never import a previous run's diagnosis by image name.
    write_json(folder/'prior-model-candidates.json',candidates)
    messages=[{'role':'system','content':prompt}]
    if source.get('previous_model_review'):
        previous=read(source['previous_model_review'])
        prior_tools=Path(source['previous_model_review']).parent/'tool-calls.json'
        if not previous.get('model_review') and prior_tools.exists():
            previous['model_review']={'interrupted_review':True,'executed_model_issues':[{'issues':(c.get('arguments') or {}).get('issues',[]),'results':[{'id':i['id'],'status':i['status'],'errors':i.get('errors',[])} for i in c['result'].get('issues',[])]} for c in read(prior_tools) if c['name']=='apply_repairs']}
        messages.append({'role':'user','content':'Explicit continuation from the prior actual output. Below is the previous PRODUCT MODEL review, not human repair instructions. Tool argument validation and restricted BP style support have been improved. Recheck against the current image and continue remaining issues; preserve already correct repairs.\n'+json.dumps(previous.get('model_review'),ensure_ascii=False)})
    messages.append(user_snapshot(snap,original,folder/'images-0'))
    if source.get('previous_conversation') and not survey_resume:
        previous_status=read(source['previous_model_review'])
        if previous_status['final_revision']!=snap['revision']:raise ValueError('continuation SVG differs from saved tool conversation')
        messages=restored_conversation(source['previous_conversation'],folder/'restored-images')
        issues_log=submitted_issues(messages)
        messages[0]={'role':'system','content':prompt}
        messages.append({'role':'user','content':'Continue the SAME product-model/tool conversation from its last actual SVG revision. All previous calls, results, and latest images are retained. Do not restart inspection of unchanged regions already checked. Proceed with remaining actions or finish_review honestly; this continuation is bounded. Tool parameter validation and restricted BP style are supported as documented.'})
    if continue_unresolved:
        messages.append({'role':'user','content':'This run continues the remaining defects YOU already identified. Start with a productive repair or necessary focused inspection, not a repetition of the same incomplete finish_review. Use SP for needed reconstruction and the local formula renderer for math. Do not defer merely because multiple objects are involved; stay within the bounded run and record real blockers honestly.'})
    print(f'{name}: prepared {len(snap["rows"])} TP objects; {len(candidates)} prior candidates',flush=True)
    baseline_frames={f['frame_id'] for f in snap['frames']};delivered_frames=set();diagnosis=None;confirmed=set();allowed_ids={};applied_ids=set();focus_delivered={};issue_focus_boxes={}
    if survey_resume:
        messages=restored_conversation(survey_resume/'conversation-redacted.json',folder/'restored-images')
        messages[0]={'role':'system','content':prompt}
        prior_status,prior_diagnosis,baseline_frames,delivered_frames,confirmed,allowed_ids,applied_ids,focus_delivered,issue_focus_boxes=restore_survey_state(survey_resume,messages,snap['revision'])
        initial_rev=prior_status['initial_revision'];diagnosis=prior_diagnosis if prior_diagnosis['status']=='submitted' else None
        issues_log=submitted_issues(messages)
        messages.append({'role':'user','content':'Continue this same product-model survey and native-tool conversation from the saved actual SVG revision. The recorded diagnosis, crop delivery, applied repairs and latest images remain available. Continue remaining repair or review work within this bounded run; correct tool errors using the returned results.'})
    if survey_first:write_json(folder/'diagnosis.json',diagnosis or {'status':'pending','observations':[],'confirmed_ids':[],'coverage':{'required_frame_ids':sorted(baseline_frames),'delivered_frame_ids':sorted(delivered_frames),'complete':baseline_frames<=delivered_frames}})
    write_json(folder/'status.json',{'status':'running','revision':snap['revision'],'survey_first':survey_first})
    for turn in range(max_turns):
        d=folder/f'turn-{turn:02d}';d.mkdir();write_json(d/'state-before.json',{'revision':snap['revision'],'snapshot':str(snap['folder'])})
        try:message=send(compact_history(messages),TOOLS if survey_first else [t for t in TOOLS if t['function']['name']!='submit_diagnosis'],d/'api')
        except Exception as e:stop='api_error';write_json(d/'failure.json',{'error':str(e)});break
        revision_seen=snap['revision'];messages.append(message);tool_calls=message.get('tool_calls') or [];print(f'{name}: turn {turn} calls {[c["function"]["name"] for c in tool_calls]}',flush=True)
        if not tool_calls:
            stop='no_native_tool_calls';write_json(d/'unstructured-final.json',message);break
        changed=False;images=[];tool_log=[];repeated_in_turn=False
        for j,call in enumerate(tool_calls):
            fn=call['function']['name'];argstr=call['function']['arguments'];dest=d/f'tool-{j:02d}';dest.mkdir();args=None
            try:
                args=json.loads(argstr)
                if not isinstance(args,dict):raise ValueError('tool arguments must be object')
                canonical=json.dumps(args,sort_keys=True,separators=(',',':'),ensure_ascii=False)
                if fn=='apply_repairs':
                    key=(fn,canonical);mutation_duplicates[key]=mutation_duplicates.get(key,0)+1
                    repeated=mutation_duplicates[key]>2
                else:
                    key=(snap['revision'],fn,canonical);read_duplicates[key]=read_duplicates.get(key,0)+1
                    repeated=read_duplicates[key]>2
                if repeated:
                    repeated_in_turn=True
                    raise ValueError('unchanged identical tool request repeated at this revision; choose different evidence/action or finish unresolved')
                if fn=='inspect_regions':result,more=inspect(root,snap,original,args,dest);images+=more
                elif fn=='sample_original_colors':result={'samples':colors(original,args['regions'])}
                elif fn=='submit_diagnosis':
                    if not survey_first:raise ValueError('submit_diagnosis requires survey-first')
                    if diagnosis is None:
                        confirmed=validate_diagnosis(args.get('observations'),baseline_frames,delivered_frames,snap['tp']['objects'])
                        allowed_ids={o['id']:set(o['target_ids']+o['neighbor_ids']) for o in args['observations'] if o['decision']=='confirmed'}
                        diagnosis={'status':'submitted','observations':args['observations'],'confirmed_ids':sorted(confirmed),'coverage':{'required_frame_ids':sorted(baseline_frames),'delivered_frame_ids':sorted(delivered_frames),'complete':True},'amendments':[]}
                        result={'recorded':True,'confirmed_ids':sorted(confirmed),'coverage':diagnosis['coverage']}
                    else:
                        if images:raise ValueError('deliver current inspection crops before amending diagnosis')
                        amendments=args.get('observations')
                        if not isinstance(amendments,list) or not amendments:raise ValueError('submit at least one new or amended observation')
                        existing={o['id']:o for o in diagnosis['observations']}
                        if any(o.get('id') in existing and o['id'] not in confirmed for o in amendments):raise ValueError('cannot amend dismissed/duplicate observation')
                        if any(o.get('id') in confirmed and o.get('decision')!='confirmed' for o in amendments):raise ValueError('confirmed observations cannot be dismissed or deduplicated by amendment; use final false_positive review with evidence')
                        validate_diagnosis(amendments,baseline_frames,delivered_frames,set(snap['tp']['objects'])|set().union(*allowed_ids.values()),confirmed)
                        by={o['id']:o for o in diagnosis['observations']}
                        for o in amendments:
                            by[o['id']]=o
                            if o['decision']=='confirmed':
                                confirmed.add(o['id']);allowed_ids.setdefault(o['id'],set()).update(o['target_ids']+o['neighbor_ids'])
                        diagnosis['observations']=list(by.values());diagnosis['confirmed_ids']=sorted(confirmed)
                        diagnosis.setdefault('amendments',[]).append({'revision':snap['revision'],'observations':amendments})
                        result={'amended_ids':[o['id'] for o in amendments if o['id'] in existing],'new_ids':[o['id'] for o in amendments if o['id'] not in existing],'confirmed_ids':sorted(confirmed)}
                    write_json(folder/'diagnosis.json',diagnosis)
                elif fn=='apply_repairs':
                    mapping_amendments=[]
                    if survey_first:
                        if diagnosis is None:raise ValueError('submit_diagnosis and complete crop coverage before repairs')
                        repair_ids=[i.get('id') for i in args.get('issues',[]) if isinstance(i,dict)]
                        if len(repair_ids)!=len(args.get('issues',[])) or len(repair_ids)!=len(set(repair_ids)) or set(repair_ids)-confirmed:raise ValueError('repair issue IDs must be distinct confirmed observation IDs')
                        observations={o['id']:o for o in diagnosis['observations']}
                        for issue in args['issues']:
                            observed=observations[issue['id']]
                            targets=issue.get('target_ids');neighbors=issue.get('neighbor_ids',[]);types=issue.get('types')
                            if not isinstance(targets,list) or not targets or not isinstance(neighbors,list) or any(not isinstance(v,str) for v in targets+neighbors):raise ValueError('repair '+issue['id']+' requires nonempty target IDs and string neighbor IDs')
                            if not isinstance(types,list) or not types or set(types)-set(CATEGORIES):raise ValueError('repair '+issue['id']+' has invalid types')
                            if not all(isinstance(issue.get(k),str) and issue[k].strip() for k in ('description','original_evidence')):raise ValueError('repair '+issue['id']+' requires description and original evidence')
                            unknown=(set(targets)|set(neighbors))-set(snap['tp']['objects'])
                            if unknown:raise ValueError('repair '+issue['id']+' references unknown current SVG IDs '+str(sorted(unknown)))
                            fields=('target_ids','neighbor_ids','types','description','original_evidence')
                            updated={**observed,**{k:issue.get(k,[]) for k in fields}}
                            if any(updated[k]!=observed.get(k) for k in fields):mapping_amendments.append(updated)
                        if mapping_amendments:
                            by={o['id']:o for o in diagnosis['observations']}
                            for o in mapping_amendments:
                                by[o['id']]=o;allowed_ids[o['id']].update(o['target_ids']+o['neighbor_ids'])
                            diagnosis['observations']=list(by.values())
                            diagnosis.setdefault('amendments',[]).append({'revision':snap['revision'],'source':'apply_repairs','observations':mapping_amendments})
                            write_json(folder/'diagnosis.json',diagnosis)
                    pre_boxes={}
                    if survey_first:
                        for issue in args['issues']:
                            ids=[i for i in issue.get('target_ids',[])+issue.get('neighbor_ids',[]) if i in snap['tp']['objects']]
                            box=union_tight(snap['tp'],ids) if ids else None
                            if box:
                                w=box['right']-box['left'];h=box['bottom']-box['top']
                                pre_boxes[issue['id']]=[box['left']-w*.5,box['top']-h*.5,w*2,h*2]
                        issue_focus_boxes.update(pre_boxes)
                    before=revision(root);trial=deepcopy(root);result=execute_batch(trial,args['issues'],original,dest,scale=4);issues_log+=args['issues'];after=revision(trial)
                    if mapping_amendments:result['mapping_amendments']=[{'id':o['id'],'target_ids':o['target_ids'],'neighbor_ids':o['neighbor_ids'],'types':o['types'],'description':o['description'],'original_evidence':o['original_evidence']} for o in mapping_amendments]
                    if after!=before:
                        # Earlier current crops belong to older SVG revisions.
                        images=[]
                        next_snap=snapshot(trial,original,dest/'after');root=trial;snap=next_snap;changed=True
                        if survey_first:focus_delivered.clear()
                        result['focus_inspections']=[]
                        # Per-issue neighborhoods stay local; don't union all scene issues into one crop.
                        focus_issues=zip(args['issues'],result['issues']) if survey_first else zip(args['issues'][:8],result['issues'][:8])
                        for k,(issue,issue_result) in enumerate(focus_issues):
                            if issue_result['status']!='applied':continue
                            if survey_first and issue_result['resulting_revision']!=issue_result['baseline_revision']:
                                applied_ids.add(issue['id'])
                                for operation in issue_result['applied_operations']:
                                    outcome=operation['result'];allowed_ids[issue['id']].update(outcome.get('added_ids',[]))
                                    if outcome.get('replacement_id'):allowed_ids[issue['id']].add(outcome['replacement_id'])
                            ids=[i for i in issue.get('target_ids',[])+issue.get('neighbor_ids',[]) if i in snap['tp']['objects']]
                            target_boxes=[]
                            if survey_first:
                                for operation in issue_result['applied_operations']:
                                    outcome=operation['result'];ids.extend(i for i in outcome.get('added_ids',[]) if i in snap['tp']['objects'])
                                    if outcome.get('replacement_id') in snap['tp']['objects']:ids.append(outcome['replacement_id'])
                                    target=(operation['input'].get('args') or {}).get('target_tp')
                                    if isinstance(target,dict) and all(v in target for v in ('left','top','right','bottom')):target_boxes.append([target['left'],target['top'],target['right']-target['left'],target['bottom']-target['top']])
                            if ids or issue['id'] in pre_boxes:
                                try:
                                    if survey_first and len(ids)>40:raise ValueError('post-repair focus exceeds 40 object IDs; request focused inspection')
                                    focus_args={'object_ids':list(dict.fromkeys(ids))[:40]}
                                    if issue['id'] in pre_boxes:focus_args['current_boxes']=[pre_boxes[issue['id']]]
                                    if target_boxes:focus_args.setdefault('current_boxes',[]).extend(target_boxes)
                                    focus,more=inspect(root,snap,original,focus_args,dest/f'focus-{k:02d}')
                                    for region in focus['regions']:region['issue_id']=issue['id']
                                    for image in more:image['issue_id']=issue['id']
                                    result['focus_inspections'].append({'issue_id':issue['id'],'revision':snap['revision'],'regions':focus['regions']})
                                    images+=more
                                except ValueError as exc:
                                    result['focus_inspections'].append({'issue_id':issue['id'],'revision':snap['revision'],'error':str(exc)})
                        if survey_first:
                            current_ids={i['id'] for i in args['issues']}
                            for prior_index,old_id in enumerate(sorted(applied_ids-current_ids)):
                                old_ids=[i for i in allowed_ids[old_id] if i in snap['tp']['objects']]
                                try:
                                    if len(old_ids)>40:raise ValueError('post-repair focus exceeds 40 object IDs; request focused inspection')
                                    focus_args={'object_ids':old_ids}
                                    if old_id in issue_focus_boxes:focus_args['current_boxes']=[issue_focus_boxes[old_id]]
                                    focus,more=inspect(root,snap,original,focus_args,dest/f'focus-prior-{prior_index:03d}')
                                    for region in focus['regions']:region['issue_id']=old_id
                                    for image in more:image['issue_id']=old_id
                                    result['focus_inspections'].append({'issue_id':old_id,'revision':snap['revision'],'regions':focus['regions']})
                                    images+=more
                                except ValueError as exc:result['focus_inspections'].append({'issue_id':old_id,'revision':snap['revision'],'error':str(exc)})
                        result['current_revision']=snap['revision'];result['actual_snapshot']=str(snap['folder'])
                elif fn=='finish_review':
                    if survey_first and diagnosis is None:raise ValueError('submit_diagnosis and complete crop coverage before review')
                    if survey_first and images:raise ValueError('inspection or repair crops requested in this response have not been delivered; review next round')
                    if revision_seen!=snap['revision']:raise ValueError('latest mutated render has not been sent to model; review next round')
                    if not all(args.get(k) for k in ('summary','global_review')):raise ValueError('missing global evidence')
                    expected=confirmed if survey_first else {i['id'] for i in issues_log};reviewed={i['issue_id'] for i in args.get('issue_results',[])}
                    if expected-reviewed:raise ValueError('review missing submitted issues: '+str(sorted(expected-reviewed)))
                    if survey_first and reviewed-expected:raise ValueError('review contains unknown observation IDs')
                    if survey_first:
                        if len(args.get('issue_results',[]))!=len(expected):raise ValueError('review requires exactly one result per confirmed observation')
                        unresolved={i['issue_id'] for i in args.get('issue_results',[]) if i['status'] in ('remaining','uncertain')}
                        if unresolved!=set(args.get('remaining_issues',[])):raise ValueError('remaining_issues must equal unresolved confirmed observations')
                        for item in args['issue_results']:
                            if item['status']=='resolved' and (item['issue_id'] not in applied_ids or focus_delivered.get(item['issue_id'])!=snap['revision']):raise ValueError('resolved requires an applied repair and delivered local original/current evidence at current revision')
                    result={'recorded':True,'revision':snap['revision'],'human_visual_passed':False,**args};concluded=result
                else:raise ValueError('unknown tool '+fn)
            except Exception as e:result={'error':type(e).__name__,'detail':str(e),'revision':snap['revision']}
            record={'tool_call_id':call['id'],'name':fn,'arguments':args,'result':result}
            if survey_first and diagnosis is not None:
                progress=repair_progress(diagnosis,[{'name':'apply_repairs','arguments':a,'result':r} for a,r in matched_tool_results(messages,'apply_repairs')]+[record])
                result['execution_coverage']=progress
                write_json(folder/'repair-progress.json',progress)
            write_json(dest/'execution.json',record);tool_log.append(record);calls.append(record)
            messages.append({'role':'tool','tool_call_id':call['id'],'content':json.dumps(compact_result(result),ensure_ascii=False)})
        write_json(d/'tool-results.json',tool_log)
        if concluded and not changed:
            if continue_unresolved and concluded.get('remaining_issues') and turn<max_turns-1:
                if images:messages.append(crop_feedback(images[:20],d/'feedback-images',snap['revision']))
                messages.append({'role':'user','content':'Your own review records remaining defects. Continue a productive batch from those findings using available TP/SP/BP; do not defer just because several objects need rebuilding. For complex local content use the documented SP photo/vector option, and mathematical typesetting uses the formula constructor. All choices and source crops must come from the original image. Preserve correct work. If a finding was false, dismiss it with evidence; if truly blocked, state the concrete limitation. No new human image-specific hints are provided.'})
                concluded=None
                continue
            stop='model_finished';break
        if changed:concluded=None
        if repeated_in_turn and not changed:stop='repeated_no_progress';break
        # All tool messages must be contiguous with assistant calls before adding image feedback.
        feedback_images=images if survey_first else images[:20]
        if changed:messages.append(user_snapshot(snap,original,d/'feedback-images',extra_images=feedback_images,extra_text='Actual locally executed result. Recheck all affected objects and neighbors; do not claim solved until these images support it.'))
        elif images:messages.append(crop_feedback(feedback_images,d/'feedback-images',snap['revision']))
        else:messages.append({'role':'user','content':'Tools completed with no rendered change. Use the result/errors to proceed; do not repeat unchanged calls. Finish unresolved if unable.'})
        if survey_first:
            delivered_frames.update(i['frame_id'] for i in feedback_images if i.get('label')=='frame_pair' and i.get('revision')==initial_rev and i.get('frame_id') in baseline_frames)
            for issue_id in {i.get('issue_id') for i in feedback_images if i.get('issue_id')}:
                labels={i.get('label') for i in feedback_images if i.get('issue_id')==issue_id}
                if {'original','current'}<=labels:focus_delivered[issue_id]=snap['revision']
            if diagnosis is None:write_json(folder/'diagnosis.json',{'status':'pending','observations':[],'confirmed_ids':[],'coverage':{'required_frame_ids':sorted(baseline_frames),'delivered_frame_ids':sorted(delivered_frames),'complete':baseline_frames<=delivered_frames}})
    (folder/'final.svg').write_text(serialize(root));measure(root,folder/'final.png')
    status={'status':stop,'initial_revision':initial_rev,'final_revision':revision(root),'changed':initial_rev!=revision(root),'tool_calls':len(calls),'issues_submitted':len(issues_log),'model_review':concluded,'human_visual_passed':False,'latest_snapshot':str(snap['folder']),'survey_first':survey_first}
    if survey_first:status.update({'diagnosis':str(folder/'diagnosis.json'),'coverage':{'required_frame_ids':sorted(baseline_frames),'delivered_frame_ids':sorted(delivered_frames),'complete':baseline_frames<=delivered_frames},'confirmed_observations':sorted(confirmed)})
    write_json(folder/'status.json',status);write_json(folder/'tool-calls.json',calls);write_json(folder/'conversation-redacted.json',redact(messages))
    (folder/'index.html').write_text('<meta charset="utf-8"><title>'+name+' tool repair</title><style>body{font:16px system-ui;margin:24px}img{max-width:100%}pre{white-space:pre-wrap}</style><h1>'+name+'</h1><p>Actual model-selected tools; human quality not automatically accepted.</p><h2>Original</h2><img src="'+original.as_uri()+'"><h2>Before</h2><img src="'+Path(source['current']).as_uri()+'"><h2>After</h2><img src="final.png"><p><a href="final.svg">SVG</a> · <a href="tool-calls.json">Actual tool calls</a></p><pre>'+html.escape(json.dumps(status,ensure_ascii=False,indent=2))+'</pre>')
    print(f'{name}: finished {stop}, changed={status["changed"]}',flush=True);return status
