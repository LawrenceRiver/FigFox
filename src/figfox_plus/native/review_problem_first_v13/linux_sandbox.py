"""Run isolated generated Python on Linux, or through an installed WSL distro."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET

from ...state import PLUS_ROOT, write_json
from ..document import validate


def run_code(code, input_svg, output_dir, *, timeout=20, max_output_bytes=20_000_000, current_tp=None):
    out = Path(output_dir).resolve()
    out.mkdir(parents=True, exist_ok=False)
    receipt = {'status': 'failed', 'backend': 'wsl-bubblewrap' if os.name == 'nt' else 'linux-bubblewrap',
               'network': False, 'child_processes': False, 'visual_acceptance': 'pending',
               'memory_limit_kind': 'hard RLIMIT_AS:512MiB'}
    try:
        if not isinstance(code, str) or len(code.encode('utf-8')) > 1_000_000:
            raise ValueError('invalid_source_size')
        receipt['code_sha256'] = hashlib.sha256(code.encode('utf-8')).hexdigest()
        snapshot = json.dumps(current_tp or {}, ensure_ascii=False)
        receipt['tp_snapshot_sha256'] = hashlib.sha256(snapshot.encode('utf-8')).hexdigest()
        (out/'program.py').write_text(code, encoding='utf-8')
        runner = PLUS_ROOT/'runtime/sandbox_runner.py'
        if os.name == 'nt':
            wsl = shutil.which('wsl')
            if not wsl:
                raise ValueError('sandbox_unavailable: install WSL, Python 3, bubblewrap and libseccomp2')
            prefix = [wsl]
            if os.environ.get('FIGFOX_WSL_DISTRO'):
                prefix += ['--distribution', os.environ['FIGFOX_WSL_DISTRO']]
            prefix += ['--exec']
            converted = subprocess.run(prefix+['wslpath', '-a', '-u', str(runner)],
                                       capture_output=True, text=True, encoding='utf-8', timeout=15, check=True)
            command = prefix+['python3', '-I', str(converted.stdout).strip()]
        else:
            command = ['python3', '-I', str(runner)]
        payload = {'code': code, 'svg': Path(input_svg).read_text(encoding='utf-8'),
                   'current_tp': current_tp or {}, 'timeout': timeout, 'max_output_bytes': max_output_bytes}
        process = subprocess.run(command, input=json.dumps(payload).encode('utf-8'),
                                 capture_output=True, timeout=timeout+30)
        if process.returncode:
            raise ValueError('sandbox_unavailable: '+process.stderr.decode('utf-8', 'replace')[:2000])
        result = json.loads(process.stdout)
        value = result.pop('svg_text', None)
        receipt.update(result)
        if receipt.get('status') == 'executed':
            if not isinstance(value, str) or len(value.encode('utf-8')) > max_output_bytes:
                raise ValueError('invalid_svg_output')
            validate(ET.fromstring(value))
            dest = out/'generated.svg'
            dest.write_text(value, encoding='utf-8')
            receipt.update(svg=str(dest), sha256=hashlib.sha256(value.encode('utf-8')).hexdigest())
    except subprocess.TimeoutExpired:
        receipt.update(status='failed', error='sandbox_timeout')
    except Exception as exc:
        receipt.update(status='failed', error=str(exc))
    write_json(out/'receipt.json', receipt)
    return receipt
