"""Every frame gets a visible original/current comparison and crop mapping."""
import html
import math
from pathlib import Path
from PIL import Image,ImageDraw
from .document import frame_ids,tag
from ..pack import half_crop
from ..state import write_json

def build(original,current,root,measured,out):
    out=Path(out);out.mkdir(parents=True,exist_ok=True);c=measured['canvas'];W,H=c['width'],c['height']
    frames=[]
    with Image.open(original) as src,Image.open(current) as now:
        for fid in frame_ids(root):
            if fid not in measured['objects']:continue
            b=measured['objects'][fid]['geometry_bbox']
            try:x,y,w,h=half_crop([b['left']-c['x'],b['top']-c['y'],b['right']-b['left'],b['bottom']-b['top']],[W,H])
            except ValueError:continue
            # Filenames are independent of model IDs (IDs may contain slashes).
            stem=f'frame-{len(frames):03d}';crops=[]
            for label,im in [('original',src),('current',now)]:
                sx,sy=im.width/W,im.height/H
                rect=[math.floor(x*sx),math.floor(y*sy),math.ceil((x+w)*sx),math.ceil((y+h)*sy)]
                crop=im.crop(rect);path=out/f'{stem}-{label}.png';crop.save(path);crops.append(crop)
            # Equal display scale, never independent stretching of the two halves.
            scale=max(1,min(3,1200/max(crops[0].width,crops[0].height)))
            display=[im.resize((round(im.width*scale),round(im.height*scale))) for im in crops]
            plate=Image.new('RGB',(sum(im.width for im in display)+12,max(im.height for im in display)+34),'white')
            draw=ImageDraw.Draw(plate);draw.text((5,5),'ORIGINAL',fill='black');draw.text((display[0].width+17,5),'CURRENT',fill='black')
            plate.paste(display[0],(0,34));plate.paste(display[1],(display[0].width+12,34))
            path=out/f'{stem}-pair.png';plate.save(path)
            frames.append({'frame_id':fid,'canvas_crop':[x+c['x'],y+c['y'],w,h],'pair':str(path.resolve()),'display_scale':scale,'original_left':True})
    write_json(out/'pack.json',{'frames':frames,'canvas':c,'coverage_inferred_from':'explicit frame metadata or legacy closed shapes with explicit IDs','visual_passed':False})
    cards=''.join(f'<section><h2>{html.escape(f["frame_id"])}</h2><img src="{Path(f["pair"]).name}"></section>' for f in frames)
    (out/'index.html').write_text('<meta charset="utf-8"><title>All frame comparisons</title><style>body{font-family:system-ui;margin:24px}img{max-width:100%}section{border-bottom:1px solid #ccc;padding:12px}</style><h1>Original left · Current right</h1>'+cards, encoding='utf-8')
    return frames
