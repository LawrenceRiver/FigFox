"""Local text and TeX construction; no remote resources or generated code."""
import json
import subprocess
import shutil
from math import isfinite
import xml.etree.ElementTree as ET
from ..state import PLUS_ROOT

SVG='http://www.w3.org/2000/svg'


def content_element(kind,data):
    size=float(data.get('font_size',20))
    if not isfinite(size) or size<=0: raise ValueError('font size must be finite and positive')
    if kind=='text':
        raw_style=data.get('style',{})
        if isinstance(raw_style,str):
            try:style=dict(part.strip().split(':',1) for part in raw_style.split(';') if part.strip())
            except ValueError:raise ValueError('invalid CSS declaration')
        else:style=dict(raw_style)
        allowed={'font-weight','font-style','fill','letter-spacing','text-decoration'}
        if set(style)-allowed: raise ValueError('unsupported text style')
        if 'fill' in data: style['fill']=data['fill']
        el=ET.Element(f'{{{SVG}}}text',{'x':str(data.get('x',0)), 'y':str(data.get('y',0)),
            'font-size':str(size),'font-family':data.get('font_family','Arial, sans-serif'),
            'text-anchor':data.get('anchor','start'),
            'style':';'.join(f'{k}:{v}' for k,v in style.items())})
        lines=data['text'].split('\n')
        if len(lines)==1:el.text=lines[0]
        else:
            leading=float(data.get('line_height',1.2))*size
            if leading<=0:raise ValueError('line height must be positive')
            for n,line in enumerate(lines):
                span=ET.SubElement(el,f'{{{SVG}}}tspan',{'x':str(data.get('x',0)),'y':str(float(data.get('y',0))+n*leading)})
                span.text=line
        return el
    if not isinstance(data.get('tex'),str) or not data['tex'].strip():
        raise ValueError('formula requires nonempty LaTeX')
    result=subprocess.run([shutil.which('node') or 'node',str(PLUS_ROOT/'runtime/formula.cjs')],
        input=json.dumps({'tex':data['tex']}),text=True,capture_output=True,timeout=30, encoding='utf-8')
    if result.returncode: raise ValueError('formula: '+result.stderr[:500])
    wrapper=ET.fromstring(result.stdout)
    el=next((e for e in wrapper.iter() if e.tag.split('}')[-1]=='svg'),None)
    if el is None or any(e.get('data-mml-node')=='merror' for e in wrapper.iter()):
        raise ValueError('formula rendering failed')
    box=list(map(float,el.get('viewBox').split()))
    if len(box)!=4 or not all(isfinite(v) for v in box) or min(box[2:])<=0:
        raise ValueError('formula has invalid glyph bounds')
    el.set('width',str(box[2]*size/1000));el.set('height',str(box[3]*size/1000))
    el.set('x',str(data.get('x',0)));el.set('y',str(data.get('y',0)))
    el.attrib.pop('style',None)
    # Preserve mathematical source and treat all glyphs as a single TP object.
    color=data.get('fill','#111111')
    el.set('fill',color);el.set('color',color)
    metadata=ET.SubElement(el,f'{{{SVG}}}metadata')
    metadata.text=json.dumps({'renderer':'MathJax','tex':data['tex'],'viewBox':box,'display':True},ensure_ascii=False)
    return el
