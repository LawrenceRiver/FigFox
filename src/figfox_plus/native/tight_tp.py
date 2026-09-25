"""Render-aware TP independent of the locked first-stage geometry estimator."""
import json,os,shutil,subprocess
from pathlib import Path
from .document import serialize,validate
from ..state import PLUS_ROOT

def measure_tight(root,ids=None,scale=4,*,alpha_threshold=1,max_pixels=40_000_000,layout=False):
    validate(root)
    if not isinstance(scale,(int,float)) or not 1<=scale<=16:raise ValueError('scale must be 1..16')
    if not isinstance(alpha_threshold,int) or not 1<=alpha_threshold<=255:raise ValueError('alpha threshold must be 1..255')
    if not isinstance(layout,bool):raise ValueError('layout must be boolean')
    env=os.environ.copy()
    env.setdefault('PLUS_PLAYWRIGHT_MODULE',str(Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'))
    env.setdefault('PLUS_CHROMIUM',str(Path.home()/'Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell'))
    p=subprocess.run([shutil.which('node') or str(Path.home()/'.node/bin/node'),str(PLUS_ROOT/'runtime/tight-tp.cjs')],input=json.dumps({'svg':serialize(root),'ids':ids,'scale':scale,'alpha_threshold':alpha_threshold,'max_pixels':max_pixels,'layout':layout}),text=True,capture_output=True,env=env,timeout=900)
    if p.returncode:raise ValueError(p.stderr[:3000])
    return json.loads(p.stdout)

def union_tight(measurement,ids):
    """Explicit selection; empty objects contribute no bounds, unknown/unsupported fail."""
    boxes=[]
    for i in dict.fromkeys(ids):
        o=measurement['objects'].get(i)
        if o is None or o['status']=='unsupported':raise ValueError('TP unavailable: '+i)
        if o['status']=='measured':boxes.append(o['tight_bbox'])
    if not boxes:return None
    return {k:(min if k in ('left','top') else max)(b[k] for b in boxes) for k in ('left','top','right','bottom')}
