"""Browser layout measurements, explicitly conservative for transformed curves/strokes."""
import json
import subprocess
from .state import PLUS_ROOT
from .runtime import browser_environment, node_command


def measure(svg,index,png=None):
    env=browser_environment()
    result=subprocess.run([node_command(),str(PLUS_ROOT/'runtime/measure.cjs')],
        input=json.dumps({'svg':svg,'index':index,'png':str(png) if png else None}),
        text=True,capture_output=True,env=env,timeout=45)
    if result.returncode: raise ValueError('measurement: '+result.stderr[:1000])
    return json.loads(result.stdout)
