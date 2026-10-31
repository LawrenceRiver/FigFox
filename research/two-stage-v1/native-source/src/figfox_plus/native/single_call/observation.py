"""Uniform diagnostic PNG pairs, independent of SVG object names and types.

Shared viewport regions are comparison aids, never source material coordinates.
TP is not used to locate reference content. Images are resampled once per side.
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw


def _starts(length, edge, overlap):
    if length<=edge:return [0]
    count=math.ceil((length-edge)/(edge*(1-overlap)))+1
    return [i*(length-edge)/(count-1) for i in range(count)]


def tile_regions(canvas, edge=384, overlap=0.25):
    if edge<=0 or not 0<=overlap<1:raise ValueError('invalid observation tiling')
    x,y,w,h=(float(canvas[k]) for k in ('x','y','width','height'))
    if not all(math.isfinite(v) for v in (x,y,w,h)) or min(w,h)<=0:
        raise ValueError('invalid canvas')
    return [{'id':f'visual-tile-{row:02d}-{col:02d}',
             'shared_diagnostic_region':[x+dx,y+dy,min(w,edge),min(h,edge)]}
            for row,dy in enumerate(_starts(h,edge,overlap))
            for col,dx in enumerate(_starts(w,edge,overlap))]


def balanced_pairs(original,current,canvas,folder,*,edge=384,zoom=2.5):
    if not math.isfinite(zoom) or not 0<zoom<=8:raise ValueError('invalid display zoom')
    folder=Path(folder);folder.mkdir(parents=True,exist_ok=True)
    out=[]
    with Image.open(original) as src,Image.open(current) as now:
        for region in tile_regions(canvas,edge=edge):
            x,y,w,h=region['shared_diagnostic_region']
            size=(max(1,round(w*zoom)),max(1,round(h*zoom)))
            plate=Image.new('RGB',(2*size[0]+12,size[1]+30),'white')
            draw=ImageDraw.Draw(plate)
            draw.text((4,5),'ORIGINAL',fill='black')
            draw.text((size[0]+16,5),'CURRENT',fill='black')
            for i,im in enumerate((src,now)):
                sx,sy=im.width/canvas['width'],im.height/canvas['height']
                left,top=(x-canvas['x'])*sx,(y-canvas['y'])*sy
                # PIL resizes this precise source box directly (no double upsampling).
                display=im.convert('RGB').resize(size,Image.Resampling.LANCZOS,
                                                box=(left,top,left+w*sx,top+h*sy))
                plate.paste(display,(i*(size[0]+12),30))
            path=folder/(region['id']+'.png');plate.save(path)
            out.append({**region,'path':str(path.resolve()),'display_size_each':list(size),
                        'purpose':'diagnostic_pair_only_not_material_source_crop'})
    return out
