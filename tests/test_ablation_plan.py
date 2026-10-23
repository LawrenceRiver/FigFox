"""Offline checks for the historical four-cell preregistration."""
import hashlib
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from figfox_plus.ablation_plan import build_plan, write_plan


def fixture_manifest(tmp_path):
    samples = []
    for order, dataset_id in enumerate(('005', '077'), 1):
        image = tmp_path / f'{dataset_id}.png'
        image.write_bytes(f'fixture-{dataset_id}'.encode())
        samples.append({
            'historical_order': order,
            'sample_id': f'sample-{int(dataset_id):04d}',
            'dataset_id': dataset_id,
            'fc_bin': 'C1_low',
            'dataset_fc_bin': 'C1_low',
            'source_group': f'paper-{dataset_id}',
            'dataset_source_group': f'paper-{dataset_id}',
            'historical_source_group_values': [f'paper-{dataset_id}'],
            'historical_paired_fc_bin_values': ['C1_low'],
            'match_status': 'matched',
            'source_image_path': str(image),
            'source_image_sha256': hashlib.sha256(image.read_bytes()).hexdigest(),
        })
    manifest = {'historical_sample_count': 2, 'matched_count': 2,
                'unmatched': [], 'ambiguous': [], 'replacements': [], 'samples': samples}
    path = tmp_path / 'manifest.json'
    path.write_text(json.dumps(manifest))
    return path, manifest


def test_four_frozen_cells_per_historical_source_with_balanced_order(tmp_path):
    manifest_path, manifest = fixture_manifest(tmp_path)
    plan = build_plan(manifest_path, expected_count=2)
    assert plan['status'] == 'planned'
    assert plan['paid_execution_allowed'] is False
    assert plan['sample_count'] == 2 and plan['cell_count'] == 8
    assert [c['cell'] for c in plan['cells'][:4]] == ['S0C0', 'S1C0', 'S0C1', 'S1C1']
    assert [c['cell'] for c in plan['cells'][4:]] == ['S1C0', 'S0C1', 'S1C1', 'S0C0']
    assert len({c['output_dir'] for c in plan['cells']}) == 8
    assert len({(c['sample_id'], c['cell']) for c in plan['cells']}) == 8
    for cell in plan['cells']:
        source = manifest['samples'][cell['historical_order'] - 1]
        assert cell['sample_id'] == source['sample_id']
        assert cell['source_image_sha256'] == source['source_image_sha256']
        assert cell['capability_hash'] and len(cell['capability_hash']) == 64
        assert cell['status'] == 'planned'
    assert sum(c['cell'] == 'S1C1' for c in plan['cells']) == 2
    assert plan['common_config']['first']['model'] == 'gpt-5.5'
    assert plan['common_config']['review']['model'] == 'deepseek-flash'
    assert plan['common_config']['review']['max_output_tokens'] == 64000
    assert plan['common_config']['review']['max_requests'] == 3


def test_common_runtime_sampling_and_context_policy_are_explicit(tmp_path, monkeypatch):
    import socket

    path, manifest = fixture_manifest(tmp_path)
    allowed = {path.resolve(), *(Path(sample['source_image_path']).resolve()
                                 for sample in manifest['samples'])}
    original_open = Path.open

    def only_historical_inputs(self, *args, **kwargs):
        if self.resolve() not in allowed:
            pytest.fail(f'unexpected file read: {self}')
        return original_open(self, *args, **kwargs)

    monkeypatch.setattr(Path, 'open', only_historical_inputs)
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('network opened'))
    plan = build_plan(path, expected_count=2)
    common = plan['common_config']
    assert common['renderer'] == {
        'engine': 'Chromium',
        'playwright_version': '1.62.1',
        'executable_policy': 'PLUS_CHROMIUM if set, otherwise Playwright-installed Chromium',
        'svg_font_policy': 'preserve authored font-family; resolve against one pinned host font inventory',
        'runtime_manifest': 'external manifest required before paid execution',
        'runtime_manifest_verified': False,
    }
    assert common['runtime_limits'] == {
        'first_http_timeout_seconds': 1800,
        'review_http_timeout_seconds': 300,
        'native_render_timeout_seconds': 60,
        'legacy_browser_measure_timeout_seconds': 45,
        'native_tight_tp_timeout_seconds': 900,
        'native_line_sampling_timeout_seconds': 120,
        'native_coincident_sampling_timeout_seconds': 120,
        'generated_python_wall_timeout_seconds': 20,
        'generated_python_max_output_bytes': 20_000_000,
        'generated_python_rss_limit_mib': 512,
    }
    assert common['sampling'] == {
        'first_temperature': 'omitted; provider default unverified',
        'first_seed': 'omitted; provider default unverified',
        'review_temperature': 'omitted; provider default unverified',
        'review_seed': 'omitted; provider default unverified',
        'deterministic_sampling_claim': False,
    }
    assert common['review']['context_preflight_may_lower_output_limit'] is False
    assert common['review']['context_preflight_policy'] == 'admit full requested max_tokens or block before HTTP'
    assert plan['execution_prerequisites']['runtime_manifest_verified'] is False
    assert plan['paid_execution_allowed'] is False


@pytest.mark.parametrize('mutation', [
    lambda m: m['samples'][1].update(sample_id=m['samples'][0]['sample_id']),
    lambda m: m['samples'][1].update(historical_order=1),
    lambda m: m['samples'].pop(),
    lambda m: m.update(unmatched=['sample-0005']),
    lambda m: m.update(ambiguous=['sample-0005']),
    lambda m: m.update(replacements=['sample-0005']),
    lambda m: m['samples'][0].update(match_status='unmatched'),
    lambda m: m['samples'][0].update(dataset_id='999'),
    lambda m: m['samples'][0].update(dataset_source_group='different'),
    lambda m: m['samples'][0].update(source_image_sha256='0' * 64),
])
def test_invalid_historical_binding_cannot_be_planned(tmp_path, mutation):
    path, manifest = fixture_manifest(tmp_path)
    mutation(manifest)
    path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError):
        build_plan(path, expected_count=2)


def test_missing_source_and_existing_output_are_rejected(tmp_path):
    path, manifest = fixture_manifest(tmp_path)
    Path(manifest['samples'][0]['source_image_path']).unlink()
    with pytest.raises(ValueError):
        build_plan(path, expected_count=2)
    path, _ = fixture_manifest(tmp_path)
    out = tmp_path / 'plan.json'
    write_plan(path, out, expected_count=2)
    first = out.read_bytes()
    with pytest.raises(FileExistsError):
        write_plan(path, out, expected_count=2)
    assert out.read_bytes() == first


def test_cli_only_plans_and_public_count_is_exact_80(tmp_path):
    path, _ = fixture_manifest(tmp_path)
    env = dict(os.environ, PYTHONPATH=str(Path(__file__).resolve().parents[1] / 'src'))
    command = [sys.executable, '-m', 'figfox_plus.ablation_plan', '--manifest', str(path),
               '--out', str(tmp_path / 'plan.json')]
    result = subprocess.run(command, cwd=Path(__file__).resolve().parents[1], env=env,
                            text=True, capture_output=True)
    assert result.returncode != 0
    assert not (tmp_path / 'plan.json').exists()
    help_result = subprocess.run([sys.executable, '-m', 'figfox_plus.ablation_plan', '--help'],
                                 cwd=Path(__file__).resolve().parents[1], env=env,
                                 text=True, capture_output=True)
    assert help_result.returncode == 0
    assert '--execute' not in help_result.stdout


def test_plan_generation_never_opens_network(tmp_path, monkeypatch):
    import socket

    path, _ = fixture_manifest(tmp_path)
    monkeypatch.setattr(socket, 'socket', lambda *a, **k: pytest.fail('network opened'))
    assert build_plan(path, expected_count=2)['cell_count'] == 8
