"""Keep detection records independent of repairability and preserve explicit duplicates."""
import xml.etree.ElementTree as ET
from .lean_inspection import CATEGORIES


def effective_issue_rows(history):
    """Retain detection history while allowing evidenced S1 reclassification."""
    current = {}
    for row in history:
        key = (row.get('image_id'), row.get('id'))
        previous = current.get(key)
        if previous and previous.get('decision') == 'confirmed':
            if row.get('category') != previous.get('category'):
                continue
            if row.get('decision') in ('preserved', 'uncertain'):
                if previous.get('category') != 'S1':
                    continue
                review = row.get('source_review')
                expected = 'planar' if row['decision'] == 'preserved' else 'uncertain'
                if (not isinstance(review, dict) or review.get('classification') != expected
                        or not isinstance(review.get('evidence'), str) or not review['evidence'].strip()):
                    continue
            elif row.get('decision') != 'confirmed':
                continue
        current[key] = row
    return list(current.values())


def source_pending_ids(issues, rejected):
    deferred = {ref for row in rejected if row.get('status') == 'deferred_source_geometry'
                for ref in row.get('issue_ids', [])}
    return sorted({i['id'] for i in issues if i.get('category') == 'S1'
                   and (i.get('decision') == 'uncertain'
                        or (i.get('decision') == 'confirmed' and i['id'] in deferred))})


def validate_issues(issues,programs,images):
    known={im:{n.get('id') for n in ET.parse(v['svg']).getroot().iter() if n.get('id')} for im,v in images.items()}
    seen={};attempted={ref for p in programs if isinstance(p,dict) and isinstance(p.get('issue_ids'),list) for ref in p['issue_ids'] if isinstance(ref,str)}
    for row in issues:
        if not isinstance(row,dict):raise ValueError('issue must be object')
        ident=row.get('id');im=row.get('image_id')
        if not isinstance(ident,str) or not ident.strip() or ident in seen or im not in known:raise ValueError('invalid issue identity')
        if row.get('category') not in CATEGORIES:raise ValueError('unknown issue category')
        if row.get('decision') not in ('confirmed','uncertain','preserved','duplicate'):raise ValueError('invalid issue decision')
        for field in ('description','original_evidence','current_evidence'):
            if not isinstance(row.get(field),str) or not row[field].strip():raise ValueError('missing '+field)
        for field in ('target_ids','neighbor_ids'):
            ids=row.get(field)
            if not isinstance(ids,list) or any(not isinstance(i,str) or i not in known[im] for i in ids):raise ValueError('unknown current SVG object')
        if row['decision']=='confirmed' and ident not in attempted and not str(row.get('unresolved_reason','')).strip():
            row['unresolved_reason'] = 'Host record: The model confirmed this issue but submitted neither a corresponding program nor an unresolved_reason; this item remains unresolved.'
            row['host_missing_program']=True
        seen[ident]=row
    for row in issues:
        if row['decision']=='duplicate':
            prior=seen.get(row.get('duplicate_of'),{})
            if prior.get('decision')!='confirmed' or prior.get('image_id')!=row['image_id'] or prior.get('category')!=row['category']:
                raise ValueError('invalid duplicate reference')
    return issues
