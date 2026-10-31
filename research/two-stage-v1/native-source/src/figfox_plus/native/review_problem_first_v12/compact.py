"""Lossless wire expansion of explicit per-unit observations.

Only invariant fields already bound by the host schedule are restored. No state,
observation text, applicability claim, or issue reference is guessed or filled.
This reduces repeated keys, not the required inspection coverage or visual work.
The caller must run validate_observations on the expanded result.
"""
from copy import deepcopy
import re

ROW_KEYS = {'image_id','pass','category','states','evidence_ids','issue_ids'}
EVIDENCE_KEYS = {'original_observation','current_observation','applicability_reason'}
STATES = {'C':'clear','I':'issue','U':'uncertain','N':'not_applicable'}
GROUP_KEYS = ('image_id','pass','category')
RESTORED_KEYS = ('image_id','pass','category','region_id','current_revision','evidence_assets')
GENERIC = re.compile(r'(?:done|checked|ok|clear|normal|same|no\s+(?:issue|issues|problem|problems|defects)|检查完成|已检查|完成|无问题|正常|同上)[.!。！\s]*',re.I)
SHORTCUT = re.compile(r'same as (?:the )?(?:previous|prior)|see (?:the )?(?:previous|prior)|上一轮看过|同上一轮|见上轮|沿用上轮',re.I)


def _fail(message):
    raise ValueError('invalid_compact_observations: '+message)


def _text(value, label):
    if not isinstance(value,str) or not value.strip():
        _fail(label+' must contain explicit observation text')
    if GENERIC.fullmatch(value.strip()) or SHORTCUT.search(value):
        _fail(label+' cannot be generic completion or a previous-pass reference')
    return value


def expand_observations(plan, schedule):
    """Expand compact rows, or deep-copy the existing verbose observations array.

    Compact row order is exactly schedule group order; array positions within
    each row are exactly that group's schedule region order. Every evidence ID
    must exist, and every supplied evidence dictionary entry must be referenced.
    """
    if not isinstance(plan,dict):_fail('plan must be an object')
    compact_present='observation_rows' in plan or 'observation_evidence' in plan
    if 'observations' in plan:
        if compact_present:_fail('mixed verbose and compact forms are ambiguous')
        if not isinstance(plan['observations'],list):_fail('observations must be an array')
        return deepcopy(plan['observations'])
    rows=plan.get('observation_rows');evidence=plan.get('observation_evidence')
    if not isinstance(rows,list) or not isinstance(evidence,dict):
        _fail('observation_rows and observation_evidence are both required')
    if not isinstance(schedule,list):_fail('schedule must be an array')
    groups=[];seen_groups=set();seen_units=set()
    for unit in schedule:
        if not isinstance(unit,dict) or any(k not in unit for k in RESTORED_KEYS):_fail('invalid host schedule')
        group=tuple(unit[k] for k in GROUP_KEYS)
        key=group+(unit['region_id'],)
        try:
            if key in seen_units:_fail('duplicate host schedule unit')
            seen_units.add(key)
            if not groups or group!=groups[-1][0]:
                if group in seen_groups:_fail('noncontiguous host schedule group')
                seen_groups.add(group);groups.append((group,[]))
        except TypeError:_fail('invalid host schedule identity')
        groups[-1][1].append(unit)
    if len(rows)!=len(groups):_fail('row count does not match complete host schedule')
    for evidence_id,item in evidence.items():
        if not isinstance(evidence_id,str) or not evidence_id.strip():_fail('evidence identity must be nonempty text')
        if not isinstance(item,dict) or set(item)-EVIDENCE_KEYS:_fail('invalid evidence entry fields')
        _text(item.get('original_observation'),'original_observation')
        _text(item.get('current_observation'),'current_observation')
        if 'applicability_reason' in item:_text(item['applicability_reason'],'applicability_reason')
    expanded=[];used=set()
    for row,(identity,units) in zip(rows,groups):
        if not isinstance(row,dict) or set(row)!=ROW_KEYS:_fail('each row must contain exactly the six wire fields')
        if tuple(row[k] for k in GROUP_KEYS)!=identity:_fail('row identity/order differs from host schedule')
        states=row['states'];eids=row['evidence_ids'];refs=row['issue_ids'];size=len(units)
        if not isinstance(states,str) or len(states)!=size or any(c not in STATES for c in states):_fail('states must explicitly encode every unit with C/I/U/N')
        if not isinstance(eids,list) or len(eids)!=size:_fail('evidence_ids length must match every unit')
        if not isinstance(refs,list) or len(refs)!=size:_fail('issue_ids length must match every unit')
        for index,unit in enumerate(units):
            eid=eids[index];issue_ids=refs[index]
            if not isinstance(eid,str) or eid not in evidence:_fail('unknown or missing evidence identity')
            if not isinstance(issue_ids,list) or any(not isinstance(i,str) or not i.strip() for i in issue_ids):_fail('every unit needs an explicit issue ID array')
            if len(set(issue_ids))!=len(issue_ids):_fail('duplicate issue reference in unit')
            item={key:deepcopy(unit[key]) for key in RESTORED_KEYS}
            item.update(deepcopy(evidence[eid]))
            item.update(state=STATES[states[index]],issue_ids=deepcopy(issue_ids))
            expanded.append(item);used.add(eid)
    if used!=set(evidence):_fail('unreferenced evidence entries are not accepted')
    return expanded
