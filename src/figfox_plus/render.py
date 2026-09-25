"""Browser layout measurements, explicitly conservative for transformed curves/strokes."""
import json
import os
from pathlib import Path
import shutil
import subprocess
from .state import PLUS_ROOT


def measure(svg,index,png=None):
    env=os.environ.copy()
    deps=Path.home()/'.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/playwright'
    chrome=Path.home()/'Library/Caches/ms-playwright/chromium_headless_shell-1234/chrome-headless-shell-mac-arm64/chrome-headless-shell'
    env.setdefault('PLUS_PLAYWRIGHT_MODULE',str(deps))
    env.setdefault('PLUS_CHROMIUM',str(chrome))
    result=subprocess.run([shutil.which('node') or 'node',str(PLUS_ROOT/'runtime/measure.cjs')],
        input=json.dumps({'svg':svg,'index':index,'png':str(png) if png else None}),
        text=True,capture_output=True,env=env,timeout=45)
    if result.returncode: raise ValueError('measurement: '+result.stderr[:1000])
    return json.loads(result.stdout)
