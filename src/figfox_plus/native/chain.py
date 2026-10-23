"""One figure, one command: GPT-5.5, crops, two DeepSeek calls, then a third only if priority issues did not land."""
import hashlib
import json
import math
import time
from pathlib import Path
import shutil

from PIL import Image

from figfox_plus.native.pipeline import first, stage
from figfox_plus.native.review_problem_first_v13.inputs import validate_bundle
from figfox_plus.native.review_problem_first_v13.orchestrator import prepare, run as review_run
from figfox_plus.native.review_problem_first_v13.upstream_arrows import freeze_arrow_evidence
from figfox_plus.providers import call_gpt55
from figfox_plus.state import new_run, write_json
from .capabilities import normalize_capabilities, capability_hash, trace_context, invoke


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def asset(path, asset_id, *, png=False):
    path = Path(path)
    item = {'path': str(path.resolve()), 'sha256': sha(path), 'asset_id': asset_id}
    if png:
        with Image.open(path) as image:
            item['dimensions'] = list(image.size)
    return item


def pixel_rect(box, canvas, image_size):
    x, y, w, h = box
    x -= canvas['x']
    y -= canvas['y']
    sx, sy = image_size[0] / canvas['width'], image_size[1] / canvas['height']
    return [math.floor(x * sx), math.floor(y * sy), math.ceil((x + w) * sx), math.ceil((y + h) * sy)]


def bundle_from_stage(run, original, image_id):
    stage_dir = run / 'stage-0'
    svg = stage_dir / 'scene.svg'
    preview = stage_dir / 'preview.png'
    revision = sha(svg)
    original_asset = asset(original, image_id + '/original_png', png=True)
    current_png = asset(preview, image_id + '/current_png', png=True)
    current_png['current_revision'] = revision
    tp = asset(stage_dir / 'bounds.json', image_id + '/current_tp')
    tp.update(current_revision=revision, domain='current')
    pack = json.loads((stage_dir / 'pack' / 'pack.json').read_text())
    pairs = []
    with Image.open(original) as src, Image.open(preview) as now:
        sizes = {'original': src.size, 'current': now.size}
    for index, frame in enumerate(pack['frames']):
        stem = f'frame-{index:03d}'
        mapping = {}
        assets = {}
        for side in ('original', 'current'):
            mapping[side] = pixel_rect(frame['canvas_crop'], pack['canvas'], sizes[side])
            assets[side] = asset(stage_dir / 'pack' / f'{stem}-{side}.png', f'{image_id}/crop/{stem}/{side}', png=True)
        pairs.append({
            'pair_id': stem,
            'producer_version': 'half-crop-stage-0',
            'original_revision': original_asset['sha256'],
            'current_revision': revision,
            'comparison_scale': frame['display_scale'],
            'display_mapping': mapping,
            'original_asset': assets['original'],
            'current_asset': assets['current'],
        })
    return {'images': {image_id: {
        'original_png': original_asset,
        'current_svg': asset(svg, image_id + '/current_svg'),
        'current_png': current_png,
        'current_tp': tp,
        'current_revision': revision,
        'crop_pairs': pairs,
    }}}


def run_chain(image, out, *, image_id, rerun_authorization, capabilities=None,
              first_sender=None, review_sender=None,
              sam_service_url='http://127.0.0.1:18080'):
    image = Path(image).resolve()
    out = Path(out).resolve()
    if not image.is_file():
        raise SystemExit(f'missing image: {image}')
    if not image_id.replace('-', '').replace('_', '').isalnum():
        raise SystemExit('invalid image id')
    if out.exists():
        raise SystemExit(f'already exists: {out}')
    policy = normalize_capabilities(capabilities)
    out.mkdir()
    write_json(out / 'capabilities.json', {'policy': policy, 'sha256': capability_hash(policy)})
    log = out / 'chain-timing.jsonl'

    def mark(event, **extra):
        row = {'event': event, 'at': time.time(), **extra}
        with log.open('a') as handle:
            handle.write(json.dumps(row) + '\n')
        print(json.dumps(row), flush=True)

    mark('gpt55_start')
    run = new_run(out, 'native')
    write_json(run / 'run.json', {
        'original': str(image),
        'execution_source': 'native-gpt55',
        'status': 'building',
        'visual_passed': False,
        'capabilities': policy,
        'capability_sha256': capability_hash(policy),
    })

    def send(prompt, images, run_dir, purpose):
        return call_gpt55(prompt, images, run_dir, purpose,
                          rerun_authorization=rerun_authorization,
                          ledger=out/'model-ledger.jsonl')

    root = first(image, run, send=first_sender or send, capabilities=policy,
                 sam_service_url=sam_service_url)
    with trace_context(run, policy, 'stage'):
        invoke('common_guard', stage, root, image, run / 'stage-0', trace_method='stage')
    state = json.loads((run / 'run.json').read_text())
    state.update(latest_stage=str(run / 'stage-0'), status='baseline_rendered', baseline_svg_sha256=sha(run / 'stage-0' / 'scene.svg'))
    write_json(run / 'run.json', state)
    mark('gpt55_done', run=str(run))
    with trace_context(run, policy, 'bundle'):
        bundle = invoke('common_runtime', bundle_from_stage, run, image, image_id,
                        trace_method='bundle_from_stage')
    validate_bundle(bundle)
    (out / 'bundle.json').write_text(json.dumps(bundle))
    arrows = {}
    if policy['sam']:
        arrows = {image_id: {'sam_manifest': str(run / 'sam.json'), 'head_evidence': str(run / 'arrow-head-evidence.json')}}
        try:
            freeze_arrow_evidence(arrows[image_id], bundle['images'][image_id]['original_png'], out / 'arrow-check')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            mark('arrow_handoff_failed', error=str(exc))
            arrows = {}
    (out / 'arrows.json').write_text(json.dumps(arrows))
    mark('review_start', crops=len(bundle['images'][image_id]['crop_pairs']))
    review = out / 'review' / image_id
    prepare({'images': {image_id: bundle['images'][image_id]}}, review,
            upstream_arrow_specs=arrows, capabilities=policy)
    print(json.dumps({'case': image_id, 'status': 'prepared'}), flush=True)
    result = review_run(review, sender=review_sender, request_limit=2, capabilities=policy)
    if set(result.get('images', {})) != {image_id}:
        raise ValueError('review terminal image identity mismatch')
    terminal = result['images'][image_id]
    source_svg, source_png = Path(terminal['svg']), Path(terminal['png'])
    if not source_svg.is_file() or sha(source_svg) != terminal.get('revision'):
        raise ValueError('review terminal SVG revision mismatch')
    if not source_png.is_file():
        raise ValueError('review terminal PNG is missing')
    final = out/'final'; final.mkdir()
    shutil.copyfile(source_svg, final/'scene.svg')
    shutil.copyfile(source_png, final/'preview.png')
    exported = dict(terminal, svg=str(final/'scene.svg'), png=str(final/'preview.png'))
    write_json(out/'chain-result.json', {
        'status': result.get('status'), 'images': {image_id: exported},
        'visual_passed': False, 'capabilities': policy,
        'capability_sha256': capability_hash(policy),
        'source_image_sha256': sha(image), 'review_result': str(review/'result.json'),
        'terminal_source': {'svg': str(source_svg), 'png': str(source_png),
                            'revision': terminal['revision'], 'png_sha256': sha(source_png)},
    })
    state = json.loads((run/'run.json').read_text())
    state.update(latest_stage=str(final), status=result.get('status'),
                 chain_result=str(out/'chain-result.json'), visual_passed=False)
    write_json(run/'run.json', state)
    mark('review_done', status=result.get('status'))
    print(str(out))
    return out
