"""Problem-first inspection; host changes encoding, never supplies observations."""
from copy import deepcopy
from .inspection_contract import CATEGORIES, inspection_regions, expand_observations, _CHECK, _text, audit_inspection

PROMPT = '''Chain the inspection by problem type; do not browse the whole image casually first and then pick a few easy-to-fix problems.
Fixed main order: E Alignment -> F Overlap / Flush to Edge / Overflow -> B Fonts and Formulas -> A Knowledge Content, Semantic Icons and Arrow Connections -> S1 Obvious Geometry Errors.
In the first request, complete the whole itinerary below for one category before entering the next: original PNG against current PNG; check the current SVG together with the original figure; verify the whole-image current TP and structural candidates relevant to this category; review every existing paired Crop one by one; then run the same batch of Crops once more for omission checks and counter-evidence. Upstream Crops are already finished; do not re-crop around suspicions to replace them. Every category must be looked at from start to finish, and cannot be substituted by having been seen under another category. In the second request, if the host confirms the first records are complete, only re-verify each issue against the new whole image and supply corrective programs; there is no need to resubmit the earlier three-pass records. If the first records are incomplete, they must still be completed from the initial assets; old Crops must not pass off as evidence of the newer image after repair.
For E, first identify the bound whole, the reference axis, group symmetry and corresponding heights, then compare members and neighbors. For F, check actual edges, clearance and containers object by object; TP intersection is only a candidate; normal containment and overlaps intentional in the original figure are not reported. For B, check glyph order, symbols, sub/superscripts and legibility; do not single out only subtle font differences. For A, follow every connection from its start to its end and verify direction, head count, shaft, connection and missing items; also verify the identity of the object each semantic icon represents. For S1, check whether faces, edges and vertices can form a plausible object, the length-width-depth relations, the combination order and local garbled lines; ordinary schematic waveforms, textures or style differences are not geometric damage. An original photo turned into invented geometry must also be confirmed.
If upstream_arrow_evidence is present, first use upstream SAM to lock arrow candidates, then verify once more against this round's original and current images. SAM misses detections and may recognize letters as arrows; it is not the answer. Original asset coordinates are used only for original-figure candidates; current-render positions are still determined independently from semantics and SVG/TP. When no SAM is provided, state plainly that only current evidence was used.
For each category output one entry in category_sweeps, giving records in category_itinerary order. Each region binds a host region and contains state, original_observation, current_observation, issue_ids; E/F also add candidate_check, and the first whole-image pass of each category adds svg_observation. Give only short verifiable observations; do not output internal reasoning. Write uncertain when not sure; do not fabricate, and do not substitute "normal / same as above".
Finally, other_sweep scans once more for missing items and remaining problems: examined_regions covers all regions; each findings entry gives regions, decision (missed_primary|secondary|uncertain|ignored), issue_ids and evidence. Confirmed primary omissions are added to the existing five issue categories and referenced in the corresponding main-category record; secondary differences keep an explanation but must not replace the main issue. When there are no extra findings, findings may be empty and a summary is given. Do not pre-dismiss real omissions, and do not manufacture errors to inflate a count.
Evaluate discovery and repair separately; do not withhold a report because you do not know how to fix it. For localization, first state the subject, the object and the surrounding relations, then bind current-render IDs. TP applies only to the current render and cannot be used to locate the original. Keep the full method library, generated dynamic code, dependency order and actual RCD. Complete records within one output only prove that evidence was submitted; they cannot claim that no omission has been proven.'''

def category_itinerary(schedule):
    regions=inspection_regions(schedule)
    return [{'category':c,'regions':deepcopy(regions)} for c in CATEGORIES]

def expand_category_sweeps(plan, schedule):
    regions=inspection_regions(schedule)
    sweeps=plan.get('category_sweeps')
    if not isinstance(sweeps,list) or [s.get('category') for s in sweeps]!=list(CATEGORIES):
        raise ValueError('category order must be E F B A S1')
    expected=[r['region'] for r in regions]
    combined={r['region']:{'region':r['region'],'checks':{}} for r in regions}
    for sweep in sweeps:
        records=sweep.get('records');category=sweep['category']
        if not isinstance(records,list) or [r.get('region') for r in records]!=expected:
            raise ValueError('region coverage or order incomplete')
        for row, region in zip(records,regions):
            entry=deepcopy(row);entry.pop('region')
            svg=entry.pop('svg_observation',None)
            if region['pass']==1:
                if not isinstance(svg,str) or not svg.strip():raise ValueError('missing SVG observation')
                _text(svg,'svg_observation')
                target=combined[region['region']]
                target['svg_observation']=target.get('svg_observation','')+category+': '+svg+'\n'
            combined[region['region']]['checks'][category]=entry
    other=plan.get('other_sweep',{})
    if other.get('examined_regions')!=expected or not isinstance(other.get('summary'),str) or not other['summary'].strip():
        raise ValueError('other sweep requires region coverage and summary')
    _text(other['summary'],'other summary')
    findings=other.get('findings')
    if not isinstance(findings,list):raise ValueError('other findings required')
    known={i['id']:i for i in plan.get('issues',[])}
    for item in findings:
        if item.get('decision') not in ('missed_primary','secondary','uncertain','ignored') or not isinstance(item.get('evidence'),str):
            raise ValueError('other finding requires decision and evidence')
        _text(item['evidence'],'other finding evidence')
        ids=item.get('issue_ids');where=item.get('regions')
        if not isinstance(where,list) or not where or any(x not in expected for x in where):raise ValueError('other region invalid')
        if not isinstance(ids,list) or any(i not in known for i in ids):raise ValueError('other issue reference invalid')
        if item['decision']=='missed_primary' and (not ids or any(known[i].get('decision')!='confirmed' for i in ids)):
            raise ValueError('missed primary requires confirmed issue')
        if item['decision']=='missed_primary':
            for ident in ids:
                cat=known[ident].get('category')
                if cat not in CATEGORIES or not any(ident in combined[r]['checks'][cat]['issue_ids'] for r in where):
                    raise ValueError('missed primary must be linked to its region and category observation')
    out=deepcopy(plan);out['inspection_records']=[combined[i] for i in expected]
    expand_observations(out,schedule)
    return out

def audit_problem_first(schedule,plan,issues):
    return audit_inspection(schedule,expand_category_sweeps(plan,schedule),issues)

_record=deepcopy(_CHECK)
_record['properties'].update(region={'type':'integer','minimum':0},svg_observation={'type':'string'})
_record['required'].append('region')
SCHEMA={
 'category_sweeps':{'type':'array','minItems':5,'maxItems':5,'items':{
     'type':'object','properties':{'category':{'enum':list(CATEGORIES)},'records':{'type':'array','items':_record}},
     'required':['category','records'],'additionalProperties':False}},
 'other_sweep':{'type':'object','properties':{
     'examined_regions':{'type':'array','items':{'type':'integer'}},
     'summary':{'type':'string'},'findings':{'type':'array','items':{
        'type':'object','properties':{'regions':{'type':'array','items':{'type':'integer'}},
        'decision':{'enum':['missed_primary','secondary','uncertain','ignored']},
        'issue_ids':{'type':'array','items':{'type':'string'}},'evidence':{'type':'string'}},
        'required':['regions','decision','issue_ids','evidence'],'additionalProperties':False}}},
     'required':['examined_regions','summary','findings'],'additionalProperties':False}}
