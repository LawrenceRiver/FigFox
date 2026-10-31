"""Neutral global marker contribution diagnostic. No native/controller imports.

Callbacks receive (svg_text, exclusive_output_png). They are synchronous and are
not cancellable here. Limits are preflight estimates and a soft elapsed limit,
never an enforceable deadline or a sandbox for a hostile renderer.
"""
from dataclasses import dataclass
from copy import deepcopy
import base64
from io import BytesIO
import os
import stat
import tempfile
import hashlib
import json
from pathlib import Path
import re
import time

from lxml import etree as ET
import lxml
import numpy as np
from PIL import Image, __version__ as pillow_version
import tinycss2
from tinycss2.color3 import parse_color

SVG_NS='http://www.w3.org/2000/svg'
class Unsupported(ValueError): pass
class IntegrityError(ValueError): pass
class InfrastructureError(OSError): pass

@dataclass(frozen=True)
class Limits:
    max_pixels: int
    max_input_bytes: int
    max_peak_bytes: int
    max_artifact_bytes: int
    soft_seconds: float

PROPERTIES={'fill','stroke','color','opacity','fill-opacity','stroke-opacity','stroke-width',
            'stroke-linecap','stroke-linejoin','stroke-miterlimit','stroke-dasharray','stroke-dashoffset',
            'fill-rule','marker-start','marker-mid','marker-end','display','visibility'}
ATTRS={
    'svg':{'width','height','viewBox','preserveAspectRatio','version'},
    'defs':set(), 'style':{'type'}, 'marker':{'markerWidth','markerHeight','refX','refY','viewBox','orient','markerUnits','preserveAspectRatio'},
    'g':set(), 'path':{'d','pathLength'}, 'rect':{'x','y','width','height','rx','ry'},
    'circle':{'cx','cy','r'},'ellipse':{'cx','cy','rx','ry'},'line':{'x1','y1','x2','y2'},
    'polyline':{'points'},'polygon':{'points'},'title':set(),'desc':set(),
}
RENDERABLE={'g','path','rect','circle','ellipse','line','polyline','polygon'}
FONT_PROPERTIES={'font-family','font-size','font-weight','font-style','letter-spacing','text-anchor','dominant-baseline'}
PROPERTIES |= FONT_PROPERTIES | {'stop-color','stop-opacity'}
ATTRS.update({
    'text':{'x','y','dx','dy'},'tspan':{'x','y','dx','dy'},
    'image':{'x','y','width','height','preserveAspectRatio'},
    'linearGradient':{'x1','y1','x2','y2','gradientUnits','gradientTransform','spreadMethod'},
    'radialGradient':{'cx','cy','r','fx','fy','fr','gradientUnits','gradientTransform','spreadMethod'},
    'stop':{'offset'},
})
RENDERABLE |= {'text','image'}
XML_SPACE='{http://www.w3.org/XML/1998/namespace}space'
XLINK_HREF='{http://www.w3.org/1999/xlink}href'
NUMBER=r'[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?'
NUM_RE=re.compile(NUMBER)
LENGTH_RE=re.compile(NUMBER+r'(?:px|%)?\Z')

def sha_bytes(data): return hashlib.sha256(data).hexdigest()

def sha_file(path):
    digest=hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda:stream.read(65536),b''):digest.update(chunk)
    return digest.hexdigest()

def _tag(node):
    if not isinstance(node.tag,str): return None
    q=ET.QName(node)
    if q.namespace!=SVG_NS: raise Unsupported('non-SVG namespace')
    return q.localname

def _parse(text):
    if '<!DOCTYPE' in text.upper() or '<!ENTITY' in text.upper() or '<?' in text:
        raise Unsupported('DTD, entities and processing instructions unsupported')
    try:root=ET.fromstring(text.encode(),ET.XMLParser(resolve_entities=False,no_network=True,remove_comments=False))
    except (ET.XMLSyntaxError,ValueError) as exc:raise Unsupported('malformed XML: '+str(exc)) from exc
    if _tag(root)!='svg':raise Unsupported('root is not SVG')
    return root

def _tokens(tokens): return [t for t in tokens if t.type not in ('whitespace','comment')]

def _selector(prelude):
    parts=[[]]
    for token in prelude:
        if token.type=='literal' and token.value==',':parts.append([])
        else:parts[-1].append(token)
    for part in parts:
        while part and part[0].type in ('whitespace','comment'):part.pop(0)
        while part and part[-1].type in ('whitespace','comment'):part.pop()
        valid=(len(part)==1 and part[0].type=='ident' and part[0].value in ATTRS) or (len(part)==1 and part[0].type=='hash' and part[0].is_identifier) or (len(part)==2 and part[0].type=='literal' and part[0].value=='.' and part[1].type=='ident')
        if not valid:raise Unsupported('only simple type/class/id selectors and selector lists supported')

def _value(name,tokens,ids,paints=None):
    paints=set() if paints is None else paints
    tt=_tokens(tokens);v=tinycss2.serialize(tt).strip()
    if not tt or any(t.type=='error' for t in tt):raise Unsupported('empty or malformed property '+name)
    if any(t.type in ('at-keyword','{} block','[] block','() block') for t in tt):raise Unsupported('unsupported property construct')
    if v in ('inherit','initial','unset'):return
    if name in ('marker-start','marker-mid','marker-end'):
        if v=='none':return
        if len(tt)==1 and tt[0].type=='url': ref=tt[0].value
        elif len(tt)==1 and tt[0].type=='function' and tt[0].lower_name=='url':
            args=_tokens(tt[0].arguments)
            if len(args)!=1 or args[0].type!='string':raise Unsupported('ambiguous marker URL')
            ref=args[0].value
        else:raise Unsupported('unsupported marker reference')
        if not ref.startswith('#') or ref[1:] not in ids:raise Unsupported('external or unresolved marker reference')
        return
    if name in ('fill','stroke') and (any(t.type=='url' for t in tt) or any(t.type=='function' and t.lower_name=='url' for t in tt)):
        _value('marker-end',tokens,paints);return
    if name in ('fill','stroke','color','stop-color'):
        if v=='none' and name in ('fill','stroke'):return
        if len(tt)!=1 or parse_color(tt[0]) is None:raise Unsupported('non-solid or unknown color')
        return
    if any(t.type=='function' or t.type=='url' for t in tt):raise Unsupported('unsupported function')
    if name in ('opacity','fill-opacity','stroke-opacity','stop-opacity'):
        if len(tt)!=1 or tt[0].type not in ('number','percentage'):raise Unsupported('unsupported opacity')
        if not 0<=tt[0].value<=(100 if tt[0].type=='percentage' else 1):raise Unsupported('opacity outside small grammar')
    elif name in FONT_PROPERTIES:
        if name=='font-family':
            if any(t.type not in ('ident','string') and not (t.type=='literal' and t.value==',') for t in tt) or tt[0].type=='literal' or tt[-1].type=='literal':raise Unsupported('unsupported static font family')
            groups=[[]]
            for token in tt:
                if token.type=='literal':groups.append([])
                else:groups[-1].append(token)
            if any(not group or not (all(t.type=='ident' for t in group) or len(group)==1 and group[0].type=='string') for group in groups):raise Unsupported('malformed font family')
        elif name in ('font-size','letter-spacing'):
            if name=='letter-spacing' and v=='normal':return
            if not LENGTH_RE.fullmatch(v) or not np.isfinite(float(NUM_RE.match(v)[0])):raise Unsupported('unsupported font length')
            if name=='font-size' and float(NUM_RE.match(v)[0])<0:raise Unsupported('negative font size')
        else:
            choices={'font-weight':{'normal','bold','bolder','lighter'}|{str(n) for n in range(100,1000,100)},'font-style':{'normal','italic','oblique'},'text-anchor':{'start','middle','end'},'dominant-baseline':{'auto','alphabetic','ideographic','middle','central','mathematical','hanging','text-top','text-bottom'}}
            if v not in choices[name]:raise Unsupported('unsupported font/text keyword '+name)
    elif name in ('stroke-width','stroke-dashoffset','stroke-miterlimit'):
        if not LENGTH_RE.fullmatch(v) or not np.isfinite(float(NUM_RE.match(v)[0])):raise Unsupported('unsupported numeric property')
    elif name=='stroke-dasharray':
        if v!='none' and any(t.type not in ('number','dimension','percentage') and not (t.type=='literal' and t.value==',') for t in tt):raise Unsupported('unsupported dash array')
        if any(t.type=='dimension' and t.lower_unit!='px' for t in tt):raise Unsupported('unsupported dash unit')
    else:
        values={'stroke-linecap':{'butt','round','square'},'stroke-linejoin':{'miter','round','bevel'},'fill-rule':{'nonzero','evenodd'},'display':{'inline','none'},'visibility':{'visible','hidden','collapse'}}
        if v not in values.get(name,set()):raise Unsupported('unsupported keyword '+name)

def _declarations(text,ids,paints=None):
    result=tinycss2.parse_declaration_list(text,skip_comments=False,skip_whitespace=False)
    for d in result:
        if d.type in ('whitespace','comment'):continue
        if d.type!='declaration' or d.lower_name not in PROPERTIES:raise Unsupported('unknown or malformed declaration')
        _value(d.lower_name,d.value,ids,paints)
    return result

def _transform(value):
    # Lexical grammar for transform attributes, not a CSS parser.
    pos=0;count=0
    for m in re.finditer(r'([A-Za-z]+)\s*\(([^()]*)\)',value):
        if value[pos:m.start()].strip(' ,\t\r\n'):raise Unsupported('malformed affine transform')
        args=m[2]; nums=NUM_RE.findall(args)
        if NUM_RE.sub('',args).strip(' ,\t\r\n'):raise Unsupported('malformed transform numbers')
        arities={'matrix':{6},'translate':{1,2},'scale':{1,2},'rotate':{1,3},'skewX':{1},'skewY':{1}}
        if len(nums) not in arities.get(m[1],set()) or any(not np.isfinite(float(n)) for n in nums):raise Unsupported('unsupported affine transform')
        pos=m.end();count+=1
    if not count or value[pos:].strip():raise Unsupported('malformed affine transform')

def _finite(value,percentage=True,nonnegative=False):
    if not re.fullmatch(NUMBER+(r'%?' if percentage else ''),value):raise Unsupported('unsupported static numeric value')
    number=float(value.removesuffix('%'))
    if not np.isfinite(number) or (nonnegative and number<0):raise Unsupported('nonfinite or negative static numeric value')
    return number

def _lengths(value):
    tokens=_tokens(tinycss2.parse_component_value_list(value))
    if not tokens or any(t.type not in ('number','percentage','dimension') or (t.type=='dimension' and t.lower_unit!='px') or not np.isfinite(t.value) for t in tokens):raise Unsupported('unsupported static text geometry')

def _embedded_image(node):
    refs=[node.get(k) for k in ('href',XLINK_HREF) if node.get(k) is not None]
    if len(refs)!=1:raise Unsupported('image requires exactly one self-contained raster href')
    match=re.fullmatch(r'data:image/(png|jpeg);base64,([A-Za-z0-9+/]*={0,2})',refs[0])
    if not match:raise Unsupported('only self-contained base64 PNG/JPEG image resources supported')
    try:
        data=base64.b64decode(match[2],validate=True)
        if base64.b64encode(data).decode()!=match[2]:raise ValueError('noncanonical base64')
        with Image.open(BytesIO(data)) as im:
            if im.format!={'png':'PNG','jpeg':'JPEG'}[match[1]] or getattr(im,'n_frames',1)!=1:raise ValueError('MIME/format mismatch or animated raster')
            if im.width*im.height>4194304:raise ValueError('embedded raster pixel bound exceeded')
            dimensions=list(im.size);im.verify()
    except Exception as exc:raise Unsupported('invalid embedded PNG/JPEG resource: '+str(exc)) from exc
    for key in ('x','y','width','height'):
        value=node.get(key,'0' if key in ('x','y') else '')
        if not re.fullmatch(NUMBER+r'(?:px)?',value):raise Unsupported('explicit static image geometry required')
        number=_finite(value.removesuffix('px'),percentage=False)
        if key in ('width','height') and number<=0:raise Unsupported('positive image dimensions required')
    return {'mime_type':'image/'+match[1],'sha256':sha_bytes(data),'data_uri_sha256':sha_bytes(refs[0].encode()),'dimensions':dimensions}

def _validate(root):
    nodes=list(root.iter());ids={};markers=set();paints=set();resources=[]
    for n in nodes:
        tag=_tag(n)
        if tag is None:continue
        if tag not in ATTRS:raise Unsupported('unsupported element '+tag)
        if tag=='svg' and n is not root:raise Unsupported('nested SVG unsupported')
        ident=n.get('id')
        if ident:
            if ident in ids:raise Unsupported('duplicate id')
            ids[ident]=n
        if tag in ('marker','linearGradient','radialGradient'):
            if not ident or _tag(n.getparent())!='defs' or any(_tag(p)=='marker' for p in n.iterancestors()):raise Unsupported('ambiguous marker/paint definition')
            (markers if tag=='marker' else paints).add(ident)
    for n in nodes:
        tag=_tag(n)
        if tag is None:continue
        if tag not in ('style','title','desc','text','tspan') and n.text and n.text.strip():raise Unsupported('unexpected text content')
        if n.tail and n.tail.strip() and _tag(n.getparent()) not in ('text','tspan'):raise Unsupported('unexpected text tail')
        if tag in ('style','title','desc') and len(n):raise Unsupported('nested textual element')
        if tag in ('text','tspan') and any(_tag(child) not in ('tspan',None) for child in n):raise Unsupported('unsupported text child')
        if tag=='tspan' and _tag(n.getparent()) not in ('text','tspan'):raise Unsupported('tspan outside text')
        if tag in ('linearGradient','radialGradient') and any(_tag(child) not in ('stop',None) for child in n):raise Unsupported('unsupported gradient child')
        if tag=='stop' and (_tag(n.getparent()) not in ('linearGradient','radialGradient') or len(n)):raise Unsupported('stop outside admitted gradient')
        if tag=='image':
            if any(_tag(child) not in ('title','desc',None) for child in n):raise Unsupported('unsupported image child')
            resources.append(_embedded_image(n))
        for attr,value in n.attrib.items():
            if attr in ('href',XLINK_HREF) and tag=='image':continue
            if attr==XML_SPACE and tag in ('text','tspan'):
                if value not in ('default','preserve'):raise Unsupported('unsafe xml:space')
            elif attr in PROPERTIES:_value(attr,tinycss2.parse_component_value_list(value),markers,paints)
            elif attr=='style':_declarations(value,markers,paints)
            elif attr in ('transform','gradientTransform'):
                if attr=='gradientTransform' and tag not in ('linearGradient','radialGradient'):raise Unsupported('misplaced gradient transform')
                _transform(value)
            elif attr not in ATTRS[tag]|{'id','class'}:raise Unsupported('unsupported attribute '+attr)
            elif tag in ('text','tspan') and attr in ('x','y','dx','dy'):_lengths(value)
            elif tag in ('linearGradient','radialGradient') and attr in ('x1','y1','x2','y2','cx','cy','r','fx','fy','fr'):_finite(value,nonnegative=attr in ('r','fr'))
            elif attr=='preserveAspectRatio':
                if value!='none' and not re.fullmatch(r'x(?:Min|Mid|Max)Y(?:Min|Mid|Max)(?: (?:meet|slice))?',value):raise Unsupported('unknown static preserveAspectRatio')
            elif attr=='gradientUnits' and value not in ('objectBoundingBox','userSpaceOnUse'):raise Unsupported('unknown gradient units')
            elif attr=='spreadMethod' and value not in ('pad','reflect','repeat'):raise Unsupported('unknown gradient spread')
            elif tag=='stop' and attr=='offset':
                number=_finite(value)
                if not 0<=number<=(100 if value.endswith('%') else 1):raise Unsupported('gradient stop offset outside 0..1')
        if tag=='style':
            if n.get('type','text/css')!='text/css':raise Unsupported('unsupported style type')
            for rule in tinycss2.parse_stylesheet(n.text or '',skip_comments=True,skip_whitespace=True):
                if rule.type!='qualified-rule':raise Unsupported('at-rule or malformed stylesheet')
                _selector(rule.prelude);_declarations(rule.content,markers,paints)
    for key in ('width','height'):
        if not re.fullmatch(r'\d+(?:px)?',root.get(key,'')) or int(root.get(key).removesuffix('px'))<=0:raise Unsupported('explicit positive integer canvas dimensions required')
    width=int(root.get('width').removesuffix('px'));height=int(root.get('height').removesuffix('px'))
    if root.get('viewBox'):
        v=root.get('viewBox');numbers=NUM_RE.findall(v)
        if NUM_RE.sub('',v).strip(' ,\t\r\n') or len(numbers)!=4 or [float(x) for x in numbers]!=[0,0,width,height]:raise Unsupported('unsupported viewBox/canvas correspondence')
    return markers,(width,height),paints,resources

def _projection(root,targets):
    # Bytes-as-parsed XML projection with only target style attributes removed.
    copy=deepcopy(root)
    for index,n in enumerate(copy.iter()):
        if index in targets:n.attrib.pop('style',None)
    return ET.tostring(copy,method='c14n',with_comments=True)

def hide_marker_content(text):
    root=_parse(text);markers,dimensions,paints,resources=_validate(root)
    targets=[]
    for marker in root.iter('{'+SVG_NS+'}marker'):
        for child in marker:
            if _tag(child) in RENDERABLE:targets.append(child)
            elif _tag(child) not in ('title','desc',None):raise Unsupported('non-renderable or ambiguous marker child')
    target_indexes={i for i,n in enumerate(root.iter()) if n in targets}
    original_projection=_projection(root,target_indexes)
    originals={i:tinycss2.serialize(_declarations(n.get('style',''),markers,paints)) for i,n in enumerate(root.iter()) if i in target_indexes}
    for node in targets:
        declarations=_declarations(node.get('style',''),markers,paints)
        # Remove every competing opacity declaration, preserving other parsed declarations.
        retained=[d for d in declarations if not (d.type=='declaration' and d.lower_name=='opacity')]
        style=tinycss2.serialize(retained)
        if style.strip() and not style.rstrip().endswith(';'):style+=';'
        node.set('style',style+'opacity:0!important;')
    serialized=ET.tostring(root,encoding='unicode')
    reparsed=_parse(serialized)
    if _projection(reparsed,target_indexes)!=original_projection:raise IntegrityError('intervention modified non-target XML')
    # Prove non-opacity declarations preserved bytes-as-parsed on targets too.
    for i,n in enumerate(reparsed.iter()):
        if i in target_indexes:
            previous=_declarations(originals[i],markers,paints);current=_declarations(n.get('style'),markers,paints)
            strip=lambda ds:tinycss2.serialize([d for d in ds if not (d.type=='declaration' and d.lower_name=='opacity')])
            if strip(previous)!=strip(current):raise IntegrityError('intervention modified unrelated declaration')
    return serialized,{'hidden_top_level_children':len(targets),'markers':len(markers),'paint_servers':len(paints),'embedded_resources':resources,'canvas_dimensions':list(dimensions),'preservation':'non-target XML canonical bytes-as-parsed; target non-opacity declaration serialization; no computed-style equivalence claim'}

def contribution(normal,hidden):
    if normal.dtype!=np.uint8 or hidden.dtype!=np.uint8 or normal.shape!=hidden.shape or normal.ndim!=3 or normal.shape[2]!=4:raise ValueError('requires equal uint8 RGBA arrays')
    n=normal.astype(np.int32);h=hidden.astype(np.int32)
    return n[:,:,:3]*n[:,:,3,None]+255*(255-n[:,:,3,None])-h[:,:,:3]*h[:,:,3,None]-255*(255-h[:,:,3,None])

def cells(width,height):
    x=width//2;y=height//2
    return [(0,0,x,y),(x,0,width,y),(0,y,x,height),(x,y,width,height)]

def counts(before,candidate):
    b=np.any(before!=0,axis=2);c=np.any(candidate!=0,axis=2);changed=np.any(before!=candidate,axis=2)
    return dict(before_contributing=int(b.sum()),candidate_contributing=int(c.sum()),lost=int((b&~c).sum()),gained=int((~b&c).sum()),altered=int((b&c&changed).sum()),changed=int(changed.sum()))

def _plain_path(path,exists=True):
    p=Path(path)
    if not p.is_absolute():p=Path.cwd()/p
    if '..' in p.parts:raise IntegrityError('parent traversal path unsupported')
    for q in [p,*p.parents]:
        if q.is_symlink():raise IntegrityError('symlink path unsupported: '+str(q))
    if exists and not p.is_file():raise IntegrityError('missing/non-file input: '+str(p))
    return p

def _png(path,max_pixels):
    with Image.open(path) as im:
        if im.format!='PNG':raise ValueError('input/output is not PNG')
        if im.width*im.height>max_pixels:raise Unsupported('pixel bound exceeded')
        a=np.array(im.convert('RGBA'),dtype=np.uint8)
    return a

def _publish(path,writer):
    """Atomic create-only publication; never overwrite a callback/planted artifact."""
    path=Path(path);temporary=None
    try:
        if path.exists() or path.is_symlink():raise IntegrityError('host-owned output path already exists: '+path.name)
        fd,temporary=tempfile.mkstemp(prefix='.'+path.name+'-',dir=path.parent)
        with os.fdopen(fd,'wb') as stream:
            writer(stream);stream.flush();os.fsync(stream.fileno())
        try:os.link(temporary,path)
        except FileExistsError as exc:raise IntegrityError('host-owned output collision: '+path.name) from exc
    except IntegrityError:raise
    except OSError as exc:raise InfrastructureError('output storage/infrastructure failure: '+str(exc)) from exc
    finally:
        if temporary is not None:
            try:os.unlink(temporary)
            except OSError:pass


def build(*,before_svg,before_png,candidate_svg,candidate_png,original_png,output_dir,renderer,expected_sha256,limits):
    """Create one exclusive report; input/output mutation raises IntegrityError.

    Synchronous callbacks must stop writing when they return. Hashes do not guard
    hostile writes after final validation or provide a concurrent filesystem sandbox.
    """
    start=time.monotonic();calls=0
    paths={k:_plain_path(v) for k,v in dict(before_svg=before_svg,before_png=before_png,candidate_svg=candidate_svg,candidate_png=candidate_png,original_png=original_png).items()}
    if set(expected_sha256)!=set(paths):raise IntegrityError('expected hashes must bind exactly all five inputs')
    initial={k:sha_file(p) for k,p in paths.items()}
    if initial!=expected_sha256:raise IntegrityError('input SHA256 mismatch')
    if any(not isinstance(getattr(limits,k),(int,float)) or not np.isfinite(getattr(limits,k)) or getattr(limits,k)<=0 for k in limits.__dataclass_fields__):raise ValueError('explicit positive finite limits required')
    out=_plain_path(output_dir,exists=False)
    if out.exists():raise IntegrityError('output directory already exists')
    if not out.parent.is_dir():raise IntegrityError('output parent must already exist')
    try:out.mkdir()
    except OSError as exc:raise InfrastructureError('output storage/infrastructure failure: '+str(exc)) from exc
    bindings={k:{'path':str(p),'sha256':initial[k],'bytes':p.stat().st_size} for k,p in paths.items()}
    report={'schema':'neutral-marker-field/2','status':'field_unavailable','bindings':bindings,'counts':None,'audit':None,
            'source_correspondence':{'status':'not_asserted','reason':'actual original raster bound; source-to-SVG coordinate transform and semantic correspondence are not established'},
            'limitations':['globally unattributed pixel counts; no head count/identity, source necessity, preservation certification or edit authority','zero field cannot establish successful intervention or absence; equal-color/coincident substitution blind spot','no repair findings, automatic todo or review obligations','callbacks must stop writing on return; no concurrent/hostile post-return-write sandbox'],
            'dependencies':{'numpy':np.__version__,'pillow':pillow_version,'tinycss2':tinycss2.__version__,'lxml':lxml.__version__},
            'limits':{k:getattr(limits,k) for k in limits.__dataclass_fields__},'deadline':'soft elapsed checks only; synchronous injected callback is not cancellable'}
    pins={};arrays={};host_pins={}
    def rehash():
        for k,p in paths.items():
            _plain_path(p)
            if sha_file(p)!=initial[k]:raise IntegrityError('input changed during callbacks: '+k)
    def validate_outputs():
        for name,pin in pins.items():
            path=out/name;_plain_path(path)
            current=path.stat()
            if not stat.S_ISREG(current.st_mode) or [current.st_dev,current.st_ino]!=pin['file_identity'] or sha_file(path)!=pin['sha256']:raise IntegrityError('completed renderer output changed: '+name)
            try:decoded=_png(path,limits.max_pixels)
            except Exception as exc:raise IntegrityError('completed renderer output no longer decodes: '+name) from exc
            if list(decoded.shape[1::-1])!=pin['dimensions'] or sha_bytes(decoded.tobytes())!=pin['decoded_rgba_sha256'] or not np.array_equal(decoded,arrays[name]):raise IntegrityError('completed renderer output pixels changed: '+name)
        for name,expected in host_pins.items():
            path=out/name;_plain_path(path)
            if sha_file(path)!=expected:raise IntegrityError('host-owned artifact changed: '+name)
    def validate_all():rehash();validate_outputs()
    def publish_text(name,text):
        _publish(out/name,lambda stream:stream.write(text.encode('utf-8')));host_pins[name]=sha_file(out/name)
    def render(text,name):
        nonlocal calls
        if calls>=4:raise IntegrityError('callback cap exceeded')
        if time.monotonic()-start>limits.soft_seconds:raise Unsupported('soft elapsed bound exceeded')
        path=out/(name+'.png');calls+=1
        if path.exists() or path.is_symlink():raise IntegrityError('renderer output already exists')
        try:renderer(text,path)
        except Exception as exc:raise Unsupported('renderer failure: '+str(exc)) from exc
        finally:validate_all()
        _plain_path(path,exists=False)
        if not path.is_file():raise Unsupported('renderer output missing/non-file')
        current=path.stat()
        if not stat.S_ISREG(current.st_mode):raise IntegrityError('renderer output is not regular file')
        if sum(p.stat().st_size for p in out.iterdir() if p.is_file())>limits.max_artifact_bytes:raise Unsupported('artifact bound exceeded')
        try:a=_png(path,limits.max_pixels)
        except Exception as exc:raise Unsupported('renderer output decode failure: '+str(exc)) from exc
        arrays[path.name]=a;a.flags.writeable=False
        pins[path.name]={'sha256':sha_file(path),'decoded_rgba_sha256':sha_bytes(a.tobytes()),'dimensions':list(a.shape[1::-1]),'bytes':current.st_size,'file_identity':[current.st_dev,current.st_ino]}
        validate_all()
        if time.monotonic()-start>limits.soft_seconds:raise Unsupported('soft elapsed bound exceeded after callback')
        return a
    try:
        dims={}
        for key in ('before_png','candidate_png','original_png'):
            try:
                with Image.open(paths[key]) as im:
                    if im.format!='PNG':raise IntegrityError('supplied input is not PNG: '+key)
                    dims[key]=im.size;bindings[key]['dimensions']=list(im.size)
            except Unsupported:raise
            except Exception as exc:raise IntegrityError('invalid supplied PNG '+key+': '+str(exc)) from exc
        if any(p.stat().st_size>limits.max_input_bytes for p in paths.values()):raise Unsupported('input byte bound exceeded')
        if any(w*h>limits.max_pixels for w,h in dims.values()):raise Unsupported('pixel bound exceeded')
        if dims['before_png']!=dims['candidate_png']:raise Unsupported('endpoint canvas dimensions differ')
        width,height=dims['before_png'];pixels=width*height
        peak=max(pixels*160,dims['original_png'][0]*dims['original_png'][1]*16)+sum(p.stat().st_size for p in paths.values())*8+262144
        artifact=pixels*48+sum(p.stat().st_size for p in paths.values())*4+131072
        report['preflight']={'estimated_peak_bytes':peak,'estimated_artifact_bytes':artifact,'chunk_rows':32,'memory_is_estimate_not_process_RSS_cap':True}
        if peak>limits.max_peak_bytes:raise Unsupported('estimated peak memory bound exceeded')
        if artifact>limits.max_artifact_bytes:raise Unsupported('estimated artifact bound exceeded')
        for key in ('before_png','candidate_png','original_png'):
            try:a=_png(paths[key],limits.max_pixels)
            except Exception as exc:raise IntegrityError('invalid supplied PNG '+key+': '+str(exc)) from exc
            bindings[key]['decoded_rgba_sha256']=sha_bytes(a.tobytes());del a
        texts={}
        for key in ('before','candidate'):
            try:texts[key]=paths[key+'_svg'].read_text(encoding='utf-8')
            except UnicodeDecodeError as exc:raise Unsupported('unsupported SVG UTF-8 encoding at '+key+' endpoint') from exc
        transformed={};meta={}
        for key,text in texts.items():
            transformed[key],meta[key]=hide_marker_content(text)
            if meta[key]['canvas_dimensions']!=[width,height]:raise Unsupported('SVG/PNG canvas correspondence unsupported')
            publish_text(key+'-hidden.svg',transformed[key])
        report['intervention']=meta
        embedded_pixels=max([item['dimensions'][0]*item['dimensions'][1] for item in meta.values() for item in item['embedded_resources']]+[0])
        report['preflight']['estimated_peak_bytes']+=embedded_pixels*16
        if report['preflight']['estimated_peak_bytes']>limits.max_peak_bytes:raise Unsupported('embedded raster peak estimate exceeds memory bound')
        normal={key:render(texts[key],key+'-normal') for key in ('before','candidate')}
        for key in normal:
            existing=_png(paths[key+'_png'],limits.max_pixels)
            if not np.array_equal(normal[key],existing):raise Unsupported('normal repaint mismatch: '+key)
        hidden={key:render(transformed[key],key+'-hidden') for key in ('before','candidate')}
        if any(a.shape!=(height,width,4) for a in hidden.values()):raise Unsupported('hidden canvas mismatch')
        validate_all() # Fields only use the final validated capture-time arrays.
        fields={key:np.empty((height,width,3),np.int32) for key in normal}
        for y in range(0,height,32):
            for key in fields:fields[key][y:y+32]=contribution(normal[key][y:y+32],hidden[key][y:y+32])
        _publish(out/'fields.npz',lambda stream:np.savez(stream,**fields));host_pins['fields.npz']=sha_file(out/'fields.npz')
        report['cells']=[dict(bounds_xyxy=list(bounds),**counts(fields['before'][y0:y1,x0:x1],fields['candidate'][y0:y1,x0:x1])) for bounds in cells(width,height) for x0,y0,x1,y1 in [bounds]]
        report['counts']={name:sum(cell[name] for cell in report['cells']) for name in ('before_contributing','candidate_contributing','lost','gained','altered','changed')}
        report['audit']={'fields_npz_sha256':host_pins['fields.npz'],'dtype':'int32','shape':[height,width,3],'allow_pickle':False}
        report['status']='field_available'
    except Unsupported as exc:
        report['reason']=str(exc)
    finally:validate_all()
    report['output_pins']=pins
    report['callback_count']=calls;report['elapsed_seconds']=time.monotonic()-start
    report['outputs']={p.name:{'sha256':sha_file(p),'bytes':p.stat().st_size} for p in sorted(out.iterdir()) if p.is_file()}
    if sum(x['bytes'] for x in report['outputs'].values())>limits.max_artifact_bytes:
        report['status']='field_unavailable';report['reason']='artifact bound exceeded';report.pop('cells',None);report['counts']=None;report['audit']=None
    validate_all()
    _publish(out/'report.json',lambda stream:stream.write((json.dumps(report,indent=2)+'\n').encode()))
    return report
