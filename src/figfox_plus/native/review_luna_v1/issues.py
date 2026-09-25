"""Keep detection records independent of repairability and preserve explicit duplicates."""
import xml.etree.ElementTree as ET
from .inspection import CATEGORIES


def validate_issues(issues,programs,images):
    known={im:{n.get('id') for n in ET.parse(v['svg']).getroot().iter() if n.get('id')} for im,v in images.items()}
    seen={};attempted={ref for p in programs for ref in p.get('issue_ids',[])}
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
            raise ValueError('confirmed issue needs program or unresolved_reason')
        seen[ident]=row
    for row in issues:
        if row['decision']=='duplicate':
            prior=seen.get(row.get('duplicate_of'),{})
            if prior.get('decision')!='confirmed' or prior.get('image_id')!=row['image_id'] or prior.get('category')!=row['category']:
                raise ValueError('invalid duplicate reference')
    return issues
