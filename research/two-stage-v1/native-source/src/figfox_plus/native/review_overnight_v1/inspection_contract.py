"""Region-bound discovery records, independent of execution success.

The host must build the schedule from trusted, complete upstream inputs, freeze it
with the request, and send inspection_regions(schedule) to the model. Expansion
restores only that schedule's invariants. The audit cannot prove that a model saw
an image, checked SVG, found every defect, or truthfully described evidence.
"""
from copy import deepcopy

from ..review_priority_v1.compact import _text
from ..review_priority_v1.evidence import validate_observations

CATEGORIES = ('E', 'F', 'B', 'A', 'S1')
IDENTITY = ('image_id', 'pass', 'region_id')
INVARIANTS = ('current_revision', 'original_asset_id', 'current_asset_id', 'evidence_assets')
CHECK_FIELDS = {'state', 'original_observation', 'current_observation', 'issue_ids'}
OPTIONAL_FIELDS = {'applicability_reason', 'candidate_check'}

INSPECTION_PROMPT = '''发现与修复分别评估，保留同一次任务的图像、SVG、方法包、问题身份和执行上下文。发现不取决于能否修复；修复成功也不能代替发现覆盖。
三轮固定：1 原图PNG vs 现图PNG并核现图SVG；2 全部既有配对Crop；3 再次检查全部相同Crop。上游裁切已完成，禁止新切、改配对或借上一轮结果跳过观察。
每个区域完整检查 E对齐、F非原图有意的交叠/出框、B字体公式正确可读、A知识内容、S1明显几何结构/比例错误、局部几何乱码或原照片被误画成几何。照片细微纹理、色差和风格差异次要。
主动寻找E/F候选，比较整体、成员和邻居，依据原图排除有意不对称、包含和合法交叠。candidate_check仅写可核验证据与候选结论；无候选如实描述检查的关系，不为凑数制造问题。不输出隐藏思维过程。
输出inspection_records，每区域一条：region为宿主给的整数身份，checks按E/F/B/A/S1写五条具名观察。每条含state(clear|issue|uncertain|not_applicable)、original_observation、current_observation、issue_ids。E/F另含candidate_check；不适用给applicability_reason；第一轮区域另给svg_observation，说明实际核对的SVG身份/属性及可见证据。不确定或不可读记uncertain，不补造观察。
原图和现图分别给简短具体观察；禁止“已检查/正常/同上”或沿用前轮。多个问题可在同一区域引用，不限制问题数量。宿主仅恢复资产、revision和区域主键，不推测状态、证据、问题引用。
issues与programs仍沿用现有契约。方法包、module_program和generated_python能力保留，受现有隔离执行器限制。无法修复的问题照实报告并说明未解决；真实RCD、执行后视觉验收与本轮发现记录分别留存，不把预描述当已执行。'''


def _object(properties, required):
    return {'type': 'object', 'properties': properties, 'required': required, 'additionalProperties': False}


_TEXT = {'type': 'string', 'minLength': 1}
_CHECK = _object({
    'state': {'enum': ['clear', 'issue', 'uncertain', 'not_applicable']},
    'original_observation': _TEXT, 'current_observation': _TEXT,
    'issue_ids': {'type': 'array', 'items': _TEXT, 'uniqueItems': True},
    'applicability_reason': _TEXT, 'candidate_check': _TEXT,
}, sorted(CHECK_FIELDS))
_CHECKS = {category: deepcopy(_CHECK) for category in CATEGORIES}
for _category in ('E', 'F'):
    _CHECKS[_category]['required'].append('candidate_check')
INSPECTION_SCHEMA = _object({'inspection_records': {
    'type': 'array', 'minItems': 1,
    'items': _object({'region': {'type': 'integer', 'minimum': 0},
                      'checks': _object(_CHECKS, list(CATEGORIES)),
                      'svg_observation': _TEXT}, ['region', 'checks']),
}}, ['inspection_records'])


def _fail(message):
    raise ValueError('invalid_inspection_records: ' + message)


def inspection_regions(schedule):
    """Return a compact immutable-by-copy host manifest; reject invalid coverage.

    The same crop IDs, asset pairs and revision must occur in passes two/three.
    Completeness relative to upstream crops remains the schedule builder's duty.
    """
    if not isinstance(schedule, list) or not schedule:
        _fail('nonempty host schedule required')
    groups = {}; images = {}
    for unit in schedule:
        if not isinstance(unit, dict) or any(k not in unit for k in (*IDENTITY, *INVARIANTS, 'category')):
            _fail('invalid schedule unit')
        if any(not isinstance(unit[k], str) or not unit[k].strip()
               for k in ('image_id', 'region_id', 'current_revision', 'original_asset_id', 'current_asset_id')):
            _fail('invalid schedule identity or invariant')
        if type(unit['pass']) is not int or unit['pass'] not in (1, 2, 3) or unit['category'] not in CATEGORIES:
            _fail('invalid schedule pass or category')
        if unit['evidence_assets'] != [unit['original_asset_id'], unit['current_asset_id']]:
            _fail('asset pair differs from evidence')
        key = tuple(unit[k] for k in IDENTITY)
        if key not in groups:
            groups[key] = ({k: deepcopy(unit[k]) for k in (*IDENTITY, *INVARIANTS)}, set())
        region, categories = groups[key]
        if any(region[k] != unit[k] for k in INVARIANTS) or unit['category'] in categories:
            _fail('duplicate unit or inconsistent region invariants')
        categories.add(unit['category'])
        images.setdefault(unit['image_id'], {}).setdefault(unit['pass'], {})[unit['region_id']] = region
    for region, categories in groups.values():
        if categories != set(CATEGORIES): _fail('all five categories required per region')
    for passes in images.values():
        if set(passes) != {1, 2, 3} or set(passes[1]) != {'full'}:
            _fail('three passes and one full-image region required')
        if set(passes[2]) != set(passes[3]): _fail('crop coverage changed between passes')
        revisions = {r['current_revision'] for regions in passes.values() for r in regions.values()}
        if len(revisions) != 1: _fail('inspection revision changed')
        for region_id, second in passes[2].items():
            if any(second[k] != passes[3][region_id][k] for k in INVARIANTS):
                _fail('crop pairing changed between passes')
    return [dict(region=index, **region) for index, (region, _) in enumerate(groups.values())]


def expand_observations(plan, schedule):
    """Expand explicit region records into existing schedule-ordered observations.

    Other plan fields (issues/programs) are left untouched. No positional joins of
    states/evidence/issue arrays and no inferred default observations are used.
    """
    regions = inspection_regions(schedule)
    if not isinstance(plan, dict) or any(k in plan for k in ('observations', 'observation_rows', 'observation_evidence')):
        _fail('region records required; mixed encodings forbidden')
    records = plan.get('inspection_records')
    if not isinstance(records, list) or len(records) != len(regions):
        _fail('one record required for every scheduled region')
    bound = {}
    for record in records:
        if not isinstance(record, dict) or set(record) - {'region', 'checks', 'svg_observation'}:
            _fail('invalid region fields')
        index = record.get('region')
        if type(index) is not int or not 0 <= index < len(regions) or index in bound:
            _fail('unknown or duplicate region')
        region = regions[index]; checks = record.get('checks')
        if not isinstance(checks, dict) or set(checks) != set(CATEGORIES):
            _fail('every region requires all five named checks')
        if region['pass'] == 1 or 'svg_observation' in record:
            _text(record.get('svg_observation'), 'svg_observation')
        for category, check in checks.items():
            if not isinstance(check, dict) or not CHECK_FIELDS <= set(check) or set(check) - CHECK_FIELDS - OPTIONAL_FIELDS:
                _fail('invalid check fields')
            state = check['state']
            if not isinstance(state, str) or state not in ('clear', 'issue', 'uncertain', 'not_applicable'):
                _fail('invalid state')
            for field in ('original_observation', 'current_observation'):
                _text(check[field], field)
            for field in OPTIONAL_FIELDS:
                if field in check or (field == 'candidate_check' and category in ('E', 'F')) or (field == 'applicability_reason' and state == 'not_applicable'):
                    _text(check.get(field), field)
            refs = check['issue_ids']
            if not isinstance(refs, list) or any(not isinstance(r, str) or not r.strip() for r in refs) or len(refs) != len(set(refs)):
                _fail('invalid issue references')
            if (state == 'issue' and not refs) or (state in ('clear', 'not_applicable') and refs):
                _fail('state and issue references disagree')
        bound[index] = record
    by_identity = {tuple(r[k] for k in IDENTITY): r['region'] for r in regions}
    result = []
    for unit in schedule:
        record = bound[by_identity[tuple(unit[k] for k in IDENTITY)]]
        row = {k: deepcopy(unit[k]) for k in (*IDENTITY, 'category', 'current_revision', 'evidence_assets')}
        row.update(deepcopy(record['checks'][unit['category']]))
        if 'svg_observation' in record: row['svg_observation'] = record['svg_observation']
        result.append(row)
    return result


def audit_inspection(schedule, plan, issues):
    """Audit discovery coverage/linkage only; execution outcome is not an input."""
    try:
        observations = expand_observations(plan, schedule)
    except ValueError as exc:
        return {'records_complete': False, 'inspection_complete': False,
                'visual_acceptance': 'not_assessed', 'status': 'inspection_incomplete',
                'errors': [{'code': 'invalid_inspection_records', 'message': str(exc)}]}
    return validate_observations(schedule, observations, issues)
