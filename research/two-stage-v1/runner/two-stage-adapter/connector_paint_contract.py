"""Pure Bv3 provenance and residual lifecycle contract; no rendering or native imports.

Host callbacks compute full evidence only for host-derived allowlisted snapshots.
No function judges semantic truth, creates native issues, or awards repair credit.
"""
from copy import deepcopy
from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import struct
import zlib

# Exact reviewed schema definitions, embedded to avoid a mutable runtime spec dependency.
SCHEMAS = {'endpoint': {'type': 'object',
              'additionalProperties': False,
              'required': ['revision', 'evidence_hashes'],
              'properties': {'revision': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                             'evidence_hashes': {'type': 'object',
                                                 'additionalProperties': {'type': 'string',
                                                                          'pattern': '^[0-9a-f]{64}$'}}}},
 'artifact': {'type': 'object',
              'additionalProperties': False,
              'required': ['path', 'sha256'],
              'properties': {'path': {'type': 'string', 'minLength': 1},
                             'sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}}},
 'visual_evidence': {'type': 'object',
                     'additionalProperties': False,
                     'required': ['text', 'artifact_id', 'sha256', 'region_xywh'],
                     'properties': {'text': {'type': 'string', 'minLength': 1},
                                    'artifact_id': {'type': 'string', 'minLength': 1},
                                    'sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                    'region_xywh': {'type': 'array',
                                                    'minItems': 4,
                                                    'maxItems': 4,
                                                    'items': {'type': 'integer', 'minimum': 0}}}},
 'new_concern': {'type': 'object',
                 'additionalProperties': False,
                 'required': ['concern_id',
                              'concern_text',
                              'source_obligation',
                              'source_evidence',
                              'before_evidence',
                              'current_evidence',
                              'why_unbound'],
                 'properties': {'concern_id': {'type': 'string', 'minLength': 1},
                                'concern_text': {'type': 'string', 'minLength': 1},
                                'source_obligation': {'type': 'string', 'minLength': 1},
                                'source_evidence': {'$ref': '#/$defs/visual_evidence'},
                                'before_evidence': {'$ref': '#/$defs/visual_evidence'},
                                'current_evidence': {'$ref': '#/$defs/visual_evidence'},
                                'why_unbound': {'type': 'string', 'minLength': 1}}},
 'origin': {'type': 'object',
            'additionalProperties': False,
            'required': ['run_relative_report_path',
                         'raw_sha256',
                         'json_pointer',
                         'entry_sha256',
                         'before_locator'],
            'properties': {'run_relative_report_path': {'type': 'string', 'minLength': 1},
                           'raw_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                           'json_pointer': {'type': 'string', 'minLength': 1},
                           'entry_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                           'before_locator': {'$ref': '#/$defs/before_locator'}}},
 'concern_record': {'type': 'object',
                    'additionalProperties': False,
                    'required': ['concern',
                                 'origin',
                                 'source_sha256',
                                 'before',
                                 'observed',
                                 'observed_round',
                                 'provenance',
                                 'current_edit_authority'],
                    'properties': {'concern': {'$ref': '#/$defs/new_concern'},
                                   'origin': {'$ref': '#/$defs/origin'},
                                   'source_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                   'before': {'$ref': '#/$defs/endpoint'},
                                   'observed': {'$ref': '#/$defs/endpoint'},
                                   'observed_round': {'type': 'integer', 'minimum': 1, 'maximum': 3},
                                   'provenance': {'enum': ['retained_checkpoint', 'rejected_candidate']},
                                   'current_edit_authority': {'const': False}}},
 'concern_review': {'type': 'object',
                    'additionalProperties': False,
                    'required': ['concern_id',
                                 'decision',
                                 'source_evidence',
                                 'current_evidence',
                                 'reason',
                                 'native_issue_id'],
                    'properties': {'concern_id': {'type': 'string', 'minLength': 1},
                                   'decision': {'enum': ['defer', 'dismiss_current', 'transfer_to_native']},
                                   'source_evidence': {'$ref': '#/$defs/visual_evidence'},
                                   'current_evidence': {'$ref': '#/$defs/visual_evidence'},
                                   'reason': {'type': 'string', 'minLength': 1},
                                   'native_issue_id': {'anyOf': [{'type': 'string', 'minLength': 1},
                                                                 {'type': 'null'}]}}},
 'candidate_binding': {'type': 'object',
                       'additionalProperties': False,
                       'required': ['mode',
                                    'packet_sha256',
                                    'manifest_sha256',
                                    'policy_sha256',
                                    'producer_sha256'],
                       'properties': {'mode': {'const': 'connector-paint-global-v2'},
                                      'packet_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                      'manifest_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                      'policy_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                      'producer_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}}},
 'acknowledgement': {'type': 'object',
                     'additionalProperties': False,
                     'required': ['mode',
                                  'packet_sha256',
                                  'manifest_sha256',
                                  'policy_sha256',
                                  'producer_sha256',
                                  'candidate_receipt_sha256',
                                  'source_sha256',
                                  'before',
                                  'candidate',
                                  'field_status',
                                  'use'],
                     'properties': {'mode': {'const': 'connector-paint-global-v2'},
                                    'packet_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                    'manifest_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                    'policy_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                    'producer_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                    'candidate_receipt_sha256': {'type': 'string',
                                                                 'pattern': '^[0-9a-f]{64}$'},
                                    'source_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                    'before': {'$ref': '#/$defs/endpoint'},
                                    'candidate': {'$ref': '#/$defs/endpoint'},
                                    'field_status': {'enum': ['field_available', 'field_unavailable']},
                                    'use': {'const': 'attention_hint_only'}}},
 'cell': {'type': 'object',
          'additionalProperties': False,
          'required': ['cell', 'region_xywh', 'counts'],
          'properties': {'cell': {'enum': ['NW', 'NE', 'SW', 'SE']},
                         'region_xywh': {'type': 'array',
                                         'minItems': 4,
                                         'maxItems': 4,
                                         'items': {'type': 'integer', 'minimum': 0}},
                         'counts': {'anyOf': [{'type': 'object',
                                               'additionalProperties': False,
                                               'required': ['before_nonzero',
                                                            'candidate_nonzero',
                                                            'lost',
                                                            'gained',
                                                            'altered',
                                                            'changed'],
                                               'properties': {'before_nonzero': {'type': 'integer',
                                                                                 'minimum': 0},
                                                              'candidate_nonzero': {'type': 'integer',
                                                                                    'minimum': 0},
                                                              'lost': {'type': 'integer', 'minimum': 0},
                                                              'gained': {'type': 'integer', 'minimum': 0},
                                                              'altered': {'type': 'integer', 'minimum': 0},
                                                              'changed': {'type': 'integer', 'minimum': 0}}},
                                              {'type': 'null'}]}}},
 'packet': {'type': 'object',
            'additionalProperties': False,
            'required': ['schema_version',
                         'mode',
                         'policy_sha256',
                         'producer_sha256',
                         'producer_version',
                         'metric_version',
                         'manifest_sha256',
                         'source_sha256',
                         'before',
                         'candidate',
                         'field_status',
                         'unavailable_reason',
                         'cells',
                         'audit',
                         'limitations',
                         'before_locator'],
            'properties': {'schema_version': {'const': 'connector-paint-packet-v2'},
                           'mode': {'const': 'connector-paint-global-v2'},
                           'policy_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                           'producer_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                           'producer_version': {'type': 'string', 'minLength': 1},
                           'metric_version': {'type': 'string', 'minLength': 1},
                           'manifest_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                           'source_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                           'before': {'$ref': '#/$defs/endpoint'},
                           'candidate': {'$ref': '#/$defs/endpoint'},
                           'field_status': {'enum': ['field_available', 'field_unavailable']},
                           'unavailable_reason': {'anyOf': [{'type': 'string', 'minLength': 1},
                                                            {'type': 'null'}]},
                           'cells': {'type': 'array',
                                     'minItems': 4,
                                     'maxItems': 4,
                                     'items': {'$ref': '#/$defs/cell'}},
                           'audit': {'anyOf': [{'$ref': '#/$defs/artifact'}, {'type': 'null'}]},
                           'limitations': {'type': 'array', 'items': {'type': 'string', 'minLength': 1}},
                           'before_locator': {'$ref': '#/$defs/before_locator'}}},
 'policy': {'type': 'object',
            'additionalProperties': False,
            'required': ['schema_version',
                         'mode',
                         'approved_producer_version',
                         'producer_sha256',
                         'contract_sha256'],
            'properties': {'schema_version': {'const': 'connector-paint-policy-v2'},
                           'mode': {'const': 'connector-paint-global-v2'},
                           'approved_producer_version': {'type': 'string', 'minLength': 1},
                           'producer_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                           'contract_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'}}},
 'manifest': {'type': 'object',
              'additionalProperties': False,
              'required': ['schema_version', 'status', 'intent_sha256', 'artifacts'],
              'properties': {'schema_version': {'const': 'connector-paint-manifest-v2'},
                             'status': {'const': 'complete'},
                             'intent_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                             'artifacts': {'type': 'array', 'items': {'$ref': '#/$defs/artifact'}}}},
 'concern_receipt': {'type': 'object',
                     'additionalProperties': False,
                     'required': ['record',
                                  'review',
                                  'review_raw_sha256',
                                  'reviewed_revision',
                                  'repair_credit'],
                     'properties': {'record': {'$ref': '#/$defs/concern_record'},
                                    'review': {'$ref': '#/$defs/concern_review'},
                                    'review_raw_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                    'reviewed_revision': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                    'repair_credit': {'const': False}}},
 'full_evidence': {'type': 'object',
                   'additionalProperties': False,
                   'required': ['revision', 'evidence_hashes', 'pair_hashes', 'required_regions'],
                   'properties': {'revision': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                  'evidence_hashes': {'type': 'object',
                                                      'additionalProperties': {'type': 'string',
                                                                               'pattern': '^[0-9a-f]{64}$'}},
                                  'pair_hashes': {'type': 'object',
                                                  'additionalProperties': {'type': 'string',
                                                                           'pattern': '^[0-9a-f]{64}$'}},
                                  'required_regions': {'type': 'array',
                                                       'items': {'type': 'string', 'minLength': 1},
                                                       'uniqueItems': True}}},
 'before_locator': {'type': 'object',
                    'additionalProperties': False,
                    'required': ['kind',
                                 'run_id',
                                 'relative_path',
                                 'origin_round',
                                 'evidence',
                                 'acceptance_receipt_path',
                                 'acceptance_receipt_sha256'],
                    'properties': {'kind': {'enum': ['frozen_initial', 'accepted_candidate']},
                                   'run_id': {'enum': ['run1', 'run2', 'run3']},
                                   'relative_path': {'type': 'string', 'minLength': 1},
                                   'origin_round': {'type': 'integer', 'minimum': 0, 'maximum': 2},
                                   'evidence': {'$ref': '#/$defs/full_evidence'},
                                   'acceptance_receipt_path': {'anyOf': [{'type': 'string', 'minLength': 1},
                                                                         {'type': 'null'}]},
                                   'acceptance_receipt_sha256': {'anyOf': [{'type': 'string',
                                                                            'pattern': '^[0-9a-f]{64}$'},
                                                                           {'type': 'null'}]}}},
 'registration_intent': {'type': 'object',
                         'additionalProperties': False,
                         'required': ['schema_version',
                                      'mode',
                                      'run_id',
                                      'round_number',
                                      'policy_sha256',
                                      'producer_sha256',
                                      'source_sha256',
                                      'before',
                                      'candidate',
                                      'before_locator'],
                         'properties': {'schema_version': {'const': 'connector-paint-intent-v2'},
                                        'mode': {'const': 'connector-paint-global-v2'},
                                        'run_id': {'enum': ['run1', 'run2', 'run3']},
                                        'round_number': {'type': 'integer', 'minimum': 1, 'maximum': 3},
                                        'policy_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                        'producer_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                        'source_sha256': {'type': 'string', 'pattern': '^[0-9a-f]{64}$'},
                                        'before': {'$ref': '#/$defs/endpoint'},
                                        'candidate': {'$ref': '#/$defs/endpoint'},
                                        'before_locator': {'$ref': '#/$defs/before_locator'}}}}

MODE = 'connector-paint-global-v2'
FULL_KEYS = ('revision', 'evidence_hashes', 'pair_hashes', 'required_regions')
RASTER_KEYS = {'original_png', 'current_png', 'current_svg', 'public_svg', 'bounds', 'pairs', 'pack_pixels', 'pack_metadata', 'sam_catalog'}
CELLS = ('NW', 'NE', 'SW', 'SE')

class ContractError(ValueError):
    """Integrity/provenance failure; never a semantic verdict or legacy fallback."""


def require(condition, message):
    if not condition:
        raise ContractError(message)


def sha256(data):
    require(type(data) is bytes, 'hash input must be raw bytes')
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('utf-8')
    except (ValueError, TypeError, UnicodeError) as exc:
        raise ContractError('invalid canonical JSON') from exc


def parse_raw(data):
    """Parse exact frozen UTF-8 bytes, rejecting ambiguous/nonfinite JSON."""
    require(type(data) is bytes, 'raw JSON must be bytes')
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate JSON key: ' + key)
            result[key] = value
        return result
    def constant(value):
        raise ContractError('nonfinite JSON number: ' + value)
    def inspect(value):
        if type(value) is float:
            require(math.isfinite(value), 'nonfinite JSON number')
        elif type(value) is str:
            try:
                value.encode('utf-8')
            except UnicodeError as exc:
                raise ContractError('invalid Unicode scalar') from exc
        elif type(value) is dict:
            for key, item in value.items(): inspect(key); inspect(item)
        elif type(value) is list:
            for item in value: inspect(item)
    try:
        result = json.loads(data.decode('utf-8', errors='strict'), object_pairs_hook=pairs, parse_constant=constant)
        inspect(result)
        return result
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise ContractError('invalid UTF-8/JSON raw report') from exc


def _schema(schema, value, where):
    if '$ref' in schema:
        return _schema(SCHEMAS[schema['$ref'].split('/')[-1]], value, where)
    if 'anyOf' in schema:
        for choice in schema['anyOf']:
            try:
                _schema(choice, value, where)
                return
            except ContractError:
                pass
        raise ContractError(where + ': no allowed shape')
    if 'const' in schema:
        constant = schema['const']
        require(type(value) is type(constant) and value == constant, where + ': incorrect constant')
    if 'enum' in schema:
        require(any(type(value) is type(item) and value == item for item in schema['enum']), where + ': unknown value')
    kind = schema.get('type')
    if kind == 'object':
        require(type(value) is dict and all(type(key) is str and key.strip() for key in value), where + ': object required')
        require(set(schema.get('required', [])).issubset(value), where + ': missing keys')
        props = schema.get('properties', {})
        extra = schema.get('additionalProperties', True)
        if extra is False:
            require(set(value).issubset(props), where + ': unknown keys')
        for key, item in value.items():
            if key in props: _schema(props[key], item, where + '.' + key)
            elif type(extra) is dict: _schema(extra, item, where + '.' + key)
    elif kind == 'array':
        require(type(value) is list, where + ': array required')
        require(len(value) >= schema.get('minItems', 0) and len(value) <= schema.get('maxItems', len(value)), where + ': array length')
        if schema.get('uniqueItems'):
            require(len({canonical(item) for item in value}) == len(value), where + ': duplicate item')
        for item in value: _schema(schema['items'], item, where + '[]')
    elif kind == 'string':
        require(type(value) is str and bool(value.strip()), where + ': nonblank string required')
        try: value.encode('utf-8')
        except UnicodeError as exc: raise ContractError(where + ': invalid Unicode') from exc
        require(len(value) >= schema.get('minLength', 0), where + ': short string')
        if 'pattern' in schema: require(re.fullmatch(schema['pattern'], value) is not None, where + ': invalid hash/string')
    elif kind == 'integer':
        require(type(value) is int, where + ': integer required (no bool/coercion)')
        require(value >= schema.get('minimum', value) and value <= schema.get('maximum', value), where + ': integer bounds')
    elif kind == 'null':
        require(value is None, where + ': null required')


def validate_schema(name, value):
    require(name in SCHEMAS, 'unknown schema')
    _schema(SCHEMAS[name], value, name)


def endpoint(full):
    validate_full(full)
    return {key: deepcopy(full[key]) for key in ('revision', 'evidence_hashes')}


def validate_full(full):
    validate_schema('full_evidence', full)
    require(RASTER_KEYS.issubset(full['evidence_hashes']), 'incomplete full evidence hashes')
    require(full['revision'] == full['evidence_hashes']['current_svg'], 'revision/current SVG mismatch')


def full_from_state(state):
    require(type(state) is dict and all(key in state for key in FULL_KEYS), 'missing state full evidence')
    full = {key: deepcopy(state[key]) for key in FULL_KEYS}
    validate_full(full)
    return full


def artifact_basename(name):
    require(type(name) is str and bool(name.strip()) and name not in ('.', '..', 'packet.json', 'manifest.json') and '/' not in name and '\\' not in name and '\x00' not in name and PurePosixPath(name).name == name, 'observer artifact must be a nonreserved basename')
    return name


@dataclass(frozen=True)
class ApprovedVersions:
    producer_sha256: str
    producer_version: str
    contract_sha256: str
    metric_version: str


@dataclass(frozen=True)
class Raster:
    sha256: str
    width: int
    height: int


@dataclass(frozen=True)
class Registration:
    """Host-created immutable serialized bindings, never accepted from model JSON."""
    run_id: str
    round_number: int
    _before: bytes
    _candidate: bytes
    _locator: bytes

    @property
    def before(self): return parse_raw(self._before)
    @property
    def candidate(self): return parse_raw(self._candidate)
    @property
    def before_locator(self): return parse_raw(self._locator)


class Host:
    """Read-only filesystem resolver for a trusted root and data-only callback.

    evidence_reader(path) must compute the existing full evidence tuple from the
    supplied host path. It must not return model-selected paths or render data.
    Files must be quiescent while validation runs; this is not a hostile-writer
    sandbox. The callback's semantic completeness is a caller responsibility.
    """
    def __init__(self, root, run_id, frozen_initial, evidence_reader):
        root = Path(root)
        require(not root.is_symlink(), 'workflow root is symlink')
        self.root = root.resolve(strict=True)
        require(run_id in ('run1', 'run2', 'run3'), 'invalid run')
        validate_full(frozen_initial)
        require(callable(evidence_reader), 'full evidence callback required')
        self.run_id = run_id
        self._frozen_initial = canonical(frozen_initial)
        self.evidence_reader = evidence_reader

    @property
    def frozen_initial(self): return parse_raw(self._frozen_initial)

    def round(self, number):
        require(type(number) is int and 1 <= number <= 3, 'round must be exactly 1..3')
        return f'runs/{self.run_id}/round-{number}'

    def path(self, relative, *, exists=True, tree=False):
        require(type(relative) is str and relative and '\\' not in relative and '\x00' not in relative, 'invalid host path')
        parts = PurePosixPath(relative).parts
        require(not PurePosixPath(relative).is_absolute() and all(part not in ('.', '..') for part in parts) and str(PurePosixPath(relative)) == relative, 'noncanonical or escaping host path')
        path = self.root
        for part in parts:
            path = path / part
            require(not path.is_symlink(), 'symlink in host path')
        require(path.resolve().is_relative_to(self.root), 'host path escapes root')
        require(not exists or path.exists(), 'missing host artifact: ' + relative)
        if tree and path.exists():
            require(path.is_dir(), 'snapshot must be directory')
            for child in path.rglob('*'):
                require(not child.is_symlink(), 'symlink in snapshot')
                require(child.is_dir() or stat.S_ISREG(child.stat().st_mode), 'nonregular snapshot artifact')
        elif exists:
            require(path.is_file() and stat.S_ISREG(path.stat().st_mode), 'regular artifact required')
        return path

    def read(self, relative):
        try: return self.path(relative).read_bytes()
        except OSError as exc: raise ContractError('missing/unreadable host artifact: ' + relative) from exc

    def snapshot(self, relative):
        path = self.path(relative, tree=True)
        try:
            result = self.evidence_reader(path)
            validate_full(result)
            require(result['evidence_hashes']['original_png'] == sha256(self.read(relative + '/original.png')), 'actual source raster mismatch')
            require(result['evidence_hashes']['current_png'] == sha256(self.read(relative + '/current.png')), 'actual current raster mismatch')
            require(result['evidence_hashes']['current_svg'] == sha256(self.read(relative + '/current.svg')), 'actual SVG revision mismatch')
            return deepcopy(result)
        except OSError as exc:
            raise ContractError('full evidence unavailable') from exc

    def initial(self):
        result = self.snapshot('inputs/initial')
        require(result == self.frozen_initial, 'frozen initial full evidence changed')
        return result

    def _candidate(self, number, expected):
        base = self.round(number)
        actual = self.snapshot(base + '/candidate')
        require(actual == expected, 'candidate full evidence mismatch')
        receipt = parse_raw(self.read(base + '/candidate.json'))
        require(type(receipt) is dict and receipt.get('candidate_folder') == str(self.root / base / 'candidate'), 'candidate receipt path mismatch')
        require(full_from_state(receipt) == actual, 'candidate receipt full evidence mismatch')
        return actual

    def _acceptance(self, number, expected, expected_sha=None):
        raw = self.read(self.round(number) + '/acceptance.json')
        if expected_sha is not None: require(sha256(raw) == expected_sha, 'immutable acceptance receipt SHA changed')
        receipt = parse_raw(raw)
        require(type(receipt) is dict and receipt.get('rollback') is False, 'before candidate is not accepted rollback:false')
        require(full_from_state(receipt.get('state')) == expected, 'acceptance state full evidence mismatch')
        self._candidate(number, expected)
        return sha256(raw)

    def freeze_before(self, number, actual_before):
        self.round(number)
        validate_full(actual_before)
        initial = self.initial()
        require(actual_before['evidence_hashes']['original_png'] == initial['evidence_hashes']['original_png'], 'before source differs from frozen original raster')
        if actual_before == initial:
            return dict(kind='frozen_initial', run_id=self.run_id, relative_path='inputs/initial', origin_round=0, evidence=deepcopy(initial), acceptance_receipt_path=None, acceptance_receipt_sha256=None)
        for earlier in range(1, number):
            base = self.round(earlier)
            acceptance_path = self.path(base + '/acceptance.json', exists=False)
            if not acceptance_path.exists(): continue
            receipt = parse_raw(self.read(base + '/acceptance.json'))
            if type(receipt) is not dict or receipt.get('rollback') is not False: continue
            if full_from_state(receipt.get('state')) != actual_before: continue
            accepted_sha = self._acceptance(earlier, actual_before)
            return dict(kind='accepted_candidate', run_id=self.run_id, relative_path=base + '/candidate', origin_round=earlier, evidence=deepcopy(actual_before), acceptance_receipt_path=base + '/acceptance.json', acceptance_receipt_sha256=accepted_sha)
        raise ContractError('no eligible immutable actual-before locator')

    def resolve_before(self, locator, observation_round):
        self.round(observation_round)
        validate_schema('before_locator', locator)
        require(locator['run_id'] == self.run_id, 'foreign before locator run')
        validate_full(locator['evidence'])
        initial = self.initial()
        if locator['kind'] == 'frozen_initial':
            require(locator['relative_path'] == 'inputs/initial' and locator['origin_round'] == 0 and locator['acceptance_receipt_path'] is None and locator['acceptance_receipt_sha256'] is None, 'invalid frozen-initial locator')
            require(locator['evidence'] == initial, 'frozen initial locator evidence mismatch')
            return deepcopy(initial)
        number = locator['origin_round']
        require(1 <= number < observation_round and number <= 2, 'before origin round not prior')
        base = self.round(number)
        require(locator['relative_path'] == base + '/candidate' and locator['acceptance_receipt_path'] == base + '/acceptance.json' and locator['acceptance_receipt_sha256'] is not None, 'invalid accepted-candidate locator paths/hash')
        require(locator['evidence']['evidence_hashes']['original_png'] == initial['evidence_hashes']['original_png'], 'locator source mismatch')
        self._acceptance(number, locator['evidence'], locator['acceptance_receipt_sha256'])
        return deepcopy(locator['evidence'])

    def registration(self, number, actual_before, candidate):
        self.round(number)
        validate_full(candidate)
        locator = self.freeze_before(number, actual_before)
        actual = self.snapshot(self.round(number) + '/candidate')
        require(actual == candidate, 'registration candidate full evidence mismatch')
        require(candidate['evidence_hashes']['original_png'] == self.frozen_initial['evidence_hashes']['original_png'], 'candidate original source mismatch')
        return Registration(self.run_id, number, canonical(actual_before), canonical(candidate), canonical(locator))

    def validate_registration(self, reg):
        require(type(reg) is Registration and reg.run_id == self.run_id, 'host registration required')
        before = self.resolve_before(reg.before_locator, reg.round_number)
        require(before == reg.before, 'registration before locator mismatch')
        require(self.snapshot(self.round(reg.round_number) + '/candidate') == reg.candidate, 'registered candidate evidence changed')
        require(reg.candidate['evidence_hashes']['original_png'] == self.frozen_initial['evidence_hashes']['original_png'], 'registration source mismatch')

    def raster(self, relative, expected_hash):
        data = self.read(relative)
        require(sha256(data) == expected_hash, 'raster raw hash mismatch')
        require(len(data) >= 33 and data[:8] == b'\x89PNG\r\n\x1a\n' and data[8:16] == b'\x00\x00\x00\rIHDR', 'bound raster is not PNG IHDR')
        require(zlib.crc32(data[12:29]) == struct.unpack('>I', data[29:33])[0], 'bound raster IHDR checksum')
        width, height = struct.unpack('>II', data[16:24])
        require(width > 0 and height > 0, 'invalid bound raster dimensions')
        return Raster(expected_hash, width, height)

    def _scope(self, locator, number, before, candidate):
        return {
            'original_png': self.raster('inputs/initial/original.png', self.frozen_initial['evidence_hashes']['original_png']),
            'before_png': self.raster(locator['relative_path'] + '/current.png', before['evidence_hashes']['current_png']),
            'candidate_png': self.raster(self.round(number) + '/candidate/current.png', candidate['evidence_hashes']['current_png']),
        }

    def raster_scope(self, reg):
        self.validate_registration(reg)
        return self._scope(reg.before_locator, reg.round_number, reg.before, reg.candidate)

    def report(self, number):
        base = self.round(number) + '/verifier'
        raw = self.read(base + '/raw.json')
        receipt = parse_raw(self.read(base + '/receipt.json'))
        require(type(receipt) is dict and receipt.get('sha256') == sha256(raw), 'immutable raw report receipt mismatch')
        report = parse_raw(raw)
        require(type(report) is dict, 'report object required')
        return report, raw

    def resolve_origin(self, record):
        validate_schema('concern_record', record)
        number = record['observed_round']
        origin = record['origin']
        require(origin['run_relative_report_path'] == f'round-{number}/verifier/raw.json', 'origin report outside same-run fixed allowlist')
        report, raw = self.report(number)
        require(sha256(raw) == origin['raw_sha256'], 'origin raw SHA mismatch')
        match = re.fullmatch(r'/connector_visual_concerns/(0|[1-9][0-9]*)', origin['json_pointer'])
        require(match is not None, 'invalid concern origin JSON pointer')
        rows = report.get('connector_visual_concerns')
        index = int(match[1])
        require(type(rows) is list and index < len(rows), 'origin pointer entry missing')
        require(rows[index] == record['concern'] and sha256(canonical(rows[index])) == origin['entry_sha256'], 'origin pointer text/entry SHA mismatch')
        before = self.resolve_before(origin['before_locator'], number)
        observed = self._candidate(number, self.snapshot(self.round(number) + '/candidate'))
        self.historical_bundle(number, report, origin['before_locator'])
        require(endpoint(before) == record['before'] and endpoint(observed) == record['observed'], 'origin historical endpoint mismatch')
        source_sha = self.frozen_initial['evidence_hashes']['original_png']
        require(record['source_sha256'] == source_sha and before['evidence_hashes']['original_png'] == source_sha and observed['evidence_hashes']['original_png'] == source_sha, 'origin exact source SHA mismatch')
        scope = self._scope(origin['before_locator'], number, before, observed)
        validate_new_concern(record['concern'], scope)
        return deepcopy(record)

    def historical_bundle(self, number, report, locator=None):
        """Revalidate a report's original dispatch/packet/evidence chain."""
        packet = parse_raw(self.read(self.round(number) + '/connector-paint/packet.json'))
        validate_schema('packet', packet)
        if locator is None: locator = packet['before_locator']
        before = self.resolve_before(locator, number)
        observed = self.snapshot(self.round(number) + '/candidate')
        historical = Registration(self.run_id, number, canonical(before), canonical(observed), canonical(locator))
        policy = observer_mode(self, number)
        require(policy is not None, 'origin enabled policy missing')
        versions = ApprovedVersions(policy['producer_sha256'], policy['approved_producer_version'], policy['contract_sha256'], packet['metric_version'])
        ack = report.get('connector_paint_ack')
        validate_schema('acknowledgement', ack)
        bundle = validate_bundle(self, historical, versions, ack['candidate_receipt_sha256'])
        validate_ack(ack, bundle)
        return bundle

    def validate_state(self, state):
        require(type(state) is dict, 'state object required')
        concerns = state.get('connector_visual_concerns', [])
        receipts = state.get('connector_concern_receipts', [])
        require(type(concerns) is list and type(receipts) is list, 'residual state arrays required')
        ids = []
        for record in concerns:
            self.resolve_origin(record)
            ids.append(record['concern']['concern_id'])
        for receipt in receipts:
            validate_schema('concern_receipt', receipt)
            record = self.resolve_origin(receipt['record'])
            review = receipt['review']
            require(review['concern_id'] == record['concern']['concern_id'] and review['decision'] in ('dismiss_current', 'transfer_to_native'), 'invalid accepted concern receipt identity/decision')
            matches = []
            for number in range(record['observed_round'], 4):
                path = self.path(self.round(number) + '/verifier/raw.json', exists=False)
                if path.exists() and sha256(self.read(self.round(number) + '/verifier/raw.json')) == receipt['review_raw_sha256']:
                    report, _ = self.report(number)
                    self.historical_bundle(number, report)
                    rows = report.get('connector_concern_reviews', [])
                    require(type(rows) is list and sum(row == review for row in rows) == 1, 'accepted concern receipt review text mismatch')
                    observed = self.snapshot(self.round(number) + '/candidate')
                    require(observed['revision'] == receipt['reviewed_revision'], 'receipt reviewed revision mismatch')
                    scope = {'original_png': self.raster('inputs/initial/original.png', self.frozen_initial['evidence_hashes']['original_png']), 'candidate_png': self.raster(self.round(number) + '/candidate/current.png', observed['evidence_hashes']['current_png'])}
                    validate_review(review, scope, native_survivors=None)
                    matches.append(number)
            require(len(matches) == 1, 'accepted concern receipt raw review not uniquely resolvable')
            ids.append(record['concern']['concern_id'])
        require(len(ids) == len(set(ids)), 'duplicate active/historical residual identity')
        native = native_ids(state)
        require(not set(ids) & native, 'residual/native identity collision')
        return set(ids)


def observer_mode(host, number, *, binding=None, report=None):
    """Return enabled policy, or legacy only if *all* observer traces are absent."""
    base = host.round(number)
    policy = host.path('inputs/connector-paint-policy.json', exists=False)
    traces = [host.path(base + '/connector-paint-start.json', exists=False), host.path(base + '/connector-paint', exists=False)]
    active = binding is not None or (type(report) is dict and any(key in report for key in ('connector_paint_ack', 'connector_visual_concerns', 'connector_concern_reviews')))
    # Stray candidate/report activation cannot hide behind an omitted argument.
    # Only the fixed same-run/round paths are inspected.
    for relative, keys in ((base + '/candidate.json', ('connector_paint',)), (base + '/verifier/raw.json', ('connector_paint_ack', 'connector_visual_concerns', 'connector_concern_reviews'))):
        path = host.path(relative, exists=False)
        if path.exists():
            value = parse_raw(host.read(relative))
            active = active or (type(value) is dict and any(key in value for key in keys))
    import assignment_policy
    if assignment_policy.disabled(host.root):
        require(not active and not any(path.exists() for path in traces), 'disabled assignment has active connector artifacts')
        return None
    if not policy.exists():
        require(not active and not any(path.exists() for path in traces), 'absent policy with stray active observer artifacts')
        return None
    value = parse_raw(host.read('inputs/connector-paint-policy.json'))
    validate_schema('policy', value)
    return value


def cell_regions(width, height):
    require(type(width) is int and type(height) is int and width > 0 and height > 0, 'registered dimensions must be positive integers')
    x, y = width // 2, height // 2
    return [[0, 0, x, y], [x, 0, width-x, y], [0, y, x, height-y], [x, y, width-x, height-y]]


def validate_packet(packet, reg, versions, dimensions):
    validate_schema('packet', packet)
    require(type(reg) is Registration and type(versions) is ApprovedVersions, 'host bindings and approved versions required')
    require(packet['producer_sha256'] == versions.producer_sha256 and packet['producer_version'] == versions.producer_version and packet['metric_version'] == versions.metric_version, 'packet producer/metric mismatch')
    require(packet['before'] == endpoint(reg.before) and packet['candidate'] == endpoint(reg.candidate) and packet['before_locator'] == reg.before_locator, 'packet endpoint/locator mismatch')
    source = reg.before['evidence_hashes']['original_png']
    require(packet['source_sha256'] == source == reg.candidate['evidence_hashes']['original_png'], 'packet exact original source mismatch')
    regions = cell_regions(*dimensions)
    available = packet['field_status'] == 'field_available'
    require((packet['unavailable_reason'] is None and packet['audit'] is not None) if available else (packet['unavailable_reason'] is not None and packet['audit'] is None), 'available/unavailable audit or reason inconsistency')
    for cell, name, region in zip(packet['cells'], CELLS, regions):
        require(cell['cell'] == name and cell['region_xywh'] == region, 'four half-open row-major cells must cover registered raster exactly')
        counts = cell['counts']
        require((counts is not None) if available else (counts is None), 'available/unavailable counts inconsistency')
        if counts is not None:
            area = region[2] * region[3]
            require(all(value <= area for value in counts.values()), 'cell count exceeds pixel area')
            require(counts['changed'] == counts['lost'] + counts['gained'] + counts['altered'], 'changed count partition mismatch')
            require(counts['lost'] <= counts['before_nonzero'] and counts['gained'] <= counts['candidate_nonzero'] and counts['altered'] <= min(counts['before_nonzero']-counts['lost'], counts['candidate_nonzero']-counts['gained']), 'cell count contribution mismatch')
            require(counts['candidate_nonzero']-counts['before_nonzero'] == counts['gained']-counts['lost'], 'cell count nonzero balance mismatch')
    if packet['audit'] is not None: artifact_basename(packet['audit']['path'])


@dataclass(frozen=True)
class BoundPacket:
    registration: Registration
    versions: ApprovedVersions
    candidate_receipt_sha256: str
    _packet: bytes
    _binding: bytes

    @property
    def packet(self): return parse_raw(self._packet)
    @property
    def binding(self): return parse_raw(self._binding)

    def revalidate(self, host):
        current = validate_bundle(host, self.registration, self.versions, self.candidate_receipt_sha256)
        require(current._packet == self._packet and current._binding == self._binding, 'frozen observer bundle changed')
        return current


def validate_bundle(host, reg, versions, candidate_receipt_sha256):
    """Read fixed policy/intent/observer paths; validate dispatch-pinned receipt."""
    host.validate_registration(reg)
    validate_schema('artifact', {'path': 'producer', 'sha256': versions.producer_sha256})
    validate_schema('artifact', {'path': 'contract', 'sha256': versions.contract_sha256})
    base = host.round(reg.round_number)
    policy = observer_mode(host, reg.round_number)
    require(policy is not None, 'enabled packet requires policy')
    require(policy['producer_sha256'] == versions.producer_sha256 and policy['approved_producer_version'] == versions.producer_version and policy['contract_sha256'] == versions.contract_sha256, 'policy approved source/contract mismatch')
    policy_sha = sha256(host.read('inputs/connector-paint-policy.json'))
    intent_raw = host.read(base + '/connector-paint-start.json')
    intent = parse_raw(intent_raw)
    validate_schema('registration_intent', intent)
    expected_intent = dict(schema_version='connector-paint-intent-v2', mode=MODE, run_id=host.run_id, round_number=reg.round_number, policy_sha256=policy_sha, producer_sha256=versions.producer_sha256, source_sha256=host.frozen_initial['evidence_hashes']['original_png'], before=endpoint(reg.before), candidate=endpoint(reg.candidate), before_locator=reg.before_locator)
    require(intent == expected_intent, 'intent exact registration binding mismatch')
    directory = host.path(base + '/connector-paint', tree=True)
    manifest_raw = host.read(base + '/connector-paint/manifest.json')
    manifest = parse_raw(manifest_raw)
    validate_schema('manifest', manifest)
    require(manifest['intent_sha256'] == sha256(intent_raw), 'manifest intent SHA mismatch')
    artifacts = {}
    for artifact in manifest['artifacts']:
        name = artifact_basename(artifact['path'])
        require(name not in artifacts, 'duplicate manifest artifact')
        require(sha256(host.read(base + '/connector-paint/' + name)) == artifact['sha256'], 'observer artifact SHA mismatch')
        artifacts[name] = artifact['sha256']
    names = {path.name for path in directory.iterdir()}
    require(names == set(artifacts) | {'packet.json', 'manifest.json'} and all(path.is_file() for path in directory.iterdir()), 'manifest not complete exact observer inventory')
    packet_raw = host.read(base + '/connector-paint/packet.json')
    packet = parse_raw(packet_raw)
    scope = host.raster_scope(reg)
    dimensions = (scope['candidate_png'].width, scope['candidate_png'].height)
    validate_packet(packet, reg, versions, dimensions)
    require(packet['policy_sha256'] == policy_sha and packet['manifest_sha256'] == sha256(manifest_raw), 'packet policy/manifest SHA mismatch')
    if packet['field_status'] == 'field_available':
        require((scope['before_png'].width, scope['before_png'].height) == dimensions, 'available endpoint raster dimensions differ')
        audit = packet['audit']
        require(artifacts.get(audit['path']) == audit['sha256'], 'complete audit missing from manifest')
    candidate_raw = host.read(base + '/candidate.json')
    require(sha256(candidate_raw) == candidate_receipt_sha256, 'dispatch-pinned candidate receipt SHA mismatch')
    candidate = parse_raw(candidate_raw)
    host._candidate(reg.round_number, reg.candidate)
    require(candidate.get('before_revision') == reg.before['revision'] and candidate.get('before_evidence_hashes') == reg.before['evidence_hashes'], 'candidate receipt before binding mismatch')
    binding = candidate.get('connector_paint')
    validate_schema('candidate_binding', binding)
    require(binding == dict(mode=MODE, packet_sha256=sha256(packet_raw), manifest_sha256=sha256(manifest_raw), policy_sha256=policy_sha, producer_sha256=versions.producer_sha256), 'candidate observer hash binding mismatch')
    return BoundPacket(reg, versions, candidate_receipt_sha256, packet_raw, canonical(binding))


def validate_ack(ack, bundle):
    validate_schema('acknowledgement', ack)
    packet = bundle.packet
    expected = dict(**bundle.binding, candidate_receipt_sha256=bundle.candidate_receipt_sha256, source_sha256=packet['source_sha256'], before=packet['before'], candidate=packet['candidate'], field_status=packet['field_status'], use='attention_hint_only')
    require(ack == expected, 'acknowledgement stale/foreign/binding mismatch')


def validate_visual(evidence, expected_id, scope):
    validate_schema('visual_evidence', evidence)
    require(evidence['artifact_id'] == expected_id and expected_id in scope, 'visual evidence must name actual scoped raster')
    raster = scope[expected_id]
    require(evidence['sha256'] == raster.sha256, 'visual evidence raster SHA mismatch')
    x, y, width, height = evidence['region_xywh']
    require(width > 0 and height > 0 and x + width <= raster.width and y + height <= raster.height, 'visual region outside bound raster dimensions')


def validate_new_concern(concern, scope):
    validate_schema('new_concern', concern)
    require(concern['concern_id'] not in CELLS, 'cell identity cannot become concern identity')
    for field, ident in (('source_evidence', 'original_png'), ('before_evidence', 'before_png'), ('current_evidence', 'candidate_png')):
        validate_visual(concern[field], ident, scope)


def validate_review(review, scope, *, native_survivors):
    validate_schema('concern_review', review)
    validate_visual(review['source_evidence'], 'original_png', scope)
    validate_visual(review['current_evidence'], 'candidate_png', scope)
    if review['decision'] == 'transfer_to_native':
        require(review['native_issue_id'] is not None, 'transfer requires current native ID')
        if native_survivors is not None: require(review['native_issue_id'] in native_survivors, 'transfer target is not a surviving validated current native issue')
    else:
        require(review['native_issue_id'] is None, 'non-transfer native ID must be null')


def native_ids(state):
    result = set()
    historical = state.get('historical_finding_ids', [])
    require(type(historical) is list and all(type(item) is str and item.strip() for item in historical), 'invalid native history identities')
    result.update(historical)
    for field in ('required', 'uncertain', 'pending_observations', 'pending_observation_receipts'):
        rows = state.get(field, [])
        require(type(rows) is list, 'native identity namespace must be array')
        for row in rows:
            require(type(row) is dict and type(row.get('id')) is str and bool(row['id'].strip()), 'invalid native identity')
            result.add(row['id'])
    return result


def transition(host, bundle, state, *, rollback, native_survivors=frozenset(), native_reserved_ids=frozenset()):
    """Validate everything before a deep-copy commit of residual state only.

    native_survivors is trusted host output AFTER existing native validation,
    partitions/current bindings/new findings and pending triage. This helper
    neither validates native issues nor creates their targets/categories.
    native_reserved_ids includes every current/new/active/pending/historical ID.
    The caller derives rollback from its existing protected-regression contract.
    """
    require(type(rollback) is bool, 'rollback must be host bool')
    for items in (native_survivors, native_reserved_ids):
        require(type(items) in (set, frozenset) and all(type(item) is str and item.strip() for item in items), 'trusted native ID set required')
    bundle.revalidate(host)
    old_ids = host.validate_state(state)
    reserved_native = native_ids(state) | native_reserved_ids
    require(native_survivors.issubset(reserved_native), 'current survivors absent from native reservation namespace')
    require(not old_ids & reserved_native, 'existing residual/native identity collision')
    reg = bundle.registration
    report, report_raw = host.report(reg.round_number)
    require(not report.get('protected_regressions') or rollback, 'protected regression requires full rollback')
    validate_ack(report.get('connector_paint_ack'), bundle)
    concerns = state.get('connector_visual_concerns', [])
    reviews = report.get('connector_concern_reviews', [])
    rows = report.get('connector_visual_concerns', [])
    require(type(reviews) is list and type(rows) is list, 'concern/review arrays required')
    scope = host.raster_scope(reg)
    review_map = {}
    for review in reviews:
        validate_review(review, scope, native_survivors=native_survivors)
        ident = review['concern_id']
        require(ident not in review_map, 'duplicate concern review ID')
        review_map[ident] = review
    require(set(review_map) == {record['concern']['concern_id'] for record in concerns}, 'reviews must exactly partition existing residual concern IDs')
    reserved = old_ids | reserved_native
    for row in rows:
        validate_new_concern(row, scope)
        require(row['concern_id'] not in reserved, 'new concern identity collides with active/pending/historical/native/residual ID')
        reserved.add(row['concern_id'])
    # Commit starts only after ALL validation succeeds. Inputs remain unchanged.
    result = deepcopy(state)
    result.setdefault('connector_visual_concerns', [])
    result.setdefault('connector_concern_receipts', [])
    if not rollback:
        retained = []
        for record in concerns:
            review = review_map[record['concern']['concern_id']]
            if review['decision'] == 'defer': retained.append(deepcopy(record))
            else:
                result['connector_concern_receipts'].append(dict(record=deepcopy(record), review=deepcopy(review), review_raw_sha256=sha256(report_raw), reviewed_revision=reg.candidate['revision'], repair_credit=False))
        result['connector_visual_concerns'] = retained
    for index, row in enumerate(rows):
        record = dict(concern=deepcopy(row), origin=dict(run_relative_report_path=f'round-{reg.round_number}/verifier/raw.json', raw_sha256=sha256(report_raw), json_pointer=f'/connector_visual_concerns/{index}', entry_sha256=sha256(canonical(row)), before_locator=reg.before_locator), source_sha256=bundle.packet['source_sha256'], before=endpoint(reg.before), observed=endpoint(reg.candidate), observed_round=reg.round_number, provenance='rejected_candidate' if rollback else 'retained_checkpoint', current_edit_authority=False)
        validate_schema('concern_record', record)
        result['connector_visual_concerns'].append(record)
    return result


def status_suggestion(state, round_number):
    """Residual-only hint; caller retains native/pending/rollback priorities.

    Inconclusive at round three is terminal under the existing round limit.
    This returns no planner work, clean verdict, attempt, or repair credit.
    """
    require(type(round_number) is int and 1 <= round_number <= 3, 'round must be 1..3; no fourth attempt')
    return 'inconclusive' if state.get('connector_visual_concerns') else 'no_residual_blocker'
