"""Compact model-declared itinerary and candidate/issue linkage, not visual proof.

Uses the existing host inspection_regions(schedule) identities. No synthetic
normal-region records are created and no old inspection encoding is expanded.
This module performs no file, image, network, model, or execution operations.
"""
from .review_problem_first_v3.inspection_contract import inspection_regions


CATEGORIES = ('E', 'F', 'B', 'A', 'S1')
PROMPT = '''按 E对齐 → F交叠/触边/出框 → B文字公式 → A知识语义与连接 → S1明显几何错误的顺序检查。
对每一类完整走完：全图原图/现图对照 → 当前SVG与TP核查 → 全部既有配对Crop → 再看全部相同Crop作查漏与反证，然后才进入下一类。不得重新按疑点裁图替代既有Crop。
输出 compact_category_sweeps，严格按 E,F,B,A,S1 排列。每项包含 category、visited_regions（按宿主region catalog完整有序列出全部region编号，包含三轮；不是crop名称）、whole_image_observation、svg_observation、candidates，可另给candidate_summary。每类只需简短、具体的全图观察和SVG/TP观察，不要求为每个正常区域写两段描述，也不要求虚构正常记录。
candidates每项为{region,original_evidence,current_evidence,decision:confirmed|uncertain|rejected,issue_ids}。只报告有证据的候选：原图与现图证据分开，decision与关联issue的决定一致。confirmed/uncertain候选必须关联本region所属图片、同类别的实际issues；每个confirmed/uncertain issue也必须至少被同类别且同决定的candidate引用。重复观察同一问题可引用同一issue，不制造重复问题。rejected候选可以没有issue_ids，但仍需具体反证。
E/F至少给候选或明确candidate_summary说明如何由原图关系排除了候选；没有候选就如实说明反证，不为满足数量捏造问题。candidate_summary不能替代已发现问题的候选与issue关联。
other_sweep保留{examined_regions,summary,findings}：examined_regions完整有序覆盖全部region；summary给简短查漏结论。findings每项{regions,decision:missed_primary|secondary|uncertain|ignored,issue_ids,evidence}，regions为非空区域子集，evidence必有具体证据。missed_primary需关联实际confirmed issue及相应region/category的confirmed候选；findings可空，不强迫制造遗漏。
issues、programs及prior_issue_reviews保持完整原执行接口，动态代码能力不变。只提交观察、候选证据和结论，不输出内部思维。
visited_regions只是模型声明的访问顺序：宿主审计只能确认declared itinerary completeness与引用关系，不能证明真看过、判断正确、找全或视觉通过。执行成功也不等于视觉验收。
仅当宿主确认首轮声明与引用记录完整，第二轮review_only可只提交issues/programs/prior_issue_reviews，无需重交compact_category_sweeps和other_sweep；仍需依照实际新图复核旧问题并给出纠正。'''


def _object(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required, 'additionalProperties': False}


def _array(items):
    return {'type': 'array', 'items': items}


def build_schema(schedule, review_only=False):
    """Return a complete tool-parameter schema, preserving open execution items.

    This deliberately is NOT a strict-mode schema: program/issue/review objects
    remain open so existing execution contracts and arbitrary source survive.
    Audit checks array order/completeness; the schema does not imply a visit.
    """
    regions = inspection_regions(schedule)
    text = {'type': 'string'}
    refs = _array({'type': 'string'})
    region = {'type': 'integer', 'enum': [r['region'] for r in regions]}
    props = {}
    if not review_only:
        candidate = _object({
            'region': region, 'original_evidence': text, 'current_evidence': text,
            'decision': {'type': 'string', 'enum': ['confirmed', 'uncertain', 'rejected']},
            'issue_ids': refs,
        })
        props['compact_category_sweeps'] = _array(_object({
            'category': {'type': 'string', 'enum': list(CATEGORIES)},
            'visited_regions': _array(region), 'whole_image_observation': text,
            'svg_observation': text, 'candidates': _array(candidate), 'candidate_summary': text,
        }, ['category', 'visited_regions', 'whole_image_observation', 'svg_observation', 'candidates']))
        props['other_sweep'] = _object({
            'examined_regions': _array(region), 'summary': text,
            'findings': _array(_object({
                'regions': _array(region),
                'decision': {'type': 'string', 'enum': ['missed_primary', 'secondary', 'uncertain', 'ignored']},
                'issue_ids': refs, 'evidence': text,
            })),
        })
    props.update({name: _array({'type': 'object'}) for name in ('issues', 'programs', 'prior_issue_reviews')})
    return _object(props)


def _need(condition, message):
    if not condition: raise ValueError(message)


def _text(value, label):
    _need(isinstance(value, str) and bool(value.strip()), label + ' requires nonempty evidence')


def _fields(value, required, optional=()):
    _need(isinstance(value, dict), 'record must be an object')
    _need(set(required) <= set(value) <= set(required) | set(optional), 'missing or unknown compact record fields')


def _regions(value, known, *, complete=False):
    _need(isinstance(value, list) and all(type(i) is int for i in value), 'region IDs must be integer array')
    _need(len(value) == len(set(value)), 'duplicate region IDs')
    if complete:
        _need(value == list(known), 'declared region coverage/order incomplete')
    else:
        _need(bool(value) and set(value) <= set(known), 'finding needs known nonempty regions')


def _refs(value, issues):
    _need(isinstance(value, list) and all(isinstance(i, str) for i in value), 'issue_ids must be strings')
    _need(len(value) == len(set(value)), 'duplicate issue reference')
    _need(all(i in issues for i in value), 'unknown issue reference')
    return value


def audit(schedule, plan, issues=None):
    """Audit first-round declarations and links, returning explicit limited coverage.

    `issues` optionally supplies the host's actual issue list; it is authoritative
    over plan.issues. Neither input is mutated. Review-only plans are NOT initial
    itinerary evidence: callers keep the prior coverage on that second round and
    separately audit prior_issue_reviews against the current execution revision.
    """
    report = {
        'coverage_kind': 'declared_itinerary_completeness',
        'records_complete': False, 'declared_itinerary_complete': False,
        'candidate_links_complete': False, 'images_seen_verified': False,
        'semantic_completeness': 'not_assessed', 'visual_acceptance': 'not_assessed',
        'visual_passed': False, 'status': 'inspection_incomplete',
        'expected_visits': 0, 'declared_visits': 0, 'errors': [],
        'limitations': ['Visit order is model-declared, not observation telemetry.',
                       'Candidate links do not prove correctness or exhaustive detection.',
                       'Execution and visual acceptance are separate.'],
    }
    try:
        catalog = inspection_regions(schedule)
        by_region = {r['region']: r for r in catalog}
        expected = list(by_region)
        report['expected_visits'] = len(expected) * len(CATEGORIES)
        _need(isinstance(plan, dict), 'plan must be object')
        _need(not {'inspection_records', 'category_sweeps', 'observations', 'category_checks'} & set(plan),
              'mixed legacy inspection encodings are not accepted')
        sweeps = plan.get('compact_category_sweeps')
        _need(isinstance(sweeps, list) and all(isinstance(s, dict) for s in sweeps), 'compact_category_sweeps required')
        _need([s.get('category') for s in sweeps] == list(CATEGORIES), 'category order must be E F B A S1')
        report['declared_visits'] = sum(len(s['visited_regions']) for s in sweeps if isinstance(s.get('visited_regions'), list))
        for sweep in sweeps:
            _fields(sweep, ('category', 'visited_regions', 'whole_image_observation', 'svg_observation', 'candidates'), ('candidate_summary',))
            _regions(sweep['visited_regions'], expected, complete=True)
            _text(sweep['whole_image_observation'], 'whole_image_observation')
            _text(sweep['svg_observation'], 'svg_observation')
            _need(isinstance(sweep['candidates'], list), 'candidates must be array')
            if 'candidate_summary' in sweep:
                _need(isinstance(sweep['candidate_summary'], str), 'candidate_summary must be string')
            if sweep['category'] in ('E', 'F') and not sweep['candidates']:
                _text(sweep.get('candidate_summary'), 'E/F candidate_summary without candidates')
        other = plan.get('other_sweep')
        _fields(other, ('examined_regions', 'summary', 'findings'))
        _regions(other['examined_regions'], expected, complete=True)
        _text(other['summary'], 'other_sweep summary')
        _need(isinstance(other['findings'], list), 'other findings must be array')
        report['declared_itinerary_complete'] = True
        actual = plan.get('issues') if issues is None else issues
        _need(isinstance(actual, list), 'actual issues required')
        known = {}
        image_ids = {r['image_id'] for r in catalog}
        for issue in actual:
            _need(isinstance(issue, dict), 'issue must be object')
            ident = issue.get('id')
            _need(isinstance(ident, str) and bool(ident.strip()) and ident not in known, 'invalid/duplicate issue ID')
            _need(issue.get('category') in CATEGORIES and issue.get('image_id') in image_ids, 'issue category/image outside itinerary')
            _need(issue.get('decision') in ('confirmed', 'uncertain', 'preserved', 'duplicate'), 'invalid issue decision')
            known[ident] = issue
        linked = set()
        locations = {}
        for sweep in sweeps:
            category = sweep['category']
            for row in sweep['candidates']:
                _fields(row, ('region', 'original_evidence', 'current_evidence', 'decision', 'issue_ids'))
                region_id = row['region']
                _need(type(region_id) is int and region_id in by_region, 'candidate region is not a host identity')
                _text(row['original_evidence'], 'candidate original_evidence')
                _text(row['current_evidence'], 'candidate current_evidence')
                decision = row['decision']
                _need(decision in ('confirmed', 'uncertain', 'rejected'), 'invalid candidate decision')
                refs = _refs(row['issue_ids'], known)
                if decision in ('confirmed', 'uncertain'):
                    _need(bool(refs), 'confirmed/uncertain candidate requires actual issue')
                for ident in refs:
                    issue = known[ident]
                    _need(issue['category'] == category and issue['image_id'] == by_region[region_id]['image_id'],
                          'candidate issue category/image mismatch')
                    if decision in ('confirmed', 'uncertain'):
                        _need(issue['decision'] == decision, 'candidate and issue decision mismatch')
                        linked.add(ident)
                        locations.setdefault(ident, set()).add(region_id)
        required = {i for i, issue in known.items() if issue['decision'] in ('confirmed', 'uncertain')}
        _need(required <= linked, 'confirmed/uncertain issue lacks same-category candidate')
        for finding in other['findings']:
            _fields(finding, ('regions', 'decision', 'issue_ids', 'evidence'))
            _regions(finding['regions'], expected)
            _text(finding['evidence'], 'other finding evidence')
            _need(finding['decision'] in ('missed_primary', 'secondary', 'uncertain', 'ignored'), 'invalid other finding decision')
            refs = _refs(finding['issue_ids'], known)
            images = {by_region[r]['image_id'] for r in finding['regions']}
            _need(all(known[i]['image_id'] in images for i in refs), 'other finding issue/image mismatch')
            if finding['decision'] == 'missed_primary':
                _need(bool(refs) and all(known[i]['decision'] == 'confirmed' and
                      locations.get(i, set()) & set(finding['regions']) for i in refs),
                      'missed_primary requires confirmed issue and matching-region candidate')
        report.update(records_complete=True, candidate_links_complete=True,
                      status='declared_itinerary_complete', candidate_count=sum(len(s['candidates']) for s in sweeps),
                      linked_issue_count=len(linked))
    except (ValueError, TypeError, KeyError) as exc:
        report['errors'].append({'code': 'invalid_compact_inspection', 'message': str(exc)})
    return report
