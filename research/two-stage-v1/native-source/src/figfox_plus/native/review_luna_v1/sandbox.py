"""Fail-closed macOS process sandbox for generated SVG construction code.

Generated code cannot run children, use network, read home or mutate its methods.
Trusted host render/TP/formula operations happen separately after SVG validation.
"""
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
from ..document import validate


def _quote(path):
    return json.dumps(str(Path(path).resolve()))


def run_code(code, input_svg, output_dir, *, timeout=20, max_output_bytes=20_000_000):
    output_dir=Path(output_dir).resolve();output_dir.mkdir(parents=True,exist_ok=False)
    receipt={'status':'failed','code_sha256':hashlib.sha256(code.encode()).hexdigest(),
             'visual_acceptance':'pending','backend':'macos-seatbelt','network':False,
             'child_processes':False,'memory_limit_kind':'host RSS monitor:512MiB, 50ms sampling'}
    if sys.platform!='darwin' or not Path('/usr/bin/sandbox-exec').exists():
        receipt['error']='sandbox_unavailable';return receipt
    if not isinstance(code,str) or len(code.encode())>1_000_000:
        receipt['error']='invalid_source_size';return receipt
    (output_dir/'program.py').write_text(code)
    with tempfile.TemporaryDirectory(prefix='figfox-exec-',dir='/private/tmp') as tmp:
        base=Path(tmp).resolve();methods=base/'methods';work=base/'work';work.mkdir()
        source=Path(__file__).resolve().parents[2]
        shutil.copytree(source,methods/'figfox_plus',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        source_svg=base/'input.svg';shutil.copyfile(input_svg,source_svg)
        generated=work/'result.svg'
        wrapper='''import sys, resource
from pathlib import Path
sys.path.insert(0, METHODS)
resource.setrlimit(resource.RLIMIT_CPU, (CPU, CPU+1))
resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
resource.setrlimit(resource.RLIMIT_NOFILE, (64,64))
INPUT_SVG=INPUT
OUTPUT_SVG=OUTPUT
exec(compile(SOURCE, '<generated-program>', 'exec'), globals())
'''
        settings={'METHODS':str(methods),'CPU':max(1,int(timeout)),'MAX_OUTPUT':max_output_bytes,
                  'INPUT':str(source_svg),'OUTPUT':str(generated),'SOURCE':code}
        launcher=base/'launch.py'
        launcher.write_text('\n'.join(f'{k}={v!r}' for k,v in settings.items())+'\n'+wrapper)
        # Root and ancestor directory reads are required by dyld; no home data is allowed.
        reads=['/','/opt','/private','/private/tmp','/dev/null','/dev/urandom']
        trees=['/System','/usr','/bin','/Library/Apple','/Library/Frameworks','/opt/homebrew/Cellar/python@3.14','/opt/homebrew/opt/python@3.14','/private/preboot',str(base)]
        profile='(version 1)\n(deny default)\n(allow process-exec)\n(allow sysctl-read)\n(allow file-read-metadata)\n'
        profile+='(allow file-read* '+' '.join('(literal '+_quote(p)+')' for p in reads)+' '+' '.join('(subpath '+_quote(p)+')' for p in trees)+')\n'
        profile+='(allow file-write* (subpath '+_quote(work)+'))\n'
        policy=base/'profile.sb';policy.write_text(profile)
        (output_dir/'sandbox-policy.txt').write_text(profile.replace(str(base),'<isolated-job>'))
        # Use the system-installed interpreter; -I rejects user site and Python env injection.
        python=Path(sys.base_prefix)/'bin/python3'
        if not python.exists():python=Path('/opt/homebrew/bin/python3')
        env={'PATH':'/usr/bin:/bin:/opt/homebrew/bin','HOME':str(work),'TMPDIR':str(work)}
        log=work/'process.log'
        try:
            with log.open('wb') as stream:
                proc=subprocess.Popen(['/usr/bin/sandbox-exec','-f',str(policy),str(python),'-I',str(launcher)],
                                      stdout=stream,stderr=stream,env=env,cwd=work,start_new_session=True)
                start=time.monotonic()
                while proc.poll() is None:
                    if time.monotonic()-start>=timeout:
                        receipt['error']='execution_timeout';break
                    memory=subprocess.run(['/bin/ps','-o','rss=','-p',str(proc.pid)],capture_output=True,text=True)
                    if memory.stdout.strip().isdigit() and int(memory.stdout.strip())>524288:
                        receipt['error']='memory_limit';break
                    time.sleep(0.05)
                if proc.poll() is None:
                    os.killpg(proc.pid,signal.SIGKILL);proc.wait()
            receipt['exit_code']=proc.returncode
            if proc.returncode in (-signal.SIGXCPU,-signal.SIGKILL) and 'error' not in receipt:receipt['error']='execution_timeout'
            receipt['log']=log.read_bytes()[:16000].decode('utf-8','replace')
            if 'error' not in receipt and proc.returncode:receipt['error']='execution_failed'
            if 'error' not in receipt:
                if not generated.exists() or generated.is_symlink() or not generated.resolve().is_relative_to(work):
                    raise ValueError('missing_or_unsafe_svg_output')
                if generated.stat().st_size>max_output_bytes:raise ValueError('output_too_large')
                value=generated.read_text();validate(ET.fromstring(value))
                dest=output_dir/'generated.svg';dest.write_text(value)
                receipt.update(status='executed',svg=str(dest),sha256=hashlib.sha256(value.encode()).hexdigest())
        except Exception as exc:receipt['error']=str(exc)
    (output_dir/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    return receipt
