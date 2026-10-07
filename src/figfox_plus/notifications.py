"""Per-user Windows notification registration with narrowly scoped link actions."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.parse import urlsplit
from uuid import uuid4
import xml.etree.ElementTree as ET

from .state import PLUS_ROOT, write_json

APP_ID = 'FigFox.Experiments.926'
PROTOCOL = 'figfox-run-926'


def notification_folder():
    # Workspace paths also work when Explorer activates the protocol outside a
    # packaged host whose AppData writes may have been virtualized.
    return PLUS_ROOT / 'runs' / 'notifications'


def _executable():
    pythonw = Path(sys.executable).with_name('pythonw.exe')
    return str(pythonw if pythonw.is_file() else Path(sys.executable))


def toast_xml(title, message, token, *, has_result):
    url = PROTOCOL+'://open/'+token+'?kind=status'
    toast = ET.Element('toast', {'activationType':'protocol', 'launch':url})
    binding = ET.SubElement(ET.SubElement(toast,'visual'),'binding',{'template':'ToastGeneric'})
    ET.SubElement(binding,'text').text = title
    ET.SubElement(binding,'text').text = message
    actions = ET.SubElement(toast,'actions')
    ET.SubElement(actions,'action',{'content':'查看详情','activationType':'protocol','arguments':url})
    if has_result:
        ET.SubElement(actions,'action',{'content':'打开当前结果','activationType':'protocol',
            'arguments':PROTOCOL+'://open/'+token+'?kind=result'})
    return ET.tostring(toast,encoding='unicode')


def notify_windows(title, message, status, *, result=None):
    if os.name != 'nt':
        return {'status':'unsupported_os', 'detail':'status page remains available'}
    if os.environ.get('FIGFOX_NOTIFICATIONS','1')=='0':
        return {'status':'disabled_by_configuration'}
    folder = notification_folder(); folder.mkdir(parents=True,exist_ok=True)
    token = uuid4().hex
    paths = {'status':str(Path(status).resolve())}
    if result:
        paths['result'] = str(Path(result).resolve())
    write_json(folder/(token+'.json'), {'paths':paths,'expires_at':time.time()+7*86400})
    payload = {'app_id':APP_ID,'workspace':str(PLUS_ROOT),'executable':_executable(),
               'shortcut_arguments':subprocess.list2cmdline([str(PLUS_ROOT/'scripts/open-run.py')]),
               'protocol':PROTOCOL,'protocol_command':subprocess.list2cmdline([_executable(),str(PLUS_ROOT/'scripts/open-run.py')])+' "%1"',
               'xml':toast_xml(title,message,token,has_result=bool(result))}
    path = folder/(token+'-payload.json'); write_json(path,payload)
    receipt = folder/(token+'-receipt.json')
    powershell = Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe'
    process = subprocess.run([str(powershell),'-NoProfile','-NonInteractive','-ExecutionPolicy','Bypass',
        '-File',str(PLUS_ROOT/'scripts/submit-notification.ps1'),'-PayloadFile',str(path),'-ReceiptFile',str(receipt)],
        capture_output=True,timeout=30,creationflags=subprocess.CREATE_NO_WINDOW)
    if process.returncode:
        # Do not copy arbitrary stderr into a toast or expose environment data.
        return {'status':'failed','exit_code':process.returncode,
                'diagnostic':process.stderr.decode('utf-8','replace')[:2000]}
    deadline = time.monotonic()+30
    while time.monotonic()<deadline:
        try:
            return json.loads(receipt.read_text(encoding='utf-8-sig'))
        except (OSError, ValueError):
            time.sleep(0.25)
    return {'status':'failed','diagnostic':'Windows notification helper did not write a receipt within 30s'}


def resolve_action(url, *, folder=None, now=None):
    parsed = urlsplit(url)
    if parsed.scheme != PROTOCOL or parsed.netloc != 'open' or parsed.fragment:
        raise ValueError('invalid notification action')
    token = parsed.path.removeprefix('/')
    if not re.fullmatch('[a-f0-9]{32}',token) or parsed.query not in ('kind=status','kind=result'):
        raise ValueError('invalid notification action')
    record = json.loads(((folder or notification_folder())/(token+'.json')).read_text(encoding='utf-8'))
    if record['expires_at'] < (time.time() if now is None else now):
        raise ValueError('expired notification action')
    path = Path(record['paths'][parsed.query[5:]]).resolve()
    if not path.is_file() or path.suffix.lower() not in ('.html','.png'):
        raise ValueError('notification target is not an available status page or PNG')
    return path
