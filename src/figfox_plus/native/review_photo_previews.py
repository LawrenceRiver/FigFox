"""Collect supplemental PNG evidence from committed host sp_photo receipts.

Input is an explicit current execution directory, never a project/run search.
The directory's trusted host state.json is authoritative: public result.json
does not contain tool results. Only successful module RCDs and their applied
sp_photo returns are followed. Asset sidecar names are the producer contract in
assets.py (PNG.with_suffix('.json')); no guessed crop/RMBG names or globbing.

This does not crop, remove backgrounds, render vectors, send API requests, or
replace full original/current images. The caller must supply a host-owned
execution directory, not model-authored state. Reported PNG hashes bind bytes
at collection time; consumers should verify hashes again if reopening later.
"""
from copy import deepcopy
import hashlib
import io
import json
import os
from pathlib import Path
import re
import stat

from PIL import Image


class _Reader:
    """Read bounded regular files below an open root, refusing symlink hops."""

    def __init__(self, root):
        self.root = Path(root).resolve(strict=True)
        self.fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)

    def close(self):
        os.close(self.fd)

    def path(self, value):
        if not isinstance(value, (str, Path)) or not str(value):
            raise ValueError('missing explicit asset path')
        candidate = Path(value)
        if '..' in candidate.parts:
            raise ValueError('path traversal forbidden')
        if not candidate.is_absolute():
            candidate = self.root / candidate
        try:
            relative = candidate.relative_to(self.root)
        except ValueError:
            raise ValueError('path outside current execution directory') from None
        if not relative.parts:
            raise ValueError('expected file path')
        return candidate, relative.parts

    def read(self, value, limit):
        _, parts = self.path(value)
        directory = os.dup(self.fd)
        try:
            for part in parts[:-1]:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=directory)
                os.close(directory)
                directory = child
            fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
            with os.fdopen(fd, 'rb') as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > limit:
                    raise ValueError('not a bounded regular file')
                data = stream.read(limit + 1)
                if len(data) > limit:
                    raise ValueError('file exceeds size limit')
                return data
        finally:
            os.close(directory)

    def metadata(self, png):
        path, _ = self.path(png)
        value = json.loads(self.read(path.with_suffix('.json'), 1_000_000))
        if not isinstance(value, dict):
            raise ValueError('asset metadata must be an object')
        return value


def _sha(data):
    return hashlib.sha256(data).hexdigest()


def _png(reader, path, max_bytes, max_pixels):
    normalized, _ = reader.path(path)
    if normalized.suffix.lower() != '.png':
        raise ValueError('preview must be an explicitly referenced PNG')
    data = reader.read(normalized, max_bytes)
    with Image.open(io.BytesIO(data)) as image:
        if image.format != 'PNG' or image.width * image.height > max_pixels:
            raise ValueError('preview is not a bounded PNG')
        size, mode = list(image.size), image.mode
        image.verify()
    return {'path': str(normalized), 'sha256': _sha(data), 'width': size[0],
            'height': size[1], 'mode': mode, 'mime_type': 'image/png'}


def _photo_entries(value, program_id, pointer, depth=0):
    """Traverse only known host result containers, not arbitrary nested fields."""
    if depth > 12:
        raise ValueError('tool result nesting limit exceeded')
    if not isinstance(value, dict):
        return
    operations = value.get('operations')
    if isinstance(operations, list):
        for index, child in enumerate(operations):
            yield from _photo_entries(child, program_id, pointer + ['operations', index], depth + 1)
    reports = value.get('issues')
    if not isinstance(reports, list):
        return
    for index, report in enumerate(reports):
        if (not isinstance(report, dict) or report.get('id') != program_id
                or report.get('status') != 'applied' or report.get('errors')):
            continue
        for op_index, entry in enumerate(report.get('applied_operations', [])):
            if (isinstance(entry, dict) and isinstance(entry.get('input'), dict)
                    and entry['input'].get('method') == 'sp_photo'):
                yield entry, pointer + ['issues', index, 'applied_operations', op_index, 'result']


def _photo_pair(reader, entry, max_bytes, max_pixels):
    result = entry.get('result')
    if not isinstance(result, dict) or not isinstance(result.get('asset'), dict):
        raise ValueError('missing host photo result or asset')
    asset = result['asset']
    mapping = result.get('source_mapping', {})
    crop = asset.get('source_crop')
    source_hash = asset.get('source_hash')
    if (asset.get('method') != 'original-image-crop'
            or not isinstance(source_hash, str) or not re.fullmatch('[0-9a-f]{64}', source_hash)
            or not isinstance(crop, list) or len(crop) != 4
            or any(type(v) is not int for v in crop) or min(crop[:2]) < 0 or min(crop[2:]) <= 0
            or mapping.get('actual_crop') != crop
            or mapping.get('requested_crop') != entry['input'].get('args', {}).get('source_crop')
            or mapping.get('requested_crop') != asset.get('requested_crop')
            or mapping.get('original_pixel_mapping') != 'identity'
            or mapping.get('crop_pixels_to_original') != [1, 0, 0, 1, crop[0], crop[1]]):
        raise ValueError('photo crop provenance mismatch')
    representation = result.get('representation')
    if representation != asset.get('representation') or representation not in ('raster', 'vector'):
        raise ValueError('photo representation mismatch')
    # Vector outputs explicitly record their PNG input. Never read the SVG or
    # derive a PNG filename from the vector's output name.
    final_png = asset.get('source_asset_path') if representation == 'vector' else result.get('asset_path')
    removal = asset.get('background_removal')
    raw_png = removal.get('source_asset_path') if isinstance(removal, dict) else final_png
    raw = _png(reader, raw_png, max_bytes, max_pixels)
    metadata = reader.metadata(raw_png)
    raw_id = 'asset_' + hashlib.sha256((source_hash + str(crop)).encode()).hexdigest()[:20]
    if (metadata.get('id') != raw_id or metadata.get('method') != 'original-image-crop'
            or metadata.get('representation') != 'raster'
            or metadata.get('source_hash') != source_hash or metadata.get('source_crop') != crop
            or metadata.get('requested_crop') != asset.get('requested_crop')
            or metadata.get('source_size') != asset.get('source_size')
            or reader.path(metadata.get('path'))[0] != reader.path(raw_png)[0]
            or [raw['width'], raw['height']] != crop[2:]):
        raise ValueError('original crop sidecar does not match host photo return')
    raw.update(role='source_crop', asset_id=raw_id)
    previews = [raw]
    if removal is not None:
        if not isinstance(removal, dict) or removal.get('method') != 'RMBG2':
            raise ValueError('unknown background-removal provenance')
        if removal.get('signature', {}).get('crop_sha256') != raw['sha256']:
            raise ValueError('RMBG crop input hash mismatch')
        output = _png(reader, final_png, max_bytes, max_pixels)
        metadata = reader.metadata(final_png)
        derived = metadata.get('derived', {})
        if (metadata.get('output_sha256') != output['sha256']
                or derived.get('background_removal') != removal
                or not isinstance(derived.get('id'), str) or not derived['id'].startswith(raw_id + '_rmbg_')
                or output['mode'] != 'RGBA' or [output['width'], output['height']] != crop[2:]
                or (representation == 'raster' and derived['id'] != asset.get('id'))):
            raise ValueError('RMBG output sidecar/hash mismatch')
        output.update(role='rmbg_output', asset_id=derived['id'])
        previews.append(output)
    elif representation == 'raster' and asset.get('id') != raw_id:
        raise ValueError('crop asset identity mismatch')
    for preview in previews:
        preview.update(source_hash=source_hash, source_crop=deepcopy(crop),
                       source_mapping=deepcopy(mapping), photo_representation=representation)
    return previews


def collect_photo_previews(execution_dir, execution_result=None, *,
                           max_png_bytes=20_000_000, max_pixels=40_000_000):
    """Return {previews, rejections} for supplemental second-turn image inputs.

    execution_result, when provided, must carry the unchanged RCD returned by
    this execution. The explicit directory must be host-controlled. Failed or
    rolled-back programs never contribute images, even if asset files remain.
    Rejections are diagnostic metadata, not preview assets or visual verdicts.
    """
    if type(max_png_bytes) is not int or max_png_bytes <= 0 or type(max_pixels) is not int or max_pixels <= 0:
        raise ValueError('positive integer preview limits required')
    reader = _Reader(execution_dir)
    try:
        state_bytes = reader.read('state.json', 32_000_000)
        state = json.loads(state_bytes)
        if (not isinstance(state, dict) or not isinstance(state.get('rcd'), list)
                or not isinstance(state.get('results'), dict) or not isinstance(state.get('signature'), str)):
            raise ValueError('invalid host execution state')
        if execution_result is not None and (not isinstance(execution_result, dict)
                or execution_result.get('rcd') != state['rcd']):
            raise ValueError('execution result rcd differs from this execution state')
        previews, rejections, seen = [], [], set()
        for record in state['rcd']:
            if not isinstance(record, dict) or not isinstance(record.get('program_id'), str):
                raise ValueError('invalid execution RCD')
            pid = record['program_id']
            if pid in seen:
                raise ValueError('duplicate execution program identity')
            seen.add(pid)
            if pid not in state['results']:
                continue
            if (record.get('status') not in ('changed_unverified', 'executed_no_change')
                    or record.get('rolled_back') or record.get('route') != 'module_program'):
                rejections.append({'program_id': pid, 'error': 'program is not a committed module execution'})
                continue
            if (not isinstance(record.get('image_id'), str) or not isinstance(record.get('issue_ids'), list)
                    or not record['issue_ids'] or any(not isinstance(i, str) for i in record['issue_ids'])):
                rejections.append({'program_id': pid, 'error': 'missing program/image/issue binding'})
                continue
            for entry, pointer in _photo_entries(state['results'][pid], pid, ['results', pid]):
                try:
                    pair = _photo_pair(reader, entry, max_png_bytes, max_pixels)
                    for preview in pair:
                        preview.update(program_id=pid, issue_ids=deepcopy(record['issue_ids']),
                                       image_id=record['image_id'], before_revision=record.get('before_revision'),
                                       after_revision=record.get('after_revision'),
                                       execution_signature=state['signature'], state_sha256=_sha(state_bytes),
                                       receipt_path=pointer, execution_dir=str(reader.root))
                        preview['preview_id'] = _sha(json.dumps(
                            [state['signature'], pid, pointer, preview['role'], preview['sha256']],
                            ensure_ascii=False, sort_keys=True).encode())
                    previews.extend(pair)
                except (OSError, ValueError, TypeError, KeyError, Image.DecompressionBombError) as exc:
                    rejections.append({'program_id': pid, 'receipt_path': pointer, 'error': str(exc)})
        return {'previews': previews, 'rejections': rejections}
    finally:
        reader.close()
