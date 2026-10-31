"""Strict transport shape for review plans; never executes or repairs model JSON.

DeepSeek's beta strict mode requires every object property to be required and
additionalProperties=false. It does not support array min/maxItems or string
min/maxLength: https://api-docs.deepseek.com/guides/tool_calls/

This module checks shape, not observation truth, coverage semantics, tool scope,
or executable-program validity. The existing v3 audits and executor remain
mandatory after decoding. No provider calls or filesystem reads occur here.
"""
from copy import deepcopy
import json


DEFAULT_CATEGORIES = ('E', 'F', 'B', 'A', 'S1')


def _object(properties):
    return {'type': 'object', 'properties': properties,
            'required': list(properties), 'additionalProperties': False}


def _array(items):
    return {'type': 'array', 'items': items}


def _string(choices=None):
    schema = {'type': 'string'}
    if choices is not None:
        schema['enum'] = list(choices)
    return schema


def _identities(regions, categories):
    """Accept the compact host region manifest, preserving its explicit order."""
    categories = tuple(categories)
    if (not categories or any(not isinstance(c, str) or not c for c in categories)
            or len(set(categories)) != len(categories)):
        raise ValueError('categories must be unique nonempty strings')
    if not isinstance(regions, list) or not regions:
        raise ValueError('nonempty host regions required')
    numbers = []
    for region in regions:
        if (not isinstance(region, dict) or type(region.get('region')) is not int
                or region['region'] < 0 or type(region.get('pass')) is not int
                or region['pass'] not in (1, 2, 3)):
            raise ValueError('invalid host region identity or pass')
        numbers.append(region['region'])
    if len(set(numbers)) != len(numbers):
        raise ValueError('duplicate host region identity')
    return numbers, categories


def build_schema(regions, categories=DEFAULT_CATEGORIES, review_only=False):
    """Return a function-parameters schema, with host-fixed category/region keys.

    The caller supplies strict=true and the beta endpoint in its own transport.
    Review-only requests omit inspection properties entirely (strict objects
    cannot declare optional properties).
    """
    numbers, categories = _identities(regions, categories)
    issue = _object({
        'id': _string(), 'image_id': _string(), 'category': _string(categories),
        'description': _string(), 'original_evidence': _string(),
        'current_evidence': _string(), 'target_ids': _array(_string()),
        'neighbor_ids': _array(_string()),
        'decision': _string(('confirmed', 'uncertain', 'preserved', 'duplicate')),
        'duplicate_of': _string(), 'unresolved_reason': _string(),
    })
    properties = {}
    if not review_only:
        check = _object({
            'state': _string(('clear', 'issue', 'uncertain', 'not_applicable')),
            'original_observation': _string(), 'current_observation': _string(),
            'issue_ids': _array(_string()), 'candidate_check': _string(),
            'applicability_reason': _string(), 'svg_observation': _string(),
        })
        properties['category_checks'] = _object({
            category: _object({str(number): deepcopy(check) for number in numbers})
            for category in categories
        })
        region_number = {'type': 'integer', 'enum': numbers}
        properties['other_sweep'] = _object({
            'examined_regions': _array(deepcopy(region_number)), 'summary': _string(),
            'findings': _array(_object({
                'regions': _array(deepcopy(region_number)),
                'decision': _string(('missed_primary', 'secondary', 'uncertain', 'ignored')),
                'issue_ids': _array(_string()), 'evidence': _string(),
            })),
        })
    properties.update({
        'issues': _array(issue),
        'programs': _array(_object({'program_json': _string()})),
        'prior_issue_reviews': _array(_object({'review_json': _string()})),
    })
    return _object(properties)


def _validate(value, schema, path):
    """Validate only the small schema subset emitted above, without dependencies."""
    kind = schema['type']
    if kind == 'object':
        if not isinstance(value, dict):
            raise ValueError(f'{path}: expected object')
        expected = set(schema['properties'])
        if set(value) != expected:
            raise ValueError(f'{path}: missing or unknown object fields')
        for key, child in schema['properties'].items():
            _validate(value[key], child, f'{path}.{key}')
    elif kind == 'array':
        if not isinstance(value, list):
            raise ValueError(f'{path}: expected array')
        for index, item in enumerate(value):
            _validate(item, schema['items'], f'{path}[{index}]')
    elif kind == 'string':
        if not isinstance(value, str):
            raise ValueError(f'{path}: expected string')
    elif kind == 'integer':
        if type(value) is not int:
            raise ValueError(f'{path}: expected integer')
    else:
        raise ValueError(f'{path}: unsupported schema type {kind}')
    if 'enum' in schema and value not in schema['enum']:
        raise ValueError(f'{path}: value outside enum')


def _reject_constant(value):
    raise ValueError('non-JSON numeric constant: ' + value)


def _decode_items(items, field, key, rejections):
    decoded = []
    for index, item in enumerate(items):
        try:
            _validate(item, _object({key: _string()}), f'{field}[{index}]')
            value = json.loads(item[key], parse_constant=_reject_constant)
            if not isinstance(value, dict):
                raise ValueError('decoded item must be a JSON object')
            decoded.append(value)
        except (ValueError, TypeError, RecursionError) as exc:
            rejections.append({'field': field, 'index': index, 'error': str(exc)})
    return decoded


def decode_envelope(payload, regions, categories=DEFAULT_CATEGORIES):
    """Decode exact JSON strings and restore v3 category-sweep ordering.

    Presence of either inspection property selects the full envelope; absence
    of both selects review-only. The caller must enforce whether its current
    turn permits review-only and still run v3's coverage and semantic audits.
    Malformed program/review items are rejected individually. Other malformed
    envelope fields fail the whole decode rather than fabricating observations.
    """
    if not isinstance(payload, dict):
        raise ValueError('envelope: expected object')
    _, categories = _identities(regions, categories)
    review_only = not {'category_checks', 'other_sweep'} & payload.keys()
    schema = build_schema(regions, categories, review_only=review_only)
    if set(payload) != set(schema['properties']):
        raise ValueError('envelope: missing or unknown object fields')
    for key, child in schema['properties'].items():
        if key in ('programs', 'prior_issue_reviews'):
            if not isinstance(payload[key], list):
                raise ValueError(f'{key}: expected array')
        else:
            _validate(payload[key], child, key)
    rejections = []
    out = {
        'issues': deepcopy(payload['issues']),
        'programs': _decode_items(payload['programs'], 'programs', 'program_json', rejections),
        'prior_issue_reviews': _decode_items(payload['prior_issue_reviews'],
                                            'prior_issue_reviews', 'review_json', rejections),
        '_decode_rejections': rejections,
    }
    if not review_only:
        sweeps = []
        for category in categories:
            records = []
            for region in regions:
                row = deepcopy(payload['category_checks'][category][str(region['region'])])
                # Keep required audit fields even when empty: v3 must reject
                # missing evidence instead of receiving a substituted sentence.
                optional = {
                    'candidate_check': category not in ('E', 'F'),
                    'applicability_reason': row['state'] != 'not_applicable',
                    'svg_observation': region['pass'] != 1,
                }
                for key, removable in optional.items():
                    if removable and row[key] == '':
                        del row[key]
                records.append({'region': region['region'], **row})
            sweeps.append({'category': category, 'records': records})
        out['category_sweeps'] = sweeps
        out['other_sweep'] = deepcopy(payload['other_sweep'])
    return out
