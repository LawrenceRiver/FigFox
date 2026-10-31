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

INSPECTION_PROMPT = '''Evaluate discovery and repair separately, keeping the images, SVG, method pack, issue identities and execution context of the same task. Discovery does not depend on whether a fix is possible; a successful repair cannot substitute for discovery coverage.
Three fixed passes: 1 original PNG versus current-render PNG, checking the current-render SVG; 2 all existing paired Crops; 3 the same set of Crops inspected again. Upstream cropping is already finished; do not create new crops, change pairings, or reuse an earlier pass to skip an observation.
Inspect every region completely for E Alignment, F Overlap/Overflow that the original figure does not intend, B Fonts and Formulas correct and legible, A Knowledge content / semantic icons / arrows and key connections, and S1 Obvious geometry structure or proportion errors, locally garbled geometry, or an original photo mistakenly drawn as geometry. Subtle photo texture, color deviation and style differences are secondary.
After the first whole-image comparison, perform step 1.5: audit the current SVG code against the relations the original figure expresses, then go through current_diagnostics item by item for whole-image TP collisions and SVG structural candidates. Every candidate must be checked back against the original figure for counter-evidence; normal containment is not an error - crossing edges, flushing to an edge, or occlusion is judged wrong only by whether the original figure keeps clearance there. Even with no candidates, no region may be skipped.
Inspection method: first list the subjects, containers, text and connections inside the region, then verify each relation one by one; do not rely on overall similarity alone. For arrows, trace from start to end and check whether each end carries exactly the arrowhead and connection the original requires, and whether anything is extra, reversed, or left floating. For icons, verify the identity of the object represented rather than a rough outline. For geometry, verify face by face whether edges and vertices stay coherent, whether the stacking order and length-width-depth proportions hold, and do not stop just because it looks three-dimensional. For text, verify glyph order, word order and the container it sits in. For repeated structures, compare unit counts and the relation of ellipses to the boundary. Write only short verifiable evidence; do not output internal reasoning.
Actively look for E/F candidates, comparing the whole, the members and the neighbors, and use the original figure to exclude intentional asymmetry, containment and legal_overlap. candidate_check carries only verifiable evidence and the candidate conclusion; when there is no candidate, describe plainly which relations were checked, and do not manufacture problems to fill a quota. Do not output hidden reasoning.
Output inspection_records, one entry per region: region is the integer identity given by the host, and checks holds five named observations written in E/F/B/A/S1 order. Each contains state (clear|issue|uncertain|not_applicable), original_observation, current_observation and issue_ids. E/F additionally carry candidate_check; not_applicable entries give applicability_reason; first-pass regions also give svg_observation, stating which SVG identity and attributes were actually checked together with the visible evidence. Record uncertain when unsure or unreadable, and do not fabricate observations.
Give separate short, concrete observations for the original and for the current render; "already checked / normal / same as above" and reusing an earlier pass are forbidden. Several issues may be referenced in one region, and the number of issues is not capped. The host restores only assets, revision and region primary keys; it never infers state, evidence or issue references.
issues and programs still follow the existing contract. The method pack, module_program and generated_python capabilities remain available, bounded by the existing isolated executor. Report problems that cannot be fixed as they are and state why they remain unresolved; keep the real RCD, the post-execution visual acceptance and this round's discovery records separate, and never treat a pre-description as something executed.'''


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
                _text(check[field], f'region={index} category={category} {field}')
            for field in OPTIONAL_FIELDS:
                if field in check or (field == 'candidate_check' and category in ('E', 'F')) or (field == 'applicability_reason' and state == 'not_applicable'):
                    _text(check.get(field), f'region={index} category={category} {field}')
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
