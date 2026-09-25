"""Single local RMBG2 inference; no model download, HTTP retry, or color erasure."""
import json, sys, time
from pathlib import Path
from PIL import Image
p=json.load(sys.stdin)
sys.path.insert(0,p['runtime_source'])
from drawai.local_runtime import LocalRmbgClient, LocalRuntimePaths
client=LocalRmbgClient(paths=LocalRuntimePaths.from_root(p['runtime_root']),device='cpu')
start=time.monotonic()
result=client.remove_background(Image.open(p['source']),Path(p['target']).name,timeout_s=120)
result.image.save(p['target'])
print(json.dumps({'method':'RMBG2','seconds':time.monotonic()-start,'artifacts':result.artifacts}))
