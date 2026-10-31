"""Exact shared detector parser and validator; no inference or normalization."""
import json
import xml.etree.ElementTree as ET

MAIN_CATEGORIES = ('F','E','B','S1','D','S2')
EXTRA_CATEGORIES = ('A','C','S4')
PROFILE_CATEGORIES = MAIN_CATEGORIES + EXTRA_CATEGORIES
SEMANTIC_CATEGORIES = PROFILE_CATEGORIES
PROFILE_ID = 'lean6-semantic-acs4-v2'
def validate_issues(rows, svg):
    if not isinstance(rows,list):raise ValueError('issues must be array')
    ids={n.get('id') for n in ET.parse(svg).getroot().iter() if n.get('id')};seen=set()
    for row in rows:
        if not isinstance(row,dict):raise ValueError('issue must be object')
        ident=row.get('id')
        if not isinstance(ident,str) or not ident.strip() or ident in seen:raise ValueError('missing or duplicate issue id')
        seen.add(ident)
        if row.get('image_id')!='case' or row.get('category') not in PROFILE_CATEGORIES:raise ValueError('invalid image or category')
        if row.get('decision') not in ('confirmed','uncertain'):raise ValueError('invalid issue decision')
        for key in ('description','original_evidence','current_evidence'):
            if not isinstance(row.get(key),str) or not row[key].strip():raise ValueError('missing '+key)
        for key in ('target_ids','neighbor_ids'):
            values=row.get(key)
            if not isinstance(values,list) or len(values)!=len(set(values)) or any(not isinstance(x,str) or x not in ids for x in values):raise ValueError('unknown or duplicate current SVG object')
        if row.get('container_id') is not None and row['container_id'] not in ids:raise ValueError('unknown container id')
        if not row['target_ids'] and not row.get('container_id'):raise ValueError('missing content requires a real container_id')
    return rows




def bound_report(report,state, hashes=True):
    if report.get('revision')!=state['revision']:raise ValueError('stale report revision')
    if hashes and report.get('evidence_hashes')!=state['evidence_hashes']:raise ValueError('stale report evidence hashes')
    if hashes:
        known=set(state['required_regions'])
        for field in ('examined_regions','unresolved_regions'):
            if not isinstance(report.get(field),list):raise ValueError(field+' required')
            if any(not isinstance(x,str) or x not in known for x in report[field]) or len(report[field])!=len(set(report[field])):raise ValueError('unknown or duplicate region id')
        return sorted(known-set(report['examined_regions'])-set(report['unresolved_regions']))


def validate_detection_report(raw, role, state, svg, *, proposals=None):
    if role not in ('main','semantic'):raise ValueError('detector role must be main or semantic')
    report=json.loads(raw)
    if not isinstance(report,dict):raise ValueError('report must be object')
    missing=bound_report(report,state)
    if report.get('programs')!=[]:raise ValueError('detection programs must be empty')
    validate_issues(report.get('issues'),svg)
    allowed=MAIN_CATEGORIES if role=='main' else SEMANTIC_CATEGORIES
    if any(row['category'] not in allowed for row in report['issues']):raise ValueError('category outside frozen role profile')
    if role=='semantic' and proposals is not None:
        validate_proposal_reviews(report,proposals,state)
    return report,missing


def validate_proposal_reviews(report, proposals, state):
    if proposals.get('format')!='svg-observation-proposals-v1' or proposals.get('status')!='ready' or proposals.get('revision')!=state['revision']:
        raise ValueError('observation proposals must bind current ready revision')
    known=proposal_catalog(proposals)
    reviews=report.get('proposal_reviews')
    if not isinstance(reviews,list):raise ValueError('proposal_reviews required')
    issues={row['id']:row for row in report['issues']}
    if set(issues)&known:raise ValueError('proposal ID is not a native finding ID')
    seen=set()
    for review in reviews:
        if not isinstance(review,dict) or not isinstance(review.get('proposal_id'),str) or review['proposal_id'] not in known or review['proposal_id'] in seen:raise ValueError('unknown or duplicate proposal review')
        seen.add(review['proposal_id'])
        if review.get('decision') not in ('required','uncertain','qualified'):raise ValueError('invalid proposal decision')
        for field in ('source_evidence','current_evidence','necessity_reason'):
            if not isinstance(review.get(field),str) or not review[field].strip():raise ValueError('proposal review requires '+field)
        links=review.get('issue_ids')
        if not isinstance(links,list) or any(not isinstance(i,str) or i not in issues for i in links) or len(links)!=len(set(links)):raise ValueError('proposal links must use reported native issue IDs')
        decision=review['decision']
        if decision=='required' and (not links or any(issues[i]['decision']!='confirmed' for i in links)):raise ValueError('required proposal links confirmed issues')
        if decision=='uncertain' and (not links or any(issues[i]['decision']!='uncertain' for i in links)):raise ValueError('uncertain proposal requires at least one uncertain native issue')
        if decision=='qualified' and links:raise ValueError('qualified proposal grants no issue or repair authority')
    if seen!=known:raise ValueError('proposal_reviews must exactly partition proposal IDs')


def proposal_catalog(proposals):
    proposals_rows=proposals.get('proposals')
    if not isinstance(proposals_rows,list) or any(not isinstance(p,dict) or not isinstance(p.get('id'),str) or not p['id'].strip() for p in proposals_rows):raise ValueError('invalid proposal IDs')
    known={p['id'] for p in proposals_rows}
    if len(known)!=len(proposals_rows):raise ValueError('duplicate proposal IDs')
    return known
