"""Validate an explicit upstream handoff. Never discover files or produce crops.

FrozenInputs is a JSON-serializable, allowlisted snapshot of asset identities,
not filesystem immutability. Call validate_bundle again before sending/executing.
The producer's SVG-render revision binding is checked; it is not independently
proved by rasterizing SVG in this input validator.
"""
from __future__ import annotations
import hashlib
import math
from pathlib import Path
from PIL import Image


def _fail(message):
    raise ValueError(f'input_invalid: {message}')


def _asset(value, asset_id, *, png=False):
    if not isinstance(value, dict) or not isinstance(value.get('path'), str):
        _fail(f'{asset_id}: expected explicit asset path and sha256')
    path = Path(value['path']).expanduser().resolve(strict=True)
    if not path.is_file():
        _fail(f'{asset_id}: not a file')
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if value.get('sha256') != digest:
        _fail(f'{asset_id}: sha256 mismatch')
    out = {'path': str(path), 'sha256': digest, 'asset_id': asset_id}
    if png:
        with Image.open(path) as image:
            if image.format != 'PNG':
                _fail(f'{asset_id}: expected PNG')
            out['dimensions'] = list(image.size)
            image.verify()
        if 'dimensions' in value and value['dimensions'] != out['dimensions']:
            _fail(f'{asset_id}: declared dimensions mismatch')
    return out


def _revision(value, expected, label):
    rev = value.get('current_revision', value.get('revision'))
    if rev != expected:
        _fail(f'{label}: current revision mismatch')
    if 'revision' in value and value['revision'] != expected:
        _fail(f'{label}: conflicting revision')


def validate_bundle(bundle):
    """Return only validated image handoff fields; methods are host-supplied.

    Schema: images is an insertion-ordered map of image_id to original_png,
    current_svg, current_png, current_tp, current_revision, crop_pairs.
    Assets are {path, sha256}; PNG and TP additionally bind revision/current_revision.
    current_tp.domain must be 'current'. Each crop pair requires producer_version,
    pair_id, original/current_revision, both assets, display_mapping, comparison_scale.
    """
    if not isinstance(bundle, dict) or not isinstance(bundle.get('images'), dict) or not bundle['images']:
        _fail('images must be a nonempty object')
    result = {'schema_version': 'review-inputs-v1', 'images': {}}
    try:
        for image_id, raw in bundle['images'].items():
            if not isinstance(image_id, str) or not image_id.strip() or not isinstance(raw, dict):
                _fail('invalid image identity')
            image = {}
            for name in ('original_png','current_svg','current_png','current_tp'):
                image[name] = _asset(raw.get(name), f'{image_id}/{name}', png=name.endswith('_png'))
            revision = image['current_svg']['sha256']
            if raw.get('current_revision') != revision:
                _fail(f'{image_id}: current_revision must identify current SVG')
            for name in ('current_png','current_tp'):
                _revision(raw[name], revision, f'{image_id}/{name}')
                image[name]['current_revision'] = revision
            if raw['current_tp'].get('domain') != 'current':
                _fail(f'{image_id}: TP only belongs to current image')
            image['current_tp']['domain'] = 'current'
            image['current_revision'] = revision
            pairs = raw.get('crop_pairs')
            if not isinstance(pairs, list) or not pairs:
                _fail(f'{image_id}: missing upstream crop_pairs; no crops are generated here')
            image['crop_pairs'] = []
            seen = set()
            for pair in pairs:
                if not isinstance(pair, dict):
                    _fail(f'{image_id}: invalid crop pair')
                pid = pair.get('pair_id')
                if not isinstance(pid,str) or not pid.strip() or pid == 'full' or pid in seen:
                    _fail(f'{image_id}: duplicate or invalid pair_id')
                seen.add(pid)
                if pair.get('current_revision') != revision or pair.get('original_revision') != image['original_png']['sha256']:
                    _fail(f'{image_id}/{pid}: crop revision mismatch')
                producer = pair.get('producer_version')
                if not isinstance(producer,str) or not producer.strip():
                    _fail(f'{image_id}/{pid}: producer_version required')
                scale = pair.get('comparison_scale')
                if isinstance(scale,bool) or not isinstance(scale,(float,int)) or not math.isfinite(scale) or scale <= 0:
                    _fail(f'{image_id}/{pid}: comparison_scale must be positive')
                mapping = pair.get('display_mapping')
                if not isinstance(mapping,dict) or not mapping:
                    _fail(f'{image_id}/{pid}: display_mapping required')
                # Only explicit geometric mappings are forwarded; arbitrary notes are not input evidence.
                clean_mapping = {}
                for side in ('original','current'):
                    bounds = mapping.get(side)
                    if not isinstance(bounds,list) or len(bounds)!=4 or any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in bounds):
                        _fail(f'{image_id}/{pid}: display_mapping.{side} must be four finite coordinates')
                    if bounds[2] <= bounds[0] or bounds[3] <= bounds[1]:
                        _fail(f'{image_id}/{pid}: mapping must be [left,top,right,bottom]')
                    clean_mapping[side] = list(bounds)
                clean = {'pair_id':pid,'producer_version':producer,'original_revision':image['original_png']['sha256'],'current_revision':revision,'comparison_scale':scale,'display_mapping':clean_mapping}
                for side in ('original','current'):
                    clean[side+'_asset'] = _asset(pair.get(side+'_asset'),f'{image_id}/crop/{pid}/{side}',png=True)
                image['crop_pairs'].append(clean)
            result['images'][image_id] = image
    except (OSError, KeyError, TypeError) as exc:
        _fail(str(exc))
    return result
