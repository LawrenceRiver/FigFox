"""SVG affine transforms. compose(A,B) applies B first, then A."""
from math import isfinite
IDENTITY=[1,0,0,1,0,0]


def matrix(value):
    if len(value)!=6 or not all(isfinite(x) for x in value):
        raise ValueError('matrix requires six finite numbers')
    return list(value)


def apply(m,p):
    a,b,c,d,e,f=matrix(m)
    return [a*p[0]+c*p[1]+e,b*p[0]+d*p[1]+f]


def compose(outer,inner):
    a,b,c,d,e,f=matrix(outer);g,h,i,j,k,l=matrix(inner)
    return [a*g+c*h,b*g+d*h,a*i+c*j,b*i+d*j,a*k+c*l+e,b*k+d*l+f]


def inverse(m):
    a,b,c,d,e,f=matrix(m);det=a*d-b*c
    if abs(det)<1e-12: raise ValueError('singular or ill-conditioned matrix')
    return [d/det,-b/det,-c/det,a/det,(c*f-d*e)/det,(b*e-a*f)/det]


def translate_world(local,parent_world,dx,dy):
    """Conjugate canvas translation into parent coordinates; do not translate children twice."""
    return compose(inverse(parent_world),compose([1,0,0,1,dx,dy],compose(parent_world,local)))


def crop_to_canvas(crop,display_size,source_size,canvas_size):
    """Map coordinates in the displayed crop to canvas; crop is original-image xywh."""
    x,y,w,h=crop;dw,dh=display_size;sw,sh=source_size;cw,ch=canvas_size
    if not all(isfinite(v) for v in [x,y,w,h,dw,dh,sw,sh,cw,ch]) or min(w,h,dw,dh,sw,sh,cw,ch)<=0:
        raise ValueError('invalid crop or image dimensions')
    return compose([cw/sw,0,0,ch/sh,0,0],[w/dw,0,0,h/dh,x,y])


def normalize_frame_origins(scene):
    """Explicit frame-origin input dialect -> canonical SVG-parent coordinate Scene."""
    from copy import deepcopy
    out=deepcopy(scene)
    if out.get('coordinate_space')!='frame-origin':return out
    objects={o['id']:o for o in out['objects']}
    for obj in out['objects']:
        parent=objects.get(obj.get('parent_id'))
        if parent and parent['kind']=='frame':
            data=parent['data']
            origin=parent.get('child_origin')
            if origin is None:
                if data.get('shape')!='rect':raise ValueError('frame-origin requires rect parent or explicit child_origin for nonrect')
                origin=[data.get('x',0),data.get('y',0)]
            if len(origin)!=2 or not all(isfinite(v) for v in origin):raise ValueError('invalid child_origin')
            obj['matrix']=compose([1,0,0,1,*origin],obj.get('matrix',IDENTITY))
    out['coordinate_space']='svg-parent'
    return out
