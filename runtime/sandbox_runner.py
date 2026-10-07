"""Trusted Linux supervisor. Only the child enters the generated-code sandbox."""
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tempfile


WRAPPER = '''
import ctypes, resource, sys
sys.path.insert(0, '/methods')
resource.setrlimit(resource.RLIMIT_CPU, (CPU, CPU+1))
resource.setrlimit(resource.RLIMIT_AS, (512*1024*1024, 512*1024*1024))
resource.setrlimit(resource.RLIMIT_FSIZE, (MAX_OUTPUT, MAX_OUTPUT))
resource.setrlimit(resource.RLIMIT_NOFILE, (64,64))
# Kernel-enforced restrictions survive exec and cannot be removed by Python code.
lib = ctypes.CDLL('libseccomp.so.2', use_errno=True)
lib.seccomp_init.argtypes = [ctypes.c_uint32]
lib.seccomp_init.restype = ctypes.c_void_p
lib.seccomp_syscall_resolve_name.argtypes = [ctypes.c_char_p]
lib.seccomp_syscall_resolve_name.restype = ctypes.c_int
lib.seccomp_rule_add.argtypes = [ctypes.c_void_p, ctypes.c_uint32, ctypes.c_int, ctypes.c_uint]
lib.seccomp_rule_add.restype = ctypes.c_int
lib.seccomp_load.argtypes = [ctypes.c_void_p]
lib.seccomp_load.restype = ctypes.c_int
lib.seccomp_release.argtypes = [ctypes.c_void_p]
ctx = lib.seccomp_init(0x7fff0000)
if not ctx: raise RuntimeError('seccomp_init failed')
try:
    for name in ('clone','clone3','fork','vfork','execve','execveat','socket','socketpair',
                 'ptrace','mount','umount2','unshare','setns','bpf','io_uring_setup'):
        number = lib.seccomp_syscall_resolve_name(name.encode())
        if number >= 0 and lib.seccomp_rule_add(ctx, 0x00050001, number, 0) != 0:
            raise RuntimeError('seccomp rule failed: '+name)
    if lib.seccomp_load(ctx) != 0: raise RuntimeError('seccomp_load failed')
finally:
    lib.seccomp_release(ctx)
exec(compile(SOURCE, '<generated-program>', 'exec'), {
    'INPUT_SVG': '/job/input.svg', 'OUTPUT_SVG': '/work/result.svg', 'CURRENT_TP': TP,
    '__name__': '__main__'})
'''


def run(payload):
    if not shutil.which('bwrap'):
        return {'status': 'failed', 'error': 'sandbox_unavailable: install bubblewrap and libseccomp2 inside Linux/WSL'}
    limit = payload['max_output_bytes']
    timeout = payload['timeout']
    with tempfile.TemporaryDirectory(prefix='figfox-isolated-') as tmp:
        base = Path(tmp)
        job, work = base/'job', base/'work'
        job.mkdir(); work.mkdir()
        (job/'input.svg').write_text(payload['svg'], encoding='utf-8')
        settings = {'SOURCE': payload['code'], 'TP': payload['current_tp'],
                    'CPU': max(1, int(timeout)), 'MAX_OUTPUT': limit}
        (job/'launch.py').write_text('\n'.join(f'{k}={v!r}' for k,v in settings.items())+WRAPPER, encoding='utf-8')
        command = ['bwrap', '--unshare-all', '--die-with-parent', '--new-session',
                   '--cap-drop', 'ALL', '--clearenv', '--setenv', 'PATH', '/usr/bin',
                   '--setenv', 'LANG', 'C.UTF-8', '--setenv', 'HOME', '/work',
                   '--ro-bind', '/usr', '/usr']
        for folder in ('/lib', '/lib64', '/bin'):
            if Path(folder).exists():
                command += ['--ro-bind', folder, folder]
        command += ['--proc', '/proc', '--dev', '/dev', '--tmpfs', '/tmp',
                    '--ro-bind', str(job), '/job',
                    '--ro-bind', str(Path(__file__).resolve().parents[1]/'src'), '/methods',
                    '--bind', str(work), '/work', '--chdir', '/work',
                    'python3', '-I', '-B', '-X', 'utf8', '/job/launch.py']
        log = base/'process.log'
        receipt = {'status': 'failed'}
        with log.open('wb') as stream:
            child = subprocess.Popen(command, stdout=stream, stderr=stream, start_new_session=True)
            try:
                child.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                receipt['error'] = 'execution_timeout'
            finally:
                if child.poll() is None:
                    os.killpg(child.pid, signal.SIGKILL)
                    child.wait()
        receipt['exit_code'] = child.returncode
        with log.open('rb') as handle:
            receipt['log'] = handle.read(16000).decode('utf-8', 'replace')
        if child.returncode or 'error' in receipt:
            receipt.setdefault('error', 'execution_failed')
            return receipt
        generated = work/'result.svg'
        if not generated.is_file() or generated.is_symlink() or not generated.resolve().is_relative_to(work):
            receipt['error'] = 'missing_or_unsafe_svg_output'
        elif generated.stat().st_size > limit:
            receipt['error'] = 'output_too_large'
        else:
            receipt.update(status='executed', svg_text=generated.read_text(encoding='utf-8'))
        return receipt


if __name__ == '__main__':
    try:
        result = run(json.loads(sys.stdin.buffer.read()))
    except Exception as error:
        result = {'status': 'failed', 'error': str(error)}
    sys.stdout.buffer.write(json.dumps(result, ensure_ascii=True).encode('utf-8'))
