"""One figure, one command: GPT-5.5, crops, two DeepSeek calls, then a third only if priority issues did not land."""
import hashlib
import json
import math
import time
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

from figfox_plus.native.pipeline import first, stage
from figfox_plus.native.document import extract_response
from figfox_plus.native.artifacts import publish_latest
from figfox_plus.native.review_problem_first_v13.inputs import validate_bundle
from figfox_plus.native.review_problem_first_v13.orchestrator import prepare, run as review_run
from figfox_plus.native.review_problem_first_v13.upstream_arrows import freeze_arrow_evidence
from figfox_plus.providers import call_gpt55
from figfox_plus.state import new_run, write_json
from figfox_plus.progress import RunStatus
from figfox_plus.native.first_recovery import recover_baseline


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
    pack = json.loads((stage_dir / 'pack' / 'pack.json').read_text(encoding='utf-8'))
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


def run_chain(image, out, *, image_id, rerun_authorization, resume_first=None, resume_baseline=None, review_sender=None, monitor=False):
    image = Path(image).resolve()
    out = Path(out).resolve()
    if not image.is_file():
        raise SystemExit(f'missing image: {image}')
    if not image_id.replace('-', '').replace('_', '').isalnum():
        raise SystemExit('invalid image id')
    saved_run = None
    saved_sam = None
    if resume_first is not None and resume_baseline is not None:
        raise SystemExit('choose one resume mode')
    if resume_first is not None or resume_baseline is not None:
        saved_run = Path(resume_first or resume_baseline).resolve()
        if saved_run.parent != out or not saved_run.name.startswith('native-'):
            raise SystemExit('resume-first must be a native run inside the chain output')
        state = json.loads((saved_run / 'run.json').read_text(encoding='utf-8'))
        if Path(state['original']).resolve() != image:
            raise SystemExit('resume image does not match the saved run')
        if (out / 'review').exists() or (resume_first is not None and (saved_run / 'stage-0').exists()):
            raise SystemExit('resume-first only supports failures before the baseline stage')
        if resume_baseline is not None and not (saved_run/'stage-0/scene.svg').is_file():
            raise SystemExit('saved baseline missing')
        if resume_baseline is not None and sha(saved_run/'stage-0/scene.svg')!=state.get('baseline_svg_sha256'):
            raise SystemExit('saved baseline hash mismatch')
        response = json.loads((saved_run / 'gpt55' / 'response.json').read_text(encoding='utf-8'))
        if response.get('status') != 'completed':
            raise SystemExit('saved GPT response is not complete')
        saved_sam = json.loads((saved_run / 'sam.json').read_text(encoding='utf-8'))
        if saved_sam.get('source_hash') != sha(image):
            raise SystemExit('resume image content does not match the saved SAM source')
    else:
        if out.exists():
            raise SystemExit(f'already exists: {out}')
        out.mkdir()
    log = out / 'chain-timing.jsonl'
    runtime = RunStatus(out, image, image_id)
    if monitor:
        from figfox_plus.monitor import start_monitor
        start_monitor(out)

    def mark(event, **extra):
        row = {'event': event, 'at': time.time(), **extra}
        with log.open('a', encoding='utf-8') as handle:
            handle.write(json.dumps(row) + '\n')
        print(json.dumps(row), flush=True)
        runtime.stage(event)

    mark('gpt55_reused' if saved_run else 'gpt55_start')
    run = saved_run or new_run(out, 'native')
    if not saved_run:write_json(run / 'run.json', {
        'original': str(image),
        'execution_source': 'native-gpt55',
        'status': 'building',
        'visual_passed': False,
    })

    def send(prompt, images, run_dir, purpose):
        if saved_run:
            return extract_response(saved_run / 'gpt55' / 'response.json')
        return call_gpt55(prompt, images, run_dir, purpose, rerun_authorization=rerun_authorization)

    failure = None
    try:
        if resume_baseline is None:
            try:
                root = first(image, run, send=send, sam=saved_sam)
                stage(root, image, run / 'stage-0')
            except (ValueError, ET.ParseError, OSError) as exc:
                mark('gpt55_local_recovery', error_type=type(exc).__name__)
                root = recover_baseline(image, run, exc, first=first, stage=stage)
        state = json.loads((run / 'run.json').read_text(encoding='utf-8'))
        state.update(latest_stage=str(run / 'stage-0'), status='baseline_rendered', baseline_svg_sha256=sha(run / 'stage-0' / 'scene.svg'))
        write_json(run / 'run.json', state)
        publish_latest(out, image_id)
        mark('gpt55_done', run=str(run))
        bundle = bundle_from_stage(run, image, image_id)
        validate_bundle(bundle)
        (out / 'bundle.json').write_text(json.dumps(bundle), encoding='utf-8')
        arrows = {image_id: {'sam_manifest': str(run / 'sam.json'), 'head_evidence': str(run / 'arrow-head-evidence.json')}}
        try:
            freeze_arrow_evidence(arrows[image_id], bundle['images'][image_id]['original_png'], out / 'arrow-check')
        except (ValueError, OSError, KeyError, TypeError) as exc:
            mark('arrow_handoff_failed', error=str(exc))
            arrows = {}
        (out / 'arrows.json').write_text(json.dumps(arrows), encoding='utf-8')
        mark('review_start', crops=len(bundle['images'][image_id]['crop_pairs']))
        review = out / 'review' / image_id
        prepare({'images': {image_id: bundle['images'][image_id]}}, review, upstream_arrow_specs={image_id: arrows.get(image_id)})
        print(json.dumps({'case': image_id, 'status': 'prepared'}), flush=True)
        review_options = {'sender':review_sender} if review_sender is not None else {}
        result = review_run(review, request_limit=2, **review_options)
        runtime.update(review_status=result.get('status'),
                       followup_status=(result.get('followup') or {}).get('status'))
        mark('review_done', status=result.get('status'))
    except BaseException as exc:
        failure = {'type': type(exc).__name__, 'message': str(exc)}
        mark('chain_failed', **failure)
        raise
    finally:
        try:
            artifacts = publish_latest(out, image_id, error=failure)
            mark('artifacts_checked', artifact_status=artifacts['artifact_status'], output_stage=artifacts['output_stage'])
        except Exception as exc:
            if failure is None:
                failure = {'type':type(exc).__name__,'message':str(exc)}
                raise
            mark('artifact_publication_failed', message=str(exc))
        finally:
            runtime.finish(failure)
    print(str(out))
    return out
