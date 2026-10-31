"""Local region coordinate evidence; does not prescribe repairs or infer relations."""
import math
from PIL import Image
from ..tp.transforms import inverse

def build_local_tp(bounds,frames,original,current):
    c=bounds['canvas'];cw,ch=c['width'],c['height']
    with Image.open(original) as im:sw,sh=im.size
    with Image.open(current) as im:nw,nh=im.size
    regions=[]
    for f in frames:
        x,y,w,h=f['canvas_crop'];objects={}
        for oid,o in bounds['objects'].items():
            b=o.get('geometry_bbox')
            if not b:continue
            l,t,r,bt=b['left'],b['top'],b['right'],b['bottom']
            if r<x or l>x+w or bt<y or t>y+h:continue
            # A containing ancestor isn't a local movable object merely by intersection.
            if oid!=f['frame_id'] and l<=x and t<=y and r>=x+w and bt>=y+h:continue
            objects[oid]={'region_bbox':[l-x,t-y,r-l,bt-t],'bounds_complete':o.get('bounds_complete',False)}
        maps={}
        for label,iw,ih in [('original',sw,sh),('current',nw,nh)]:
            sx,sy=iw/cw,ih/ch
            left=math.floor((x-c['x'])*sx);top=math.floor((y-c['y'])*sy)
            rect=[left,top,math.ceil((x-c['x']+w)*sx),math.ceil((y-c['y']+h)*sy)]
            matrix=[1/sx,0,0,1/sy,c['x']+left/sx,c['y']+top/sy]
            maps[label]={'pixel_rect':rect,'crop_pixel_to_canvas':matrix}
        regions.append({'frame_id':f['frame_id'],'canvas_crop':[x,y,w,h],'region_to_canvas':[1,0,0,1,x,y],'objects':objects,'crop_maps':maps,'display_scale':f['display_scale'],'pair_current_offset':[round((maps['original']['pixel_rect'][2]-maps['original']['pixel_rect'][0])*f['display_scale'])+12,34]})
    transforms={}
    for oid,o in bounds['objects'].items():
        if 'world' in o:
            try:transforms[oid]=inverse(o['world'])
            except ValueError:pass
    return {'regions':regions,'canvas_to_object_local':transforms,'contract':'region coordinates are canvas units relative to crop origin; image pixel maps include crop rounding. TP translate/fit use canvas; SP/svg/asset targets use existing object local coordinates. Bounds do not prove visual correctness.'}
