"""Coverage proves reporting completeness only, never absence of visual defects."""
CATEGORIES=('typesetting','content','overlap','overflow','alignment','relative_size','planar_shape','arrow_geometry','arrow_route','fill_spill','missing','color','count','geometry')

def audit(response,frames,ids):
    issues=response.get('issues',[]);ops=response.get('ops',[]);byissue={i['id']:i for i in issues}
    if len(byissue)!=len(issues):raise ValueError('duplicate issue ID')
    for i in issues:
        if i.get('category') not in (*CATEGORIES,'unknown'):raise ValueError('issue category missing/unknown')
        if not i.get('target_ids') or not set(i['target_ids'])<=ids:raise ValueError('issue '+str(i.get('id'))+' needs existing semantic targets; unknown='+str(set(i.get('target_ids',[]))-ids))
        if not all(i.get(k) for k in ('description','original_evidence','current_evidence')):raise ValueError('issue needs original/current evidence and semantic description')
        if not i.get('op_ids') and not i.get('unresolved_reason'):raise ValueError('issue missing execution or unresolved reason')
    # Classification is supplied by the VLM, never inferred from SVG node counts.
    opids=set()
    for o in ops:
        if o['id'] in opids:raise ValueError('duplicate op ID')
        opids.add(o['id']);i=byissue.get(o.get('issue_id'))
        if not i or o['id'] not in i.get('op_ids',[]):raise ValueError('operation '+str(o.get('id'))+' not bound to issue '+str(o.get('issue_id')))
        if not set(o.get('depends_on',[]))<=opids-{o['id']}:raise ValueError('invalid dependency order')
    if any(not set(i.get('op_ids',[]))<=opids for i in issues):raise ValueError('issue refers to missing operation')
    for i in issues:
        if i.get('category')!='geometry':continue
        cls=i.get('object_class')
        if cls not in ('single_geometry','rubiks_cube','complex_geometry','abstract'):raise ValueError('geometry issue '+i['id']+' must classify object_class before choosing SP or vector asset')
        if cls in ('complex_geometry','abstract'):
            if any(o['action'] in ('sp','svg') for o in ops if o.get('issue_id')==i['id']):raise ValueError('complex geometry/abstract reconstruction must use asset with vector classification, not SP/svg')
    return coverage_audit(response,frames)


def coverage_audit(response,frames):
    issues=response.get('issues',[])
    regions={f['frame_id'] for f in frames}|{'full'};coverage={c['frame_id']:c for c in response.get('coverage',[])}
    for entry in coverage.values():
        if isinstance(entry.get('states'),str) and len(entry['states'])==len(CATEGORIES):
            entry['categories']={c:{'C':'checked','I':'issue','U':'uncertain','N':'not_applicable'}.get(v) for c,v in zip(CATEGORIES,entry['states'])}
    missing=[]
    for region in sorted(regions):
        entry=coverage.get(region,{})
        if not entry.get('evidence'):missing.append([region,'region evidence'])
        for category in CATEGORIES:
            state=(entry.get('categories',{}) if isinstance(entry.get('categories',{}),dict) else {}).get(category)
            if state not in ('checked','issue','uncertain','not_applicable'):missing.append([region,category])
            if state=='issue' and not any(i.get('category')==category and i.get('frame_id')==region for i in issues):missing.append([region,category,'missing issue'])
    return {'reporting_complete':not missing,'missing':missing,'regions':len(regions),'categories':len(CATEGORIES),'visual_passed':False,'warning':'A complete checklist is not evidence that VLM found every defect.'}


def normalize(response):
    """Bind nested issue operations mechanically; never infer numerical answers."""
    from copy import deepcopy
    if not isinstance(response,dict):raise ValueError('response must be JSON object')
    r=deepcopy(response)
    for key in ('issues','coverage'):
        if not isinstance(r.get(key),list) or any(not isinstance(v,dict) for v in r[key]):raise ValueError(key+' must be list of objects')
    nested=any('ops' in i for i in r['issues'])
    if nested and r.get('ops'):raise ValueError('use either nested issue ops or legacy global ops, not both')
    if nested:
        r['ops']=[]
        for number,i in enumerate(r['issues']):
            i.setdefault('id',f'issue_{number}');local=i.pop('ops',[])
            if not isinstance(local,list):raise ValueError('issue.ops must be list')
            i['op_ids']=[]
            for j,o in enumerate(local):
                if not isinstance(o,dict):raise ValueError('operation must be object')
                o.setdefault('id',f'{i["id"]}_op_{j}');o['issue_id']=i['id'];i['op_ids'].append(o['id']);r['ops'].append(o)
    r.setdefault('ops',[])
    if not isinstance(r['ops'],list) or any(not isinstance(o,dict) for o in r['ops']):raise ValueError('ops must be list of objects')
    for row in r['coverage']:
        if isinstance(row.get('categories'),str):row['states']=row.pop('categories')
    return r
