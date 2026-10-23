"""Offline preregistration for the historical SAM × code-methods ablation.

This module reads and hashes local files. It cannot execute a cell or contact a
model or SAM service. The output is an input to a separately reviewed runner.
"""

import argparse
import hashlib
import json
import re
from pathlib import Path

from .native.capabilities import capability_hash, normalize_capabilities


SCHEMA = 'figfox-historical-four-cell-plan-v2'
CELL_ORDER = ('S0C0', 'S1C0', 'S0C1', 'S1C1')
FC_BINS = ('C1_low', 'C2_medium_low', 'C3_medium_high', 'C4_high')
SHA256 = re.compile(r'[0-9a-f]{64}\Z')
SAMPLE_ID = re.compile(r'sample-([0-9]{4})\Z')


def _sha256(path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(block)
    return digest.hexdigest()


def _validated_samples(manifest, expected_count):
    if type(expected_count) is not int or expected_count < 1:
        raise ValueError('expected_count must be a positive integer')
    samples = manifest.get('samples')
    if not isinstance(samples, list) or len(samples) != expected_count:
        raise ValueError(f'historical manifest must contain exactly {expected_count} samples')
    if manifest.get('historical_sample_count') != expected_count or manifest.get('matched_count') != expected_count:
        raise ValueError('historical and matched counts must equal expected count')
    for field in ('unmatched', 'ambiguous', 'replacements'):
        if manifest.get(field) != []:
            raise ValueError(f'historical manifest has {field} or lacks explicit empty list')

    ids, orders, dataset_ids, source_hashes = set(), set(), set(), set()
    bins = {name: 0 for name in FC_BINS}
    validated = []
    for sample in samples:
        if not isinstance(sample, dict):
            raise ValueError('every historical sample must be an object')
        sample_id = sample.get('sample_id')
        match = SAMPLE_ID.fullmatch(sample_id) if isinstance(sample_id, str) else None
        order = sample.get('historical_order')
        dataset_id = sample.get('dataset_id')
        if not match or type(order) is not int or not isinstance(dataset_id, str):
            raise ValueError('invalid historical identity')
        if not dataset_id.isdecimal() or int(match.group(1)) != int(dataset_id):
            raise ValueError(f'dataset ID does not bind to {sample_id}')
        if sample_id in ids or order in orders or dataset_id in dataset_ids:
            raise ValueError('duplicate historical ID, order, or dataset ID')
        ids.add(sample_id); orders.add(order); dataset_ids.add(dataset_id)
        if sample.get('match_status') != 'matched':
            raise ValueError(f'{sample_id} is not matched')
        fc_bin = sample.get('fc_bin')
        source_group = sample.get('source_group')
        if fc_bin not in bins or not isinstance(source_group, str) or not source_group:
            raise ValueError(f'{sample_id} has invalid stratum or source group')
        if (sample.get('dataset_fc_bin') != fc_bin or sample.get('dataset_source_group') != source_group
                or sample.get('historical_paired_fc_bin_values') != [fc_bin]
                or sample.get('historical_source_group_values') != [source_group]):
            raise ValueError(f'{sample_id} source binding disagrees with historical and dataset metadata')
        bins[fc_bin] += 1
        source_name = sample.get('source_image_path')
        if not isinstance(source_name, str) or not source_name or not Path(source_name).is_absolute():
            raise ValueError(f'{sample_id} needs an absolute source image path')
        source = Path(source_name)
        if source.stem != dataset_id or not source.is_file():
            raise ValueError(f'{sample_id} source image path does not match dataset ID or is missing')
        recorded_hash = sample.get('source_image_sha256')
        if not isinstance(recorded_hash, str) or not SHA256.fullmatch(recorded_hash):
            raise ValueError(f'{sample_id} source image hash is invalid')
        if _sha256(source) != recorded_hash:
            raise ValueError(f'{sample_id} source image bytes differ from frozen hash')
        if recorded_hash in source_hashes:
            raise ValueError('duplicate source image hash')
        source_hashes.add(recorded_hash)
        validated.append({
            'historical_order': order, 'sample_id': sample_id,
            'dataset_id': dataset_id, 'fc_bin': fc_bin,
            'source_group': source_group, 'source_image_path': str(source),
            'source_image_sha256': recorded_hash,
        })
    if orders != set(range(1, expected_count + 1)):
        raise ValueError('historical order must be exactly consecutive 1-based positions')
    if expected_count == 80 and bins != {name: 20 for name in FC_BINS}:
        raise ValueError('historical 80 must preserve 20 samples in each FC stratum')
    return sorted(validated, key=lambda sample: sample['historical_order'])


def build_plan(manifest_path, *, expected_count=80):
    """Validate local historical binding and return a deterministic plan only."""
    path = Path(manifest_path)
    raw = path.read_bytes()
    manifest = json.loads(raw)
    if not isinstance(manifest, dict):
        raise ValueError('historical manifest must be an object')
    samples = _validated_samples(manifest, expected_count)
    cells = []
    for sample in samples:
        order = sample['historical_order']
        for position in range(4):
            cell_name = CELL_ORDER[(order - 1 + position) % 4]
            sam = cell_name[1] == '1'
            code = cell_name[3] == '1'
            policy = normalize_capabilities({'version': 'capabilities-v1', 'sam': sam,
                                             'code_methods': code})
            cells.append({
                **sample, 'cell': cell_name, 'within_sample_position': position + 1,
                'capabilities': policy, 'capability_hash': capability_hash(policy),
                'output_dir': f"runs/{sample['sample_id']}/{cell_name}",
                'attempt_identity': f"{sample['sample_id']}:{cell_name}:attempt-1",
                'sam_manifest_reuse_group': sample['sample_id'] if sam else None,
                'status': 'planned',
            })
    return {
        'schema': SCHEMA, 'status': 'planned', 'paid_execution_allowed': False,
        'manifest_path': str(path.resolve()), 'manifest_sha256': hashlib.sha256(raw).hexdigest(),
        'sample_count': len(samples), 'cell_count': len(cells),
        'design': {
            'factors': ['sam', 'code_methods'], 'cells': list(CELL_ORDER),
            'order_rule': 'cycle four cell positions by 1-based historical order modulo four',
            'formal_full_cell': 'S1C1', 'formal_full_cell_count_per_sample': 1,
            'other_comparison_reruns': False,
        },
        'common_config': {
            'first': {'model': 'gpt-5.5', 'reasoning_effort': 'medium',
                      'max_output_tokens': 32768},
            'review': {'model': 'deepseek-flash', 'reasoning_effort': 'high',
                       'max_output_tokens': 64000,
                       'context_preflight_may_lower_output_limit': False,
                       'context_preflight_policy': 'admit full requested max_tokens or block before HTTP',
                       'base_requests': ['DS1', 'DS2'],
                       'conditional_followup': 'existing receipt-driven priority trigger',
                       'max_requests': 3},
            'renderer': {
                'engine': 'Chromium', 'playwright_version': '1.62.1',
                'executable_policy': 'PLUS_CHROMIUM if set, otherwise Playwright-installed Chromium',
                'svg_font_policy': 'preserve authored font-family; resolve against one pinned host font inventory',
                'runtime_manifest': 'external manifest required before paid execution',
                'runtime_manifest_verified': False,
            },
            'runtime_limits': {
                'first_http_timeout_seconds': 1800,
                'review_http_timeout_seconds': 300,
                'native_render_timeout_seconds': 60,
                'browser_measure_timeout_seconds': 45,
                'generated_python_wall_timeout_seconds': 20,
                'generated_python_max_output_bytes': 20_000_000,
                'generated_python_rss_limit_mib': 512,
            },
            'sampling': {
                'first_temperature': 'omitted; provider default unverified',
                'first_seed': 'omitted; provider default unverified',
                'review_temperature': 'omitted; provider default unverified',
                'review_seed': 'omitted; provider default unverified',
                'deterministic_sampling_claim': False,
            },
            'quality_policy': 'same common quality and conditional rules in all four cells',
            'quality_policy_hash': 'verify_equal_at_execution',
            'prompt_comparison': 'availability manifest, tool descriptions, and SAM evidence vary by capability; full prompt bytes are not claimed identical',
        },
        'execution_prerequisites': {
            'source_hash_recheck': 'required before each cell',
            'capability_hash_recheck': 'required before each cell',
            'real_sam_service_and_manifest': 'required before paid generation for SAM-on cells',
            'cumulative_budget_bound_and_reservation': 'required before paid generation',
            'runtime_manifest': 'bind one host, OS/Node versions, browser executable SHA-256, and font inventory/file hashes for every cell before paid generation',
            'runtime_manifest_verified': False,
            'actual_sam_verified': False, 'budget_verified': False,
            'no_automatic_retry': True,
            'runtime_records_required': ['attempt identity', 'actual intervention counts',
                                         'usage', 'elapsed time', 'terminal committed image hash',
                                         'quality outcomes including unknown and unreviewed'],
        },
        'samples': samples, 'cells': cells,
    }


def write_plan(manifest_path, out_path, *, expected_count=80):
    """Create the plan atomically with exclusive creation; never replace a plan."""
    out = Path(out_path)
    if out.exists():
        raise FileExistsError(out)
    plan = build_plan(manifest_path, expected_count=expected_count)
    out.parent.mkdir(parents=True, exist_ok=True)
    with out.open('x', encoding='utf-8') as stream:
        json.dump(plan, stream, ensure_ascii=False, sort_keys=True, indent=2)
        stream.write('\n')
    return plan


def main(argv=None):
    parser = argparse.ArgumentParser(description='Validate historical sources and write an offline four-cell plan')
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args(argv)
    plan = write_plan(args.manifest, args.out)
    print(f"planned {plan['sample_count']} sources × 4 = {plan['cell_count']} cells: {args.out}")
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
