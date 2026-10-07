import base64
from copy import deepcopy
import hashlib
from html.entities import html5
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import xml.etree.ElementTree as ET
from ..state import PLUS_ROOT
SVG='http://www.w3.org/2000/svg'
ET.register_namespace('',SVG)
HREF='{http://www.w3.org/1999/xlink}href'
DRAWABLE={'g','rect','circle','ellipse','polygon','polyline','path','line','text','image','use','svg'}

def extract_svg(text):
    # Skip comment/CDATA contents and match nested SVG viewports correctly.
    tokens=re.finditer(r"""<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>|</?svg\b(?:[^>"']|"[^"]*"|'[^']*')*>""",text)
    start=None;depth=0
    for match in tokens:
        token=match.group()
        if token.startswith(('<!--','<![CDATA[','<?')):continue
        closing=token.startswith('</')
        if start is None:
            if closing:continue
            start=match.start()
        depth+=-1 if closing else (0 if token.rstrip().endswith('/>') else 1)
        if depth==0:return text[start:match.end()]
    raise ValueError('missing complete SVG')


def parse(text, *, repairs=None):
    source=extract_svg(text)
    normalization=[]
    # These characters cannot appear literally in XML 1.0. Do not recover a
    # malformed tree, invent missing closing tags, or remove numeric entities.
    source,count=re.subn('[\x00-\x08\x0b\x0c\x0e-\x1f\ufffe\uffff]','',source)
    if count:normalization.append({'kind':'remove_invalid_xml_characters','count':count})
    opening=re.match(r"""<svg\b(?:[^>"']|"[^"]*"|'[^']*')*>""",source).group()
    if re.search(r'\bxlink:',source) and not re.search(r'\bxmlns:xlink\s*=',opening):
        end=len(opening)-(2 if opening.endswith('/>') else 1)
        source=source[:end]+' xmlns:xlink="http://www.w3.org/1999/xlink"'+source[end:]
        normalization.append({'kind':'declare_xlink_namespace','count':1})
    try:
        root=ET.fromstring(source)
    except ET.ParseError:
        # Preserve entities, comments, CDATA and processing instructions. Only
        # escape bare ampersands; malformed structure must still fail parsing.
        parts=re.split(r'(<!--[\s\S]*?-->|<!\[CDATA\[[\s\S]*?\]\]>|<\?[\s\S]*?\?>)',source)
        count=0
        entity_count=0
        def xml_entity(match):
            nonlocal entity_count
            name=match.group(1)
            if name in ('amp','lt','gt','quot','apos') or name+';' not in html5:
                return match.group()
            entity_count+=1
            return ''.join(f'&#{ord(char)};' for char in html5[name+';'])
        for index in range(0,len(parts),2):
            parts[index]=re.sub(r'&([A-Za-z][A-Za-z0-9]+);',xml_entity,parts[index])
            parts[index],changed=re.subn(r'&(?![A-Za-z_:][\w.:-]*;|#\d+;|#x[0-9a-fA-F]+;)', '&amp;',parts[index])
            count+=changed
        if not count and not entity_count:raise
        root=ET.fromstring(''.join(parts))
        if repairs is not None:
            if count:repairs.append({'kind':'escape_bare_ampersand','count':count})
            if entity_count:repairs.append({'kind':'html_named_entity_to_numeric','count':entity_count})
    validate(root)
    if repairs is not None:repairs.extend(normalization)
    # Stable generic identity only: no change to geometry/position/style.
    existing={n.get('id') for n in root.iter() if n.get('id')};counter=0
    for n in root.iter():
        if tag(n) in DRAWABLE and n is not root and not n.get('id'):
            while f'plus_node_{counter}' in existing:counter+=1
            n.set('id',f'plus_node_{counter}');existing.add(n.get('id'));counter+=1
    return root

def tag(n):return n.tag.rsplit('}',1)[-1]
def serialize(root):return ET.tostring(root,encoding='unicode')
def validate(root):
    ids=set()
    for n in root.iter():
        if tag(n) in ('script','foreignObject','animate','animateTransform','set'):raise ValueError('active SVG content unsupported')
        if n.get('id'):
            if n.get('id') in ids:raise ValueError('duplicate SVG id')
            ids.add(n.get('id'))
        for k,v in n.attrib.items():
            if k.lower().startswith('on'):raise ValueError('SVG event handler unsupported')
            if k in ('href',HREF) and not (v.startswith('#') or v.startswith('data:image/png;base64,') or re.fullmatch(r'[\w-]+',v)):
                raise ValueError('external or unsupported SVG resource')
            if re.search(r'url\(\s*[\"\']?(?!#)[^)]',v,re.I) and 'url(' in v:raise ValueError('external CSS resource')
        if tag(n)=='style' and re.search(r'@import|url\(\s*[\"\']?(?!#)[^)]',n.text or '',re.I):raise ValueError('external stylesheet resource')

def measure(root,png=None):
    validate(root);env=os.environ.copy()
    p=subprocess.run([shutil.which('node') or 'node',str(PLUS_ROOT/'runtime/native.cjs')],input=json.dumps({'svg':serialize(root),'png':str(png) if png else None}),text=True,capture_output=True,env=env,timeout=60, encoding='utf-8')
    if p.returncode:raise ValueError(p.stderr[:2000])
    return json.loads(p.stdout)

def public_svg(root):
    copy=deepcopy(root)
    for n in copy.iter():
        for k in ('href',HREF):
            if n.get(k,'').startswith('data:'):n.set(k,'embedded_'+n.get('id','image'))
    return serialize(copy)

def frame_ids(root):
    # Legacy instruction guarantees frame IDs, but does not mark roles. Keep
    # explicit IDs on closed shapes as candidates, never infer semantic answers.
    return [n.get('id') for n in root.iter() if n.get('data-plus-kind')=='frame' or
            (tag(n) in ('rect','polygon','circle','ellipse') and n.get('id') and not n.get('id').startswith('plus_node_'))]

def extract_response(path):
    d=json.loads(Path(path).read_text(encoding='utf-8'))
    if d.get('status')!='completed' or not d.get('model','').startswith('gpt-5.5'):raise ValueError('not completed GPT-5.5 response')
    return ''.join(c.get('text','') for o in d.get('output',[]) if o.get('type')=='message' for c in o.get('content',[]) if c.get('type')=='output_text')

def bind_assets(root,assets):
    for n in root.iter():
        if tag(n)!='image' or n.get('data-plus-crop'):continue
        key='href' if 'href' in n.attrib else HREF
        ref=n.get(key,'')
        if ref.startswith('data:'):continue
        if ref not in assets:raise ValueError('missing source asset '+ref)
        data=Path(assets[ref]).read_bytes();n.set(key,'data:image/png;base64,'+base64.b64encode(data).decode())
    return root
