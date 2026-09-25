"""Frame half-expansion crop coordinates; not a visual quality metric."""
import math

def half_crop(box,canvas):
    x,y,w,h=box;W,H=canvas
    if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (*box,*canvas)) or min(w,h,W,H)<=0:
        raise ValueError('invalid frame/canvas dimensions')
    l=max(0,math.floor(x-w/2));t=max(0,math.floor(y-h/2))
    r=min(W,math.ceil(x+1.5*w));b=min(H,math.ceil(y+1.5*h))
    if r<=l or b<=t:raise ValueError('frame outside canvas')
    return l,t,r-l,b-t


def build_pack(original,current,scene,measured,out_dir):
    from pathlib import Path
    from PIL import Image
    from .state import write_json
    from .tp.inspect import inspect_overlaps,inspect_relations
    from .tp.groups import joint_recheck
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True);items=[]
    W,H=scene['canvas']['width'],scene['canvas']['height']
    with Image.open(original) as src,Image.open(current) as now:
        for obj in scene['objects']:
            if obj['kind']!='frame':continue
            b=measured[obj['id']]['geometry_bbox'];box=half_crop((b['left'],b['top'],b['right']-b['left'],b['bottom']-b['top']),(W,H))
            x,y,w,h=box;paths=[]
            for label,im in [('original',src),('current',now)]:
                sx,sy=im.width/W,im.height/H
                rectangle=(max(0,math.floor(x*sx)),max(0,math.floor(y*sy)),min(im.width,math.ceil((x+w)*sx)),min(im.height,math.ceil((y+h)*sy)))
                path=out/(obj['id']+'-'+label+'.png');im.crop(rectangle).save(path)
                paths.append(dict(path=str(path.resolve()),label=label,image_crop_xyxy=rectangle,canvas_to_image=[sx,0,0,sy,0,0]))
            items.append(dict(frame_id=obj['id'],name=obj['name'],canvas_crop=box,images=paths))
    result=dict(original=str(Path(original).resolve()),current=str(Path(current).resolve()),frames=items,
                relations=inspect_relations(scene,measured),overlaps=inspect_overlaps(scene,measured),
                joint_checks=joint_recheck(scene,measured),
                objects=[dict(id=o['id'],name=o['name'],kind=o['kind'],data=o['data']) for o in scene['objects']])
    write_json(out/'pack.json',result);return result
