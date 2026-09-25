import base64
from copy import deepcopy
import hashlib
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

def parse(text):
    match=re.search(r'<svg\b[\s\S]*?</svg>',text)
    if not match:raise ValueError('missing complete SVG')
    root=ET.fromstring(match.group())
    validate(root)
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
    env.setdefault('PLUS_PLAYWRIGHT_MODULE',str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))
    env.setdefault('PLUS_CHROMIUM',str(Path.home()/'Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell'))
    p=subprocess.run([shutil.which('node') or str(Path.home()/'.node/bin/node'),str(PLUS_ROOT/'runtime/native.cjs')],input=json.dumps({'svg':serialize(root),'png':str(png) if png else None}),text=True,capture_output=True,env=env,timeout=60)
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
    d=json.loads(Path(path).read_text())
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
