"""Measured local tracing backends; vector status checked independently of backend."""
import json
import subprocess
import shutil
import time
import sys
from pathlib import Path
import xml.etree.ElementTree as ET
from PIL import Image
from .state import PLUS_ROOT,write_json


def vectorize_asset(asset,backend,out_dir):
    out=Path(out_dir);out.mkdir(parents=True,exist_ok=True);path=out/(asset['id']+'-'+backend+'.svg')
    start=time.perf_counter()
    if backend=='vtracer':
        # Fine-detail preset approved on the Privacy crop (2026-09-23).
        params=dict(colormode='color',hierarchical='stacked',mode='spline',
                    filter_speckle=0,color_precision=8,layer_difference=4,
                    corner_threshold=60,length_threshold=3.5,max_iterations=10,
                    splice_threshold=30,path_precision=4)
        # The pinned vtracer venv uses a platform-dependent layout; fall back to the
        # running interpreter so tracing is not lost on machines without that venv.
        interpreter = next((str(candidate) for candidate in (
            PLUS_ROOT/'.venv-vector/bin/python', PLUS_ROOT/'.venv-vector/Scripts/python.exe')
            if candidate.exists()), sys.executable)
        result=subprocess.run([interpreter,str(PLUS_ROOT/'runtime/vtracer_runner.py')],input=json.dumps(dict(source=asset['path'],target=str(path),parameters=params)),text=True,capture_output=True,timeout=60, encoding='utf-8')
        if result.returncode:raise ValueError('vtracer failed exit '+str(result.returncode)+': '+result.stderr[:500])
        version='0.6.12'
    elif backend=='imagetracerjs':
        params=dict(numberofcolors=32,ltres=1,qtres=1,pathomit=2)
        with Image.open(asset['path']) as im:
            im=im.convert('RGBA');payload={'image':{'width':im.width,'height':im.height,'data':list(im.tobytes())},'options':params}
        result=subprocess.run([shutil.which('node') or 'node',str(PLUS_ROOT/'runtime/vectorize.cjs')],input=json.dumps(payload),text=True,capture_output=True,timeout=60, encoding='utf-8')
        if result.returncode:raise ValueError('imagetracer failed: '+result.stderr[:500])
        path.write_text(result.stdout, encoding='utf-8');version='1.2.6'
    elif backend=='pixelruns':
        # Small local assets only: preserve tiny noise/dash/glyph details as colored
        # run paths. This is not smooth Bezier fitting or semantic editability.
        from collections import defaultdict
        params={'mode':'horizontal-color-runs','max_source_pixels':262144}
        with Image.open(asset['path']) as im:
            im=im.convert('RGBA');w,h=im.size
            if w*h>params['max_source_pixels']:raise ValueError('pixelruns is limited to small local crops')
            pixels=im.load();runs=defaultdict(list)
            for y in range(h):
                x=0
                while x<w:
                    color=pixels[x,y];end=x+1
                    while end<w and pixels[end,y]==color:end+=1
                    if color[3]:runs[color].append(f'M{x} {y}h{end-x}v1h{x-end}z')
                    x=end
        root=ET.Element('svg',{'xmlns':'http://www.w3.org/2000/svg','viewBox':f'0 0 {w} {h}','width':str(w),'height':str(h),'shape-rendering':'crispEdges'})
        for (r,g,b,a),segments in runs.items():
            attrs={'fill':f'#{r:02x}{g:02x}{b:02x}','d':' '.join(segments)}
            if a!=255:attrs['fill-opacity']=str(a/255)
            ET.SubElement(root,'path',attrs)
        ET.ElementTree(root).write(path,encoding='unicode');version='plus-1'
    else:raise ValueError('unknown tracing backend')
    elapsed=time.perf_counter()-start;root=ET.parse(path).getroot()
    if any(e.tag.split('}')[-1]=='image' or any('href' in k and not v.startswith('#') for k,v in e.attrib.items()) for e in root.iter()):
        raise ValueError('output is not self-contained vector')
    record={**asset,'id':asset['id']+'_'+backend,'representation':'vector','path':str(path.resolve()),
            'backend':backend,'version':version,'parameters':params,'elapsed_seconds':elapsed,
            'bytes':path.stat().st_size,'path_count':sum(e.tag.split('}')[-1]=='path' for e in root.iter()),
            'source_asset_path':asset['path']}
    write_json(path.with_suffix('.json'),record);return record
