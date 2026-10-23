"""Interrupted follow-up execution must remain the terminal review result."""
import hashlib
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import pytest
from PIL import Image

from figfox_plus.native.chain import bundle_from_stage
from figfox_plus.native.pipeline import stage
from figfox_plus.native.review_problem_first_v13 import orchestrator, programs


OFF = {'version': 'capabilities-v1', 'sam': False, 'code_methods': False}
SVG = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect id="a" x="1" y="1" width="20" height="20" fill="red"/></svg>'
CODE = ('import xml.etree.ElementTree as ET\n'
        'tree=ET.parse(INPUT_SVG)\n'
        'tree.getroot()[0].set("fill","blue")\n'
        'tree.write(OUTPUT_SVG,encoding="unicode")\n')


def _prepared_review(tmp_path):
    original = tmp_path/'original.png'
    Image.new('RGB', (100, 100), 'white').save(original)
    stage(ET.fromstring(SVG), original, tmp_path/'stage-0')
    bundle = bundle_from_stage(tmp_path, original, 'im')
    task = tmp_path/'review'
    orchestrator.prepare(bundle, task, capabilities=OFF)
    issue = {'id': 'i', 'image_id': 'im', 'category': 'S1', 'decision': 'confirmed',
             'target_ids': ['a'], 'neighbor_ids': [], 'description': 'synthetic wrong shape',
             'original_evidence': 'synthetic original', 'current_evidence': 'synthetic current'}
    program = {'id': 'p', 'issue_ids': ['i'], 'image_id': 'im',
               'base_revision': bundle['images']['im']['current_revision'],
               'phase': 'reconstructor', 'route': 'generated_python', 'target_ids': ['a'],
               'depends_on': [], 'source_code': CODE}
    return task, issue, program


def _interrupt_after_real_commit(tmp_path, monkeypatch):
    task, issue, program = _prepared_review(tmp_path)
    original_execute = programs.execute_programs
    calls = []

    def committed_then_interrupted(*args, **kwargs):
        result = original_execute(*args, **kwargs)
        if Path(args[3]).parent == task.parent/'review-followup':
            assert result['rcd'][0]['status'] == 'changed_unverified'
            raise KeyboardInterrupt('after committed follow-up execution')
        return result

    def sender(*args, **kwargs):
        calls.append(1)
        return {'role': 'assistant', 'content': json.dumps({
            'issues': [issue], 'programs': [program] if len(calls) == 3 else []})}

    monkeypatch.setattr(programs, 'execute_programs', committed_then_interrupted)
    with pytest.raises(KeyboardInterrupt, match='after committed'):
        orchestrator.run(task, sender=sender, capabilities=OFF)
    assert len(calls) == 3
    saved = json.loads((task/'result.json').read_text())
    committed = json.loads((task.parent/'review-followup/execution/result.json').read_text())
    assert 'red' in Path(saved['images']['im']['svg']).read_text()
    assert 'blue' in Path(committed['images']['im']['svg']).read_text()
    return task, saved, committed


def _forbidden_sender(*args, **kwargs):
    pytest.fail('resume called the model')


@pytest.mark.parametrize('only_state', [False, True])
def test_resume_adopts_committed_followup_without_model_call(tmp_path, monkeypatch, only_state):
    task, saved, committed = _interrupt_after_real_commit(tmp_path, monkeypatch)
    if only_state:
        (task.parent/'review-followup/execution/result.json').unlink()
    result = orchestrator.run(task, sender=_forbidden_sender, capabilities=OFF)
    assert result['images'] == committed['images']
    assert result['images'] != saved['images']
    assert result['terminal_source'] == 'followup'
    assert result['followup']['rcd'] == committed['rcd']
    assert result['rcd'] == committed['rcd']
    assert result['visual_passed'] is False
    assert result['status'] == 'visual_review_pending'
    assert json.loads((task/'result.json').read_text()) == result


def test_repeated_resume_does_not_duplicate_followup_receipts(tmp_path, monkeypatch):
    task, _, committed = _interrupt_after_real_commit(tmp_path, monkeypatch)
    first = orchestrator.run(task, sender=_forbidden_sender, capabilities=OFF)
    second = orchestrator.run(task, sender=_forbidden_sender, capabilities=OFF)
    assert second == first
    assert second['rcd'] == committed['rcd']


def test_resume_rejects_modified_committed_svg(tmp_path, monkeypatch):
    task, saved, committed = _interrupt_after_real_commit(tmp_path, monkeypatch)
    svg = Path(committed['images']['im']['svg'])
    svg.write_text(svg.read_text().replace('blue', 'green'))
    assert hashlib.sha256(svg.read_bytes()).hexdigest() != committed['images']['im']['revision']
    with pytest.raises(ValueError, match='followup committed SVG revision mismatch'):
        orchestrator.run(task, sender=_forbidden_sender, capabilities=OFF)
    assert json.loads((task/'result.json').read_text()) == saved


def test_resume_without_durable_followup_commit_keeps_saved_result(tmp_path, monkeypatch):
    task, saved, _ = _interrupt_after_real_commit(tmp_path, monkeypatch)
    execution = task.parent/'review-followup/execution'
    (execution/'result.json').unlink()
    (execution/'state.json').unlink()
    result = orchestrator.run(task, sender=_forbidden_sender, capabilities=OFF)
    assert result == saved
