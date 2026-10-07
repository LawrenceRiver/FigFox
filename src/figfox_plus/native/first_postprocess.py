"""Isolate optional model declarations so one bad parameter cannot erase a figure."""
from copy import deepcopy
import hashlib
import json
import subprocess

from .document import validate, serialize, measure
from .color_guard import check_color_change, ColorSampleUnverified
from .sam_groups import crop_target_box
from .sam_replace import apply_replacements
from .tools import execute, nodes, sp_element
from ..state import write_json


def apply_declarations(root, original, run, *, preserve_candidates=False):
    records = []
    color_log = []
    candidates = []

    def attempt(current, step, object_id, apply):
        trial = deepcopy(current)
        try:
            trial, receipt = apply(trial)
            validate(trial)
        except (ValueError, KeyError, TypeError, IndexError, OSError, subprocess.TimeoutExpired) as exc:
            record = {'step': step, 'object_id': object_id, 'status': 'deferred',
                      'error': type(exc).__name__ + ': ' + str(exc), 'original_preserved': True}
            if getattr(exc, 'check', None):
                record['source_color_check'] = exc.check
            candidate_root = getattr(exc, 'candidate_root', None)
            if preserve_candidates and candidate_root is not None:
                candidate = {'step': step, 'object_id': object_id, 'candidate_only': True,
                             'automatically_adopted': False, 'visual_acceptance': 'pending',
                             'model_requests': 0, 'base_revision': hashlib.sha256(serialize(current).encode()).hexdigest()}
                try:
                    destination = run / 'first-candidates' / f'{len(candidates):04d}'
                    destination.mkdir(parents=True, exist_ok=True)
                    svg, png = destination / 'scene.svg', destination / 'scene.png'
                    measure(candidate_root, png)
                    svg.write_text(serialize(candidate_root), encoding='utf-8')
                    candidate.update(status='available', image={'svg':str(svg.resolve()), 'png':str(png.resolve())})
                except Exception as error:
                    candidate.update(status='failed', error=type(error).__name__ + ': ' + str(error))
                candidates.append(candidate)
                record['candidate_index'] = len(candidates) - 1
            records.append(record)
            return current, None
        records.append({'step': step, 'object_id': object_id, 'status': 'executed'})
        return trial, receipt

    for node in list(root.iter()):
        if not node.get('data-plus-sp'):
            continue
        oid = node.get('id')

        def construct(trial):
            target = nodes(trial)[oid]
            spec = json.loads(target.get('data-plus-sp'))
            part = sp_element(spec['kind'], spec['data'], oid)
            target.extend(list(part))
            target.attrib.pop('data-plus-sp')
            return trial, None

        root, _ = attempt(root, 'sp', oid, construct)

    for node in list(root.iter()):
        if not node.get('data-plus-crop'):
            continue
        oid = node.get('id')

        def crop(trial):
            target = nodes(trial)[oid]
            values = [float(v) for v in target.get('data-plus-crop').split(',')]
            op = {'id': 'crop_' + oid, 'issue_id': 'first', 'action': 'asset',
                  'target_ids': [oid], 'args': {'source_crop': values,
                  'target_box': crop_target_box(target, values),
                  'classification': 'photo' if target.get('data-plus-representation') == 'raster' else 'complex_geometry'}}
            return execute(trial, [op], [{'id': 'first', 'target_ids': [oid]}], original, run)

        root, _ = attempt(root, 'crop', oid, crop)

    for node in list(root.iter()):
        if not node.get('data-plus-color'):
            continue
        oid = node.get('id')

        def colors(trial):
            before = nodes(trial)[oid]
            samples = json.loads(before.get('data-plus-color'))
            if not isinstance(samples, dict) or not samples or set(samples) - {'fill', 'stroke'}:
                raise ValueError('invalid color sampling declaration')
            logs = []
            for attribute, roi in samples.items():
                op = {'id': 'color_' + oid + '_' + attribute, 'issue_id': 'first_color_' + oid,
                      'action': 'sample_color', 'target_ids': [oid],
                      'args': {'source_crop': roi, 'attribute': attribute}}
                trial, log = execute(trial, [op], [{'id': op['issue_id'], 'target_ids': [oid]}],
                                     original, run / 'first-color-tools')
                logs.extend(log)
            nodes(trial)[oid].attrib.pop('data-plus-color', None)
            try:
                check_color_change(before, nodes(trial)[oid], samples)
            except ColorSampleUnverified as error:
                error.candidate_root = trial
                raise
            return trial, logs

        root, logs = attempt(root, 'color', oid, colors)
        color_log.extend(logs or [])

    def replace(trial):
        return trial, apply_replacements(trial)

    root, replacements = attempt(root, 'sam_replacement', None, replace)
    write_json(run / 'first-sam-replacement.json', replacements or [])
    write_json(run / 'first-color-execution.json', color_log)
    write_json(run / 'first-postprocessing.json',
               {'steps': records, 'deferred_count': sum(r['status'] == 'deferred' for r in records),
                'candidates': candidates, 'visual_passed': False})
    return root
