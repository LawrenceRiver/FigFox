"""Publish the last verified SVG/PNG pair, independently of review success."""
import hashlib
import json
import os
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

from PIL import Image

from .document import tag, validate
from ..state import write_json, replace_file


def _read(path):
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(data, dict):
        raise ValueError('checkpoint record must be an object')
    return data


def _checked(pair):
    svg, png = Path(pair['svg']), Path(pair['png'])
    data = svg.read_bytes()
    revision = hashlib.sha256(data).hexdigest()
    if pair.get('revision') and revision != pair['revision']:
        raise ValueError('SVG revision mismatch')
    root = ET.fromstring(data)
    if tag(root) != 'svg':
        raise ValueError('output is not SVG')
    validate(root)
    with Image.open(png) as image:
        if image.format != 'PNG' or min(image.size) <= 0:
            raise ValueError('output is not a valid PNG')
        dimensions = list(image.size)
        image.verify()
    with Image.open(png) as image:
        image.load()
    png_hash = hashlib.sha256(png.read_bytes()).hexdigest()
    if pair.get('png_sha256') and png_hash != pair['png_sha256']:
        raise ValueError('PNG checksum mismatch')
    return {'svg': str(svg.resolve()), 'png': str(png.resolve()),
            'revision': revision, 'png_sha256': png_hash, 'dimensions': dimensions}


def _copy(source, target):
    fd, name = tempfile.mkstemp(dir=target.parent, prefix='.' + target.name)
    try:
        with os.fdopen(fd, 'wb') as handle:
            handle.write(Path(source).read_bytes())
            handle.flush()
            os.fsync(handle.fileno())
        replace_file(name, target)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def publish_latest(out, image_id, *, error=None):
    """Candidates must be committed checkpoints, never raw or partially written SVG."""
    out = Path(out)
    review = out / 'review' / image_id
    candidates = []
    rejected = []
    result = {}
    records = [
        ('followup', review.with_name(review.name + '-followup') / 'execution/state.json'),
        ('review_checkpoint', review / 'phase-2/execution/state.json'),
        ('review', review / 'result.json'),
    ]
    for stage, path in records:
        try:
            record = _read(path)
            if stage == 'review':
                result = record
            pair = record.get('images', {}).get(image_id)
            if pair:
                candidates.append((stage, pair))
        except (ValueError, OSError, TypeError, AttributeError) as exc:
            rejected.append({'source': str(path), 'error': str(exc)})
    for baseline in sorted(out.glob('native-*/stage-0/scene.svg'), reverse=True):
        candidates.append(('baseline_only', {'svg': str(baseline), 'png': str(baseline.with_name('preview.png'))}))
    try:
        previous = _read(out / 'artifacts.json')
    except (ValueError, OSError):
        previous = {}
    if previous.get('artifact_status') == 'available' and previous.get('outputs') and previous.get('output_stage'):
        candidates.append((previous['output_stage'], previous['outputs']))
    summary = {'artifact_status': 'unavailable', 'output_stage': 'none', 'outputs': {},
               'review_status': 'failed' if error else result.get('status', 'pending'),
               'error': error, 'rejected_candidates': rejected, 'visual_passed': False}
    for stage, pair in candidates:
        try:
            checked = _checked(pair)
        except (ValueError, OSError, KeyError, TypeError, ET.ParseError) as exc:
            rejected.append({'output_stage': stage, 'source': pair, 'error': str(exc)})
            continue
        outputs = dict(checked)
        for suffix in ('svg', 'png'):
            target = out / ('final.' + suffix)
            _copy(checked[suffix], target)
            outputs[suffix] = str(target.resolve())
        summary.update(artifact_status='available', output_stage=stage,
                       source=checked, outputs=outputs)
        break
    write_json(out / 'artifacts.json', summary)
    return summary
