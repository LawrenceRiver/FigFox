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


# Deliberately narrow stdlib authoring surface. This is defense in depth alongside
# Seatbelt and runtime file/import auditing, not a general Python security proof.
_STDLIB_IMPORTS={'xml','math','json','re','collections','itertools','functools','statistics','decimal','fractions','copy','string'}

def validate_stdlib_source(code):
    import ast
    tree=ast.parse(code)
    forbidden={'eval','exec','compile','__import__','getattr','setattr','delattr','globals','locals','vars','dir','help','breakpoint','input','open','memoryview'}
    for node in ast.walk(tree):
        if isinstance(node,(ast.Import,ast.ImportFrom)):
            names=[alias.name for alias in node.names] if isinstance(node,ast.Import) else [node.module or '']
            if getattr(node,'level',0) or any(name.split('.')[0] not in _STDLIB_IMPORTS for name in names):
                raise ValueError('disabled import: only approved stdlib XML/math authoring modules')
        if isinstance(node,ast.Name) and (node.id in forbidden or node.id.startswith('_') or node.id=='CURRENT_TP'):
            raise ValueError('disabled Python capability: '+node.id)
        if isinstance(node,ast.Attribute) and (node.attr.startswith('_') or node.attr in ('open','read_text','read_bytes','write_text','write_bytes','load','loads','import_module','from_file')):
            # json.loads and XML fromstring are safe data parsing and remain useful.
            if not (node.attr in ('load','loads') and isinstance(node.value,ast.Name) and node.value.id=='json'):
                raise ValueError('disabled Python attribute: '+node.attr)
    return tree

def run_code(code, input_svg, output_dir, *, timeout=20, max_output_bytes=20_000_000, current_tp=None, capabilities=None):
    from ..capabilities import normalize_capabilities
    assignment=normalize_capabilities(capabilities)
    policy=assignment
    output_dir=Path(output_dir).resolve();output_dir.mkdir(parents=True,exist_ok=False)
    receipt={'status':'failed','code_sha256':hashlib.sha256(code.encode()).hexdigest(),
             'visual_acceptance':'pending','backend':'macos-seatbelt','network':False,
             'child_processes':False,'memory_limit_kind':'host RSS monitor:512MiB, 50ms sampling'}
    from ..capabilities import capability_hash
    receipt['capability_hash']=capability_hash(assignment)
    receipt.update(mounted_method_directories=[],current_tp_exposed=policy['code_methods'],python_flags=['-I'] if policy['code_methods'] else ['-I','-S'])
    if not policy['code_methods']:
        try:validate_stdlib_source(code)
        except (ValueError,SyntaxError) as exc:
            receipt['error']='disabled source: '+str(exc)
            (output_dir/'receipt.json').write_text(json.dumps(receipt,indent=2))
            return receipt
    if sys.platform!='darwin' or not Path('/usr/bin/sandbox-exec').exists():
        receipt['error']='sandbox_unavailable';return receipt
    if not isinstance(code,str) or len(code.encode())>1_000_000:
        receipt['error']='invalid_source_size';return receipt
    (output_dir/'program.py').write_text(code)
    with tempfile.TemporaryDirectory(prefix='figfox-exec-',dir='/private/tmp') as tmp:
        base=Path(tmp).resolve();methods=base/'methods';work=base/'work';work.mkdir()
        source=Path(__file__).resolve().parents[2]
        if policy['code_methods']:
            shutil.copytree(source,methods/'figfox_plus',ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
            receipt['mounted_method_directories']=[str(methods)]
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
import json
CURRENT_TP=json.loads(TP_JSON)
exec(compile(SOURCE, '<generated-program>', 'exec'), globals())
'''
        settings={'METHODS':str(methods),'CPU':max(1,int(timeout)),'MAX_OUTPUT':max_output_bytes,
                  'INPUT':str(source_svg),'OUTPUT':str(generated),'SOURCE':code,'TP_JSON':json.dumps(current_tp or {},ensure_ascii=False)}
        if policy['code_methods']:
            instrument = """import hashlib, os
library_log=open(str(Path(OUTPUT_SVG).parent/'library-invocations.jsonl'),'w')
source_hashes={}
active_calls={}
def library_trace(frame,event,arg):
    filename=frame.f_code.co_filename
    if not filename.startswith(METHODS+os.sep) or frame.f_code.co_name=='<module>': return library_trace
    call_id=str(id(frame))
    method=frame.f_globals.get('__name__','')+'.'+frame.f_code.co_name
    if filename not in source_hashes: source_hashes[filename]=hashlib.sha256(Path(filename).read_bytes()).hexdigest()
    row={'category':'code_intervention','method':method,'source_sha256':source_hashes[filename],'call_id':call_id,'parent_call_id':str(id(frame.f_back))}
    if event=='call':
        row['status']='started';active_calls[call_id]=row.copy()
    elif event=='exception':
        row.update(status='exception_observed',error=type(arg[1]).__name__+': '+str(arg[1]))
        active_calls.setdefault(call_id,row.copy())['exception']=row['error']
    elif event=='return':
        previous=active_calls.pop(call_id,{})
        # Python trace reports a return with None on propagated exceptions.
        row['status']='failed' if arg is None and previous.get('exception') else 'completed'
        if row['status']=='failed':row['error']=previous['exception']
    else:return library_trace
    library_log.write(json.dumps(row)+'\\n');library_log.flush()
    return library_trace
sys.settrace(library_trace)
"""
            wrapper=wrapper.replace("exec(compile(SOURCE, '<generated-program>', 'exec'), globals())", instrument+"exec(compile(SOURCE, '<generated-program>', 'exec'), globals())\n")
            receipt['tp_snapshot_sha256']=hashlib.sha256(settings['TP_JSON'].encode()).hexdigest()
        else:
            settings.pop('METHODS');settings.pop('TP_JSON')
            wrapper=wrapper.replace('sys.path.insert(0, METHODS)\n','').replace('CURRENT_TP=json.loads(TP_JSON)\n','')
            guard = """import os, sysconfig
stdlib=os.path.realpath(sysconfig.get_path('stdlib'))
allowed_input=os.path.realpath(INPUT_SVG)
allowed_output=os.path.realpath(OUTPUT_SVG)
def audit(event,args):
    if event == 'open':
        path=args[0]
        if isinstance(path,int): return
        path=os.path.realpath(os.fspath(path))
        flags=args[2] if len(args)>2 and isinstance(args[2],int) else 0
        writing=bool(flags & (os.O_WRONLY|os.O_RDWR|os.O_CREAT|os.O_TRUNC|os.O_APPEND))
        allowed=path==allowed_output if writing else (path in (allowed_input,allowed_output) or (path.startswith(stdlib+os.sep) and 'site-packages' not in path.split(os.sep) and 'dist-packages' not in path.split(os.sep)))
        if not allowed: raise PermissionError('disabled file access')
    if event in ('ctypes.dlopen','subprocess.Popen','os.system','os.exec','os.posix_spawn') or event.startswith('socket.'):
        raise PermissionError('disabled runtime capability')
    if event=='import' and len(args)>1 and args[1]:
        origin=os.path.realpath(args[1])
        if not origin.startswith(stdlib+os.sep) or 'site-packages' in origin.split(os.sep):
            raise PermissionError('disabled import origin')
sys.addaudithook(audit)
"""
            wrapper=wrapper.replace("exec(compile(SOURCE, '<generated-program>', 'exec'), globals())",guard+"exec(compile(SOURCE, '<generated-program>', 'exec'), {'INPUT_SVG':INPUT_SVG,'OUTPUT_SVG':OUTPUT_SVG})\nprint('FIGFOX_IMPORT_ORIGINS='+json.dumps({n:getattr(m,'__file__',None) for n,m in sys.modules.items() if getattr(m,'__file__',None)},sort_keys=True))")
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
                proc=subprocess.Popen(['/usr/bin/sandbox-exec','-f',str(policy),str(python),*receipt['python_flags'],str(launcher)],
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
            receipt['library_invocations']=[]
            library_log=work/'library-invocations.jsonl'
            if library_log.exists():
                receipt['library_invocations']=[json.loads(line) for line in library_log.read_text().splitlines()]
            receipt['exit_code']=proc.returncode
            if proc.returncode in (-signal.SIGXCPU,-signal.SIGKILL) and 'error' not in receipt:receipt['error']='execution_timeout'
            receipt['log']=log.read_bytes()[:16000].decode('utf-8','replace')
            receipt['import_origins']={}
            for line in receipt['log'].splitlines():
                if line.startswith('FIGFOX_IMPORT_ORIGINS='):receipt['import_origins']=json.loads(line.split('=',1)[1])
            if 'error' not in receipt and proc.returncode:receipt['error']='execution_failed'
            if 'error' not in receipt:
                if not generated.exists() or generated.is_symlink() or not generated.resolve().is_relative_to(work):
                    raise ValueError('missing_or_unsafe_svg_output')
                if generated.stat().st_size>max_output_bytes:raise ValueError('output_too_large')
                value=generated.read_text();validate(ET.fromstring(value))
                from ..capabilities import validate_svg_capabilities
                validate_svg_capabilities(ET.fromstring(value),assignment,terminal=True)
                dest=output_dir/'generated.svg';dest.write_text(value)
                receipt.update(status='executed',svg=str(dest),sha256=hashlib.sha256(value.encode()).hexdigest())
        except Exception as exc:receipt['error']=str(exc)
    (output_dir/'receipt.json').write_text(json.dumps(receipt,ensure_ascii=False,indent=2))
    return receipt
