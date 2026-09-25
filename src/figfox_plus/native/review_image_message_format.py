"""Lossless presentation of host-bound image identities, without I/O or API calls.

This changes message boundaries and adds headings only. Consecutive user messages
are still submitted together in one request by the caller. Inputs must already be
host-validated; this module verifies catalog correspondence, not image pixels.
"""
from copy import deepcopy
import json


def _ident(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f'{label} must be a nonempty string')
    return value


def format_initial_image_messages(messages, validated_inputs, *,
                                  upstream_arrow_assets=(), upstream_arrow_context=None):
    """Return ``(new_messages, audit)``; never mutate any input.

    Full/crop pairs must be adjacent metadata/image tuples in one user message.
    Pair sides may arrive in either order; their order is never changed. Unknown,
    duplicated, missing or unpairable assets raise ValueError. SAM identities are
    joined by exact asset_id through explicit upstream context, never ID spelling.
    """
    if not isinstance(validated_inputs, dict) or not isinstance(validated_inputs.get('images'), dict):
        raise ValueError('validated_inputs.images must be an object')
    catalog = {}

    def add(asset, image_id, kind, pair_id, role):
        if not isinstance(asset, dict):
            raise ValueError('asset must be an object')
        ident = _ident(asset.get('asset_id'), 'asset_id')
        sha = _ident(asset.get('sha256'), 'sha256')
        if ident in catalog:
            raise ValueError(f'duplicate catalog asset: {ident}')
        catalog[ident] = dict(asset_id=ident, sha256=sha, image_id=image_id,
                              kind=kind, pair_id=pair_id, role=role)

    for image_id, image in validated_inputs['images'].items():
        _ident(image_id, 'image_id')
        if not isinstance(image, dict):
            raise ValueError('image catalog must be an object')
        for key, role in [('original_png', 'original'), ('current_png', 'current')]:
            add(image.get(key), image_id, 'full_pair', None, role)
        pairs = image.get('crop_pairs', [])
        if not isinstance(pairs, list):
            raise ValueError('crop_pairs must be an array')
        pair_ids = set()
        for pair in pairs:
            if not isinstance(pair, dict):
                raise ValueError('crop pair must be an object')
            pair_id = _ident(pair.get('pair_id'), 'pair_id')
            if pair_id in pair_ids:
                raise ValueError('duplicate pair_id')
            pair_ids.add(pair_id)
            for key, role in [('original_asset', 'original'), ('current_asset', 'current')]:
                add(pair.get(key), image_id, 'crop_pair', pair_id, role)

    if not isinstance(upstream_arrow_assets, (list, tuple)):
        raise ValueError('upstream_arrow_assets must be an array')
    bindings = {}
    context = {} if upstream_arrow_context is None else upstream_arrow_context
    if not isinstance(context, dict):
        raise ValueError('upstream_arrow_context must be an object')
    for image_id, evidence in context.items():
        if image_id not in validated_inputs['images'] or not isinstance(evidence, dict):
            raise ValueError('unknown SAM image binding')
        arrows = evidence.get('arrows', [])
        if not isinstance(arrows, list):
            raise ValueError('SAM arrows must be an array')
        if arrows and (evidence.get('status') != 'available' or
                       evidence.get('coordinate_domain') != 'original_image_pixels' or
                       evidence.get('is_ground_truth') is not False):
            raise ValueError('SAM binding must explicitly identify original candidate coordinates')
        for arrow in arrows:
            if not isinstance(arrow, dict):
                raise ValueError('SAM arrow must be an object')
            ident = _ident(arrow.get('asset_id'), 'SAM asset_id')
            if ident in bindings:
                raise ValueError('duplicate SAM binding')
            bindings[ident] = image_id
    arrow_ids = []
    for asset in upstream_arrow_assets:
        if not isinstance(asset, dict):
            raise ValueError('SAM asset must be an object')
        ident = _ident(asset.get('asset_id'), 'SAM asset_id')
        if ident not in bindings:
            raise ValueError(f'missing explicit SAM binding: {ident}')
        arrow_ids.append(ident)
        add(asset, bindings[ident], 'sam_original_candidate', None, 'original_candidate')
    if set(arrow_ids) != set(bindings):
        raise ValueError('SAM mappings and assets differ')

    output, seen, groups, headings, order = [], set(), [], [], []

    def emit(source, content):
        message = deepcopy(source)
        message['content'] = deepcopy(content)
        output.append(message)

    def read_tuple(content, index):
        block = content[index]
        meta = None
        if isinstance(block, dict) and block.get('type') == 'text':
            try:
                meta = json.loads(block.get('text', ''))
            except (ValueError, TypeError):
                pass
        if not isinstance(meta, dict) or 'asset_id' not in meta:
            if isinstance(block, dict) and block.get('type') == 'image_url':
                raise ValueError('image without adjacent asset metadata')
            return None
        ident = meta.get('asset_id')
        if not isinstance(ident, str) or ident not in catalog:
            raise ValueError('unknown image asset metadata')
        if ident in seen:
            raise ValueError(f'duplicate image asset: {ident}')
        if meta.get('sha256') != catalog[ident]['sha256']:
            raise ValueError(f'asset hash mismatch: {ident}')
        if index + 1 >= len(content):
            raise ValueError('asset metadata without image')
        image = content[index + 1]
        if (not isinstance(image, dict) or image.get('type') != 'image_url' or
            not isinstance(image.get('image_url'), dict) or
            not isinstance(image['image_url'].get('url'), str) or not image['image_url']['url']):
            raise ValueError('asset metadata must immediately precede an image URL')
        seen.add(ident)
        order.append(ident)
        return catalog[ident], content[index:index + 2]

    if not isinstance(messages, list):
        raise ValueError('messages must be an array')
    for source in messages:
        if not isinstance(source, dict):
            raise ValueError('message must be an object')
        content = source.get('content')
        if source.get('role') != 'user' or not isinstance(content, list):
            if isinstance(content, list) and any(isinstance(b, dict) and b.get('type') == 'image_url' for b in content):
                raise ValueError('initial images must be in user messages')
            output.append(deepcopy(source))
            continue
        pending, i = [], 0
        if not content:
            emit(source, [])
        while i < len(content):
            item = read_tuple(content, i)
            if item is None:
                pending.append(content[i])
                i += 1
                continue
            if pending:
                emit(source, pending)
                pending = []
            record, original_blocks = item
            members = [(record, original_blocks)]
            i += 2
            if record['kind'] != 'sam_original_candidate':
                other = read_tuple(content, i) if i < len(content) else None
                if (other is None or
                    any(other[0][k] != record[k] for k in ('image_id', 'kind', 'pair_id')) or
                    other[0]['role'] == record['role']):
                    raise ValueError('pair assets must remain adjacent in their original order')
                members.append(other)
                i += 2
            parts = []
            message_index = len(output)
            for member, original_blocks in members:
                if member['kind'] == 'sam_original_candidate':
                    title = 'SAM ORIGINAL CANDIDATE — 原图候选，非答案；可能漏检或误检'
                elif member['role'] == 'original':
                    title = 'REFERENCE ORIGINAL — 参考原图'
                else:
                    title = 'CURRENT SVG RENDER — 当前 SVG 渲染图'
                heading = f"{title}\nimage_id: {member['image_id']}\nasset_id: {member['asset_id']}"
                if member['pair_id'] is not None:
                    heading += f"\nexisting_crop_pair_id: {member['pair_id']}"
                headings.append([message_index, 'content', len(parts)])
                parts.append({'type': 'text', 'text': heading})
                parts.extend(original_blocks)
            emit(source, parts)
            groups.append(dict(kind=record['kind'], image_id=record['image_id'],
                               pair_id=record['pair_id'], output_message_index=message_index,
                               asset_ids=[m['asset_id'] for m, _ in members]))
        if pending:
            emit(source, pending)
    missing = set(catalog) - seen
    if missing:
        raise ValueError(f'missing image assets: {sorted(missing)}')
    return output, dict(groups=groups, inserted_heading_paths=headings, asset_order=order,
                        input_image_count=len(order), output_image_count=len(order))
