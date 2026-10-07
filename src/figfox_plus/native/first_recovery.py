"""Recover locally by default; extra model recovery requires explicit opt-in."""
import base64
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

from ..state import PLUS_ROOT, write_json
from .document import parse
from .review_problem_first_v13.transport import send as repair_send


def recover_baseline(original, run, error, *, first, stage, sender=repair_send, allow_model_recovery=False):
    run = Path(run)
    source = run / 'gpt55' / 'response.txt'
    if not source.is_file() or not source.read_text(encoding='utf-8').strip():
        raise error
    raw = source.read_text(encoding='utf-8')
    sam = json.loads((run / 'sam.json').read_text(encoding='utf-8'))
    attempt = run / 'first-recovery-attempt.json'
    if attempt.exists():
        raise ValueError('first-draft recovery was already attempted; no repeated paid recovery') from error

    # A missing completion event can still leave a complete SVG. Validate it
    # locally first, retaining incomplete API status and unknown billing evidence.
    try:
        parse(raw)
    except (ValueError, ET.ParseError):
        pass
    else:
        if (run / 'gpt55' / 'error.json').is_file():
            root = first(original, run, send=lambda *args: raw, sam=sam)
            stage(root, original, run / 'stage-0')
            write_json(run / 'first-recovery.json', {'status': 'partial_reply_rendered',
                'additional_model_requests': 0, 'original_api_completed': False,
                'raw_response_unchanged': True, 'visual_passed': False})
            return root

    if not allow_model_recovery:
        write_json(run / 'first-recovery.json', {'status': 'manual_recovery_required',
            'error': {'type': type(error).__name__, 'message': str(error)[:4000]},
            'additional_model_requests': 0, 'raw_response_unchanged': True, 'visual_passed': False})
        raise error

    req = json.loads((run / 'gpt55' / 'request.json').read_text(encoding='utf-8'))
    content = [{'type': 'text', 'text': (PLUS_ROOT / 'prompts/first_recovery.md').read_text(encoding='utf-8') +
        '\n原始任务：\n' + req['prompt'] + '\n宿主错误：\n' + type(error).__name__ + ': ' + str(error)[:4000] +
        '\n失败原文（未经修改）：\n' + raw}]
    for item in req['images']:
        data = Path(item['path']).read_bytes()
        if hashlib.sha256(data).hexdigest() != item['sha256']:
            raise ValueError('first recovery image evidence changed')
        content.append({'type': 'image_url', 'image_url': {'url': 'data:image/png;base64,' +
            base64.b64encode(data).decode('ascii'), 'detail': 'original'}})
    with attempt.open('x', encoding='utf-8') as handle:
        json.dump({'limit': 1, 'original_reply_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
            'error': {'type': type(error).__name__, 'message': str(error)[:4000]},
            'automatic_network_retry': False, 'visual_passed': False}, handle, ensure_ascii=False)
    try:
        message = sender([{'role': 'user', 'content': content}], [], run / 'first-recovery', request_limit=1)
        response = message.get('content') or ''
        (run / 'first-recovery-response.txt').write_text(response, encoding='utf-8')
        root = first(original, run, send=lambda *args: response, sam=sam)
        stage(root, original, run / 'stage-0')
        write_json(run / 'first-recovery.json', {'status': 'recovered', 'additional_model_request_limit': 1,
            'raw_response_unchanged': True, 'visual_passed': False})
        return root
    except Exception as exc:
        write_json(run / 'first-recovery.json', {'status': 'failed', 'error': str(exc),
            'additional_model_request_limit': 1, 'raw_response_unchanged': True, 'visual_passed': False})
        raise
