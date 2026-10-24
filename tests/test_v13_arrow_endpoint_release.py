"""The D constructor guard permits only structural trims of existing marked shafts."""
from copy import deepcopy
import hashlib

import pytest

from figfox_plus.native.review_problem_first_v13 import programs


ON = {'version': 'capabilities-v1', 'sam': False, 'code_methods': True}
OFF = dict(ON, code_methods=False)
OLD = {
    'top': 'M231 240 L202 90',
    'left': 'M231 240 L103 186',
    'bottom': 'M231 240 L215 368',
    'right': 'M231 240 L325 282',
}
NEW = {
    'top': 'M 231 240 L 204.3 101.8',
    'left': 'M 231 240 L 114.1 190.7',
    'bottom': 'M 231 240 L 216.5 356.1',
    'right': 'M 231 240 L 314.0 277.1',
}


def fixture(tmp_path, old=None, new=None, *, marked=True, marker=True):
    old = old or OLD
    new = new or NEW
    path = tmp_path / 'arrows.svg'
    marker_node = '<defs><marker id="head"><path d="M0 0 L1 1"/></marker></defs>' if marker else ''
    marker_attr = ' marker-end="url(#head)"' if marked else ''
    paths = ''.join(f'<path id="{name}" d="{d}"{marker_attr}/>' for name, d in old.items())
    path.write_text(f'<svg xmlns="http://www.w3.org/2000/svg" width="500" height="500">{marker_node}{paths}</svg>')
    names = list(old)
    images = {'im': {'svg': str(path), 'revision': hashlib.sha256(path.read_bytes()).hexdigest(),
                     'original': str(tmp_path / 'original.png'), 'png': str(tmp_path / 'preview.png')}}
    issue = {'id': 'D-02', 'image_id': 'im', 'category': 'D', 'target_ids': names,
             'neighbor_ids': [], 'description': 'shaft tips', 'original_evidence': 'original figure'}
    program = {'id': 'P-D02', 'image_id': 'im', 'issue_ids': ['D-02'],
               'base_revision': images['im']['revision'], 'phase': 'reconstructor',
               'route': 'module_program', 'target_ids': names, 'depends_on': [],
               'args': {'operations': [{'method': 'bp_patch', 'target_ids': [name],
                                        'args': {'attributes': {'d': new[name]}}} for name in names]}}
    return images, issue, program


def validate(images, issues, program, capabilities=ON):
    return programs.validate_programs([program], issues, images, capabilities=capabilities)


def test_saved_four_endpoint_pattern_passes_without_sp_constructor(tmp_path):
    images, issue, program = fixture(tmp_path)
    assert validate(images, [issue], program)['P-D02'] == [issue]


@pytest.mark.parametrize(('old', 'new'), [
    ({'shaft': 'M0 0 L100 0'}, {'shaft': 'M0 0 L75 0'}),
    ({'shaft': 'M0 0 L1000 0'}, {'shaft': 'M0 0 L10 0'}),
    ({'shaft': 'M0 0 L1e2 0'}, {'shaft': 'M0 0 L7.5e1 0'}),
    ({'shaft': 'M0 0 L0.1 0'}, {'shaft': 'M0 0 L0.075 0'}),
    ({'shaft': 'M0 0 L1e-300 0'}, {'shaft': 'M0 0 L5e-301 0'}),
    ({'shaft': 'M0 0 L100 100'}, {'shaft': 'M0 0 L75.0 75.04'}),
])
def test_inward_trim_accepts_scale_and_decimal_rounding(tmp_path, old, new):
    images, issue, program = fixture(tmp_path, old, new)
    assert validate(images, [issue], program)['P-D02'] == [issue]


@pytest.mark.parametrize(('old_d', 'new_d'), [
    ('M0 0 L100 0', 'M0 0 L75 1'),
    ('M0 0 L100 0', 'M1 0 L75 0'),
    ('M0 0 L100 0', 'M0 0 L101 0'),
    ('M0 0 L100 0', 'M0 0 L-1 0'),
    ('M0 0 L100 0', 'M0 0 L0 0'),
    ('M0 0 L0 0', 'M0 0 L0 0'),
    ('M0 0 L1e309 0', 'M0 0 L1 0'),
    ('M0 0 L100 0', 'M0 0 LNaN 0'),
    ('M0 0 L1e-400 0', 'M0 0 L5e-401 0'),
    ('M0 0 L100 0', 'M0 0 L75 0e400'),
    ('M0 0 L100 0', 'M0 0 L75 0e-400'),
    ('M0 0 L100 0', 'M0 0 L75 0 L80 0'),
    ('M0 0 L100 0', 'M0 0 Q75 0 50 0'),
    ('M0 0 Q50 0 100 0', 'M0 0 L75 0'),
])
def test_non_trim_geometry_does_not_receive_exception(tmp_path, old_d, new_d):
    images, issue, program = fixture(tmp_path, {'shaft': old_d}, {'shaft': new_d})
    with pytest.raises(ValueError, match='arrow must be rebuilt'):
        validate(images, [issue], program)


@pytest.mark.parametrize(('marked', 'marker'), [(False, True), (True, False)])
def test_path_needs_existing_local_marker(tmp_path, marked, marker):
    images, issue, program = fixture(tmp_path, {'shaft': 'M0 0 L100 0'},
                                     {'shaft': 'M0 0 L75 0'}, marked=marked, marker=marker)
    with pytest.raises(ValueError, match='arrow must be rebuilt'):
        validate(images, [issue], program)


def test_marker_reference_must_resolve_to_marker_node(tmp_path):
    images, issue, program = fixture(tmp_path, {'shaft': 'M0 0 L100 0'}, {'shaft': 'M0 0 L75 0'})
    path = tmp_path / 'arrows.svg'
    path.write_text(path.read_text().replace('<marker id="head">', '<g id="head">').replace('</marker>', '</g>'))
    images['im']['revision'] = hashlib.sha256(path.read_bytes()).hexdigest()
    program['base_revision'] = images['im']['revision']
    with pytest.raises(ValueError, match='arrow must be rebuilt'):
        validate(images, [issue], program)


def test_extra_attributes_and_operations_do_not_receive_exception(tmp_path):
    images, issue, program = fixture(tmp_path, {'shaft': 'M0 0 L100 0'}, {'shaft': 'M0 0 L75 0'})
    variants = []
    extra_attr = deepcopy(program)
    extra_attr['args']['operations'][0]['args']['attributes']['stroke'] = 'red'
    variants.append(extra_attr)
    extra_operation = deepcopy(program)
    extra_operation['args']['operations'].append({'method': 'measure', 'target_ids': ['shaft'], 'args': {}})
    variants.append(extra_operation)
    repeated = deepcopy(program)
    repeated['args']['operations'].append(deepcopy(repeated['args']['operations'][0]))
    variants.append(repeated)
    repair = deepcopy(program)
    repair['convergence'] = {'repairs': [{'method': 'tp_transform', 'target_ids': ['shaft'], 'args': {}}]}
    variants.append(repair)
    for variant in variants:
        with pytest.raises(ValueError, match='arrow must be rebuilt'):
            validate(images, [issue], variant)


def test_only_declared_issue_targets_may_be_edited(tmp_path):
    old = {'shaft': 'M0 0 L100 0', 'neighbor': 'M0 10 L100 10'}
    new = {'shaft': 'M0 0 L75 0', 'neighbor': 'M0 10 L75 10'}
    images, issue, program = fixture(tmp_path, old, new)
    issue['target_ids'] = ['shaft']
    issue['neighbor_ids'] = ['neighbor']
    with pytest.raises(ValueError, match='arrow must be rebuilt'):
        validate(images, [issue], program)
    issue['neighbor_ids'] = []
    with pytest.raises(ValueError, match='arrow must be rebuilt'):
        validate(images, [issue], program)


def test_declared_targets_must_match_edited_subset_without_duplicates(tmp_path):
    images, issue, program = fixture(tmp_path, {'shaft': 'M0 0 L100 0', 'other': 'M0 10 L100 10'},
                                     {'shaft': 'M0 0 L75 0', 'other': 'M0 10 L75 10'})
    program['args']['operations'].pop()
    with pytest.raises(ValueError, match='arrow must be rebuilt'):
        validate(images, [issue], program)
    program['target_ids'] = ['shaft', 'shaft']
    with pytest.raises(ValueError, match='arrow must be rebuilt'):
        validate(images, [issue], program)


def test_mixed_categories_and_disabled_methods_do_not_get_exception(tmp_path):
    images, issue, program = fixture(tmp_path, {'shaft': 'M0 0 L100 0'}, {'shaft': 'M0 0 L75 0'})
    other = dict(issue, id='other', category='B')
    program['issue_ids'].append('other')
    with pytest.raises(ValueError, match='arrow must be rebuilt'):
        validate(images, [issue, other], program)
    program['issue_ids'].pop()
    with pytest.raises(ValueError, match='disabled'):
        validate(images, [issue], program, OFF)


def test_sp_arrow_constructor_route_remains_valid(tmp_path):
    images, issue, program = fixture(tmp_path, {'shaft': 'M0 0 L100 0'}, {'shaft': 'M0 0 L75 0'})
    program['args']['operations'] = [{'method': 'sp_replace', 'target_ids': ['shaft'],
                                      'args': {'kind': 'arrow', 'data': {'start': [0, 0], 'end': [75, 0]}}}]
    assert validate(images, [issue], program)['P-D02'] == [issue]
