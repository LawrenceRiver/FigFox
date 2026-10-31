"""Deterministic projected geometry; no model-generated raw paths required."""
from math import cos, sin, radians, isfinite


def point(p):
    if not isinstance(p,(list,tuple)) or len(p)!=2: raise ValueError('expected 2D point')
    if any(isinstance(x,bool) or not isinstance(x,(int,float)) or not isfinite(x) for x in p):
        raise ValueError('non-finite point')
    return tuple(float(x) for x in p)


def add(p,q): return (p[0]+q[0],p[1]+q[1])
def scale(p,s): return (p[0]*s,p[1]*s)
def cross(p,q): return p[0]*q[1]-p[1]*q[0]


def positive(x):
    if isinstance(x,bool) or not isinstance(x,(int,float)) or not isfinite(x) or x<=0:
        raise ValueError('expected positive finite length')
    return float(x)


def count(x):
    if isinstance(x,bool) or not isinstance(x,int) or not 1<=x<=100:
        raise ValueError('count must be integer in 1..100')
    return x


def depth_vector(length,angle_degrees):
    length=positive(length); angle=point((angle_degrees,0))[0]
    t=radians(angle)
    return length*cos(t),-length*sin(t)


def cuboid_faces(origin,u,v,depth):
    a,u,v,depth=map(point,(origin,u,v,depth))
    orientation=cross(u,v)
    if abs(orientation)<1e-9 or abs(depth[0])+abs(depth[1])<1e-9:
        raise ValueError('degenerate cuboid basis')
    b=add(a,u); d=add(a,v); c=add(b,v)
    front=[a,b,c,d]; faces={'front':front}
    for name,p,q in zip(('top','right','bottom','left'),front,front[1:]+front[:1]):
        edge=(q[0]-p[0],q[1]-p[1])
        outward=(edge[1],-edge[0]) if orientation>0 else (-edge[1],edge[0])
        if outward[0]*depth[0]+outward[1]*depth[1]>1e-9:
            faces[name]=[p,q,add(q,depth),add(p,depth)]
    if len(faces)!=3: raise ValueError('projection must show two non-degenerate adjoining faces')
    return faces


def polygon(part,points,fill,stroke='#222',width=1):
    pts=[point(p) for p in points]
    if len(pts)<3: raise ValueError('polygon needs at least three vertices')
    return {'part':part,'tag':'polygon','attrs':{
        'points':' '.join(f'{x:g},{y:g}' for x,y in pts),
        'fill':fill,'stroke':stroke,'stroke-width':width},'points':pts}


def line(part,p,q,stroke='#555',dash='3 2'):
    return {'part':part,'tag':'path','attrs':{
        'd':f'M {p[0]:g} {p[1]:g} L {q[0]:g} {q[1]:g}',
        'fill':'none','stroke':stroke,'stroke-width':0.8,'stroke-dasharray':dash},'points':[p,q]}


def cuboid(data):
    has_vector='depth' in data
    has_polar='depth_length' in data or 'depth_angle' in data
    if has_vector and has_polar: raise ValueError('choose depth vector OR length/angle, not both')
    depth=data['depth'] if has_vector else depth_vector(data['depth_length'],data['depth_angle'])
    faces=cuboid_faces(data['origin'],data['u'],data['v'],depth)
    colors=data.get('colors',{})
    defaults={'front':'#a7c78d','top':'#d3e4c4','bottom':'#789765','right':'#7b9f65','left':'#7b9f65'}
    return [polygon(k,faces[k],colors.get(k,data.get('fill',defaults[k])),data.get('stroke','#222'),data.get('stroke_width',1))
            for k in list(faces)[1:]+['front']]


def primitive(data):
    shape=data['shape'];fill=data.get('fill','#dce5ed');stroke=data.get('stroke','#222')
    if shape=='polygon': return [polygon('body',data['points'],fill,stroke)]
    if shape=='rect':
        x,y=point((data['x'],data['y']));w=positive(data['width']);h=positive(data['height'])
        return [{'part':'body','tag':'rect','attrs':{'x':x,'y':y,'width':w,'height':h,
                'fill':fill,'stroke':stroke,'rx':data.get('rx',0)},'points':[(x,y),(x+w,y+h)]}]
    if shape=='ellipse':
        x,y=point((data['cx'],data['cy']));rx=positive(data['rx']);ry=positive(data['ry'])
        return [{'part':'body','tag':'ellipse','attrs':{'cx':x,'cy':y,'rx':rx,'ry':ry,
                'fill':fill,'stroke':stroke},'points':[(x-rx,y-ry),(x+rx,y+ry)]}]
    raise ValueError(f'unsupported primitive: {shape}')


def cylinder(data):
    x,y=point((data['x'],data['y']));r=positive(data['radius']);h=positive(data['height'])
    ry=positive(data.get('ry',r/3));stroke=data.get('stroke','#222')
    body={'part':'body','tag':'path','attrs':{
        'd':f'M{x-r:g} {y:g} L{x-r:g} {y+h:g} A{r:g} {ry:g} 0 0 0 {x+r:g} {y+h:g} L{x+r:g} {y:g} Z',
        'fill':data.get('fill','#8aacca'),'stroke':stroke},'points':[(x-r,y),(x+r,y+h+ry)]}
    top=primitive({'shape':'ellipse','cx':x,'cy':y,'rx':r,'ry':ry,'fill':data.get('top','#dbeaf5'),'stroke':stroke})[0]
    top['part']='top'
    return [body,top]


def array(data):
    rows,cols=count(data['rows']),count(data['cols'])
    if rows*cols>400: raise ValueError('array too large')
    sx,sy=point(data['step_x']),point(data['step_y'])
    item=data['item']
    if item.get('shape') not in ('cuboid','rect','ellipse','polygon','cylinder'):
        raise ValueError('array item must be a primitive or cuboid/cylinder')
    parts=[]
    for row in range(rows):
        for col in range(cols):
            delta=add(scale(sx,col),scale(sy,row))
            for part in construct(item):
                part={**part,'part':f'cell-{row}-{col}.{part["part"]}',
                      'attrs':{**part['attrs'],'transform':f'translate({delta[0]:g} {delta[1]:g})'},
                      'points':[add(p,delta) for p in part['points']]}
                parts.append(part)
    return parts


def cluster(data):
    items=data['items']
    if not isinstance(items,list) or not 1<=len(items)<=400: raise ValueError('cluster needs 1..400 items')
    if data.get('order','as_given')!='as_given': raise ValueError('only explicit back-to-front item order supported')
    parts=[]
    for i,item in enumerate(items):
        if item.get('shape')!='cuboid': raise ValueError('cluster items must be cuboids')
        for p in cuboid(item): parts.append({**p,'part':f'item-{i}.{p["part"]}'})
    return parts


def lattice(data):
    allowed={'shape','origin','u','v','depth','divisions','grid','slices','slice_fill','slice_opacity','stroke','dash','shell','colors','fill','stroke_width'}
    unknown=set(data)-allowed
    if unknown:
        raise ValueError('lattice unsupported parameters: '+', '.join(sorted(unknown))+'; use colors/fill for flat visible faces; use vector_asset for complex local texture.')
    o,u,v,d=map(point,(data['origin'],data['u'],data['v'],data['depth']))
    faces=cuboid_faces(o,u,v,d)
    width=positive(data.get('stroke_width',.8))
    colors=data.get('colors',{})
    if not isinstance(colors,dict) or set(colors)-{'front','top','right','bottom','left'}:raise ValueError('invalid lattice face colors')
    filled=bool(colors) or data.get('fill','none')!='none'
    nu,nv,nd=[count(n) for n in data.get('divisions',[3,4,3])]
    grid=data.get('grid','faces')
    if grid not in ('none','faces','volume'): raise ValueError('unknown lattice grid')
    def at(i,j,k): return add(o,add(scale(u,i),add(scale(v,j),scale(d,k))))
    parts=[]
    if filled:
        for name in list(faces)[1:]+['front']:
            parts.append(polygon('surface-'+name,faces[name],colors.get(name,data.get('fill','#dce5ed')),'none',0))
    for n,t in enumerate(data.get('slices',[])):
        if not isinstance(t,(int,float)) or not 0<t<1: raise ValueError('slice fraction must be in (0,1)')
        p=polygon(f'slice-{n}',[at(t,0,0),at(t,1,0),at(t,1,1),at(t,0,1)],
                  data.get('slice_fill','#72a84b'),'none',0)
        p['attrs']['opacity']=data.get('slice_opacity',0.65);parts.append(p)
    edges=set()
    def edge(p,q):
        key=tuple(sorted((tuple(round(x,9) for x in p),tuple(round(x,9) for x in q))))
        if key not in edges:
            edges.add(key)
            part=line(f'edge-{len(edges)}',p,q,data.get('stroke','#555'),data.get('dash','' if filled else '3 2'))
            part['attrs']['stroke-width']=width;parts.append(part)
    divisions=(nu,nv,nd)
    for axis in range(3):
        other=[n for n in range(3) if n!=axis]
        na,nb=(divisions[n] for n in other)
        for a in range(na+1):
            for b in range(nb+1):
                boundary_a=a in (0,na);boundary_b=b in (0,nb)
                if boundary_a and boundary_b and not data.get('shell',True): continue
                if grid=='none' and not (boundary_a and boundary_b): continue
                if grid=='faces' and not (boundary_a or boundary_b): continue
                p=[0.,0.,0.];p[other[0]]=a/na;p[other[1]]=b/nb
                q=p.copy();q[axis]=1.
                if filled:
                    planes={'front':(2,0.),'top':(1,0.),'bottom':(1,1.),'right':(0,1.),'left':(0,0.)}
                    if not any(axis!=planes[name][0] and p[planes[name][0]]==planes[name][1] for name in faces):continue
                edge(at(*p),at(*q))
    return parts


CONSTRUCTORS={'rect':primitive,'ellipse':primitive,'polygon':primitive,'cuboid':cuboid,
              'cylinder':cylinder,'array':array,'cluster':cluster,'lattice':lattice}


def construct(data):
    shape=data.get('shape')
    if shape not in CONSTRUCTORS: raise ValueError(f'unsupported geometry: {shape}')
    fields={
        'rect':{'x','y','width','height','rx','radius'},
        'ellipse':{'cx','cy','rx','ry'},'polygon':{'points'},
        'cuboid':{'origin','u','v','depth','depth_length','depth_angle','colors'},
        'cylinder':{'x','y','radius','height','ry','top'},
        'array':{'rows','cols','step_x','step_y','item'},'cluster':{'items','order'},
    }
    if shape in fields:
        style_fields={'fill','stroke','stroke_width','stroke_dasharray','stroke_dashoffset'} if shape not in ('array','cluster') else set()
        unknown=set(data)-fields[shape]-{'shape'}-style_fields
        if unknown:raise ValueError(shape+' unsupported parameters: '+', '.join(sorted(unknown))+'; grid requires lattice, texture requires a classified asset')
    parts=CONSTRUCTORS[shape](data)
    for p in parts:
        for key,attribute in [('stroke_width','stroke-width'),('stroke_dasharray','stroke-dasharray'),('stroke_dashoffset','stroke-dashoffset')]:
            if key in data:p['attrs'][attribute]=data[key]
    return parts
