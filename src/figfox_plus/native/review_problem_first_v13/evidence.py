"""Validate observable coverage records, never infer visual correctness."""
import re
from collections import Counter

KEYS = ('image_id','pass','category','region_id')
STATES = {'clear','issue','uncertain','not_applicable'}


def _key(row):
    return tuple(row.get(k) for k in KEYS)


def _unit(key):
    return dict(zip(KEYS,key))


def validate_observations(schedule, observations, issues):
    errors = []
    expected = {_key(s):s for s in schedule}
    order = list(expected)
    if not isinstance(observations,list):
        errors.append({"code":"invalid_observations_collection"}); observations=[]
    if not isinstance(issues,list):
        errors.append({"code":"invalid_issues_collection"}); issues=[]
    issues_by_id = {}
    for issue in issues:
        if not isinstance(issue,dict) or not isinstance(issue.get('id'),str):
            errors.append({'code':'invalid_issue'}); continue
        if issue['id'] in issues_by_id:
            errors.append({'code':'duplicate_issue_id','issue_id':issue['id']})
        issues_by_id[issue['id']] = issue
    counts = Counter()
    observed_order = []
    uncertain = []
    referenced = set()
    for index, row in enumerate(observations):
        if not isinstance(row,dict):
            errors.append({'code':'invalid_observation','index':index});continue
        key = _key(row)
        try:
            counts[key] += 1
        except TypeError:
            errors.append({'code':'invalid_unit_key','index':index});continue
        if key not in expected:
            errors.append({'code':'unknown_unit','index':index});continue
        observed_order.append(key)
        spec = expected[key]
        def error(code): errors.append({'code':code,'unit':_unit(key)})
        state = row.get('state')
        if not isinstance(state,str) or state not in STATES: error('invalid_state')
        if state == 'uncertain': uncertain.append(_unit(key))
        if row.get('current_revision') != spec.get('current_revision'): error('revision_mismatch')
        for field in ('original_observation','current_observation'):
            value = row.get(field)
            if not isinstance(value,str) or not value.strip():
                error('missing_'+field)
            elif re.search(r'same as (?:the )?(?:previous|prior)|see (?:the )?(?:previous|prior)|上一轮看过|同上一轮|见上轮',value,re.I):
                error('cross_pass_shortcut')
        evidence = row.get('evidence_assets')
        allowed = set(spec.get('evidence_assets',[]))
        if not isinstance(evidence,list) or any(not isinstance(a,str) for a in evidence):
            error('invalid_evidence_assets')
        elif not set(evidence).issubset(allowed) or not {spec.get('original_asset_id'),spec.get('current_asset_id')}.issubset(evidence):
            error('missing_or_unknown_evidence')
        if state == 'not_applicable' and (not isinstance(row.get('applicability_reason'),str) or not row['applicability_reason'].strip()):
            error('missing_applicability_reason')
        refs = row.get('issue_ids')
        if not isinstance(refs,list) or any(not isinstance(ref,str) for ref in refs):
            error('invalid_issue_references');continue
        if state == 'issue' and not refs: error('issue_without_reference')
        if state in ('clear','not_applicable') and refs: error('clear_with_issue_reference')
        for ref in refs:
            issue = issues_by_id.get(ref)
            if issue is None or issue.get('image_id') != row['image_id']:
                error('unknown_or_wrong_image_issue')
            elif 'category' in issue and issue['category'] != row['category']:
                error('wrong_category_issue')
            else: referenced.add(ref)
    missing = [_unit(k) for k in order if not counts[k]]
    duplicate = [_unit(k) for k,n in counts.items() if n>1]
    if missing: errors.append({'code':'missing_units','count':len(missing)})
    if duplicate: errors.append({'code':'duplicate_units','count':len(duplicate)})
    indexes = [order.index(k) for k in observed_order]
    if indexes != sorted(indexes): errors.append({'code':'inspection_order_mismatch'})
    for issue_id in issues_by_id.keys()-referenced:
        errors.append({'code':'unreferenced_issue','issue_id':issue_id})
    return {'records_complete':not errors,'inspection_complete':not errors and not uncertain,'missing_units':missing,'duplicate_units':duplicate,'uncertain_units':uncertain,'errors':errors,'visual_acceptance':'not_assessed','status':'inspection_complete' if not errors and not uncertain else 'inspection_incomplete'}
