"""Deterministic SAM boxes on the full original; source coordinates stay local."""
import json
from pathlib import Path
from PIL import Image,ImageDraw,ImageFont

def build_boards(original,assets,folder,page_size=12):
    if page_size<1:raise ValueError('page_size must be positive')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    base=Image.open(original).convert('RGB');scale=1
    base=base.resize((base.width*scale,base.height*scale))
    font=ImageFont.load_default(size=16)
    result={'pictures':[],'arrows':[],'images':[],'public':{'pictures':[],'arrows':[]}}
    pages=[]
    for role,key,prefix in [('picture','pictures','P'),('arrow_hint','arrows','A')]:
        selected=[a for a in assets if (a['role']=='arrow_hint')==(role=='arrow_hint')]
        for i,a in enumerate(selected,1):
            obj={**a,'source_id':a['id'],'id':f'{prefix}{i:03d}'}
            result[key].append(obj)
            result['public'][key].append({k:obj[k] for k in ('id','role','head_pixels','detected_heads') if k in obj})
        for start in range(0,len(selected),page_size):
            canvas=base.copy();draw=ImageDraw.Draw(canvas);labels=[]
            items=result[key][start:start+page_size]
            for obj in items:
                x,y,w,h=obj['source_crop'];x,y,w,h=[v*scale for v in (x,y,w,h)]
                if w<=0 or h<=0:raise ValueError('invalid SAM box')
                color='#e00035' if prefix=='P' else '#0068e5'
                draw.rectangle((x,y,x+w,y+h),outline=color,width=3)
                label=obj['id'];bb=draw.textbbox((0,0),label,font=font);lw=bb[2]-bb[0]+10;lh=bb[3]-bb[1]+10
                candidates=[(x,y-lh-3),(x,y+h+3),(x+w+3,y),(x-lw-3,y)]
                def overlap(a,b):return max(0,min(a[2],b[2])-max(a[0],b[0]))*max(0,min(a[3],b[3])-max(a[1],b[1]))
                boxes=[]
                for lx,ly in candidates:
                    lx=max(0,min(lx,canvas.width-lw));ly=max(0,min(ly,canvas.height-lh));boxes.append((lx,ly,lx+lw,ly+lh))
                box=min(boxes,key=lambda b:sum(overlap(b,v) for v in labels)+overlap(b,(x,y,x+w,y+h)))
                labels.append(box)
                draw.line(((x+w/2,y+h/2),((box[0]+box[2])/2,(box[1]+box[3])/2)),fill=color,width=2)
                draw.rectangle(box,fill='white',outline=color,width=2)
                draw.text((box[0]+5,box[1]+5-bb[1]),label,font=font,fill=color)
            path=folder/f'{prefix}-board-{start//page_size+1:02d}.png';canvas.save(path)
            result['images'].append(path);pages.append({'path':str(path),'ids':[o['id'] for o in items]})
    (folder/'manifest.json').write_text(json.dumps({'source':str(original),'pages':pages,'assets':result['pictures']+result['arrows']},ensure_ascii=False,indent=2))
    return result

def review_context(original,root,run,tool_folder):
    """Boards enter only later visual diagnosis; ID resolution remains local."""
    import base64,hashlib
    run=Path(run);sam_file=run/'sam.json'
    if not sam_file.exists():return '',[]
    saved=json.loads(sam_file.read_text())
    boards=build_boards(original,saved['assets'],run/'review-sam-boards')
    assets=boards['pictures']+boards['arrows']
    folder=Path(tool_folder);folder.mkdir(parents=True,exist_ok=True)
    (folder/'asset-catalog.json').write_text(json.dumps({a['id']:a['path'] for a in assets}))
    hashes={}
    for a in assets:
        h=hashlib.sha256(Path(a['path']).read_bytes()).hexdigest();hashes.setdefault(h,[]).append(a['id'])
    current=[]
    for node in root.iter():
        if node.tag.rsplit('}',1)[-1]!='image':continue
        href=node.get('href',node.get('{http://www.w3.org/1999/xlink}href',''))
        aliases=[]
        if href.startswith('data:image/png;base64,'):
            aliases=hashes.get(hashlib.sha256(base64.b64decode(href.split(',',1)[1])).hexdigest(),[])
        current.append({'svg_id':node.get('id'),'current_asset_ids':aliases})
    prompt='\n【生成后素材核查】最后追加的附图是原图SAM标框看板，先P图片页再A箭头页；框、编号、指示线仅供核查，不属于原图。逐一对照原图对象、当前图片内容与看板ID，检查全部图片引用是否选错；只改确认错配的引用，正确的保留，不因核查看板重新布局。错配用category=content，描述原图/现图证据，再用action=relink、target_ids=[现SVG图片节点ID]、args={"asset_id":"看板实际ID"}；本地只替换图片内容，保留位置尺寸变换。不要返回文件路径或base64，不用手填crop坐标。看板没有正确素材则记录未解决或按已有补crop工具处理。\n'
    prompt+='Available board IDs:'+json.dumps([a['id'] for a in assets])+'\nCurrent image bindings:'+json.dumps(current)
    return prompt,boards['images']
