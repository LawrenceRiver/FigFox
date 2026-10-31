"""Lossless discovery merge and conservative, offline repair scheduling.

Rows are never semantically deduplicated. Connected read/write components are
indivisible; a deterministic exhaustive two-bin search admits complete wires.
"""
from copy import deepcopy
import hashlib
import itertools
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from .capacity_partition import (CATEGORIES, CapacityError, close_evidence,
                                 select_messages, write_json, _strings,
                                 plan_capacity_context)


def _namespace_payload(payload, branch):
    issues = {r['id']:branch+'::'+r['id'] for r in payload['issues']}
    observations = {r['id']:branch+'::'+r['id'] for r in payload['observations']}
    def walk(value, key=None):
        mapping = issues if key in ('issue_id','issue_ids','duplicate_of','conflicts_with') else observations if key in ('observation_id','observation_ids') else None
        if mapping is not None:
            if isinstance(value,str):
                if value not in mapping: raise ValueError('unknown '+str(key)+' reference: '+value)
                return mapping[value]
            if isinstance(value,list): return [walk(v,key) for v in value]
            raise ValueError('invalid '+str(key)+' reference')
        if isinstance(value,dict): return {k:walk(v,k) for k,v in value.items()}
        if isinstance(value,list): return [walk(v) for v in value]
        return deepcopy(value)
    result = walk(payload)
    for field,mapping in [('issues',issues),('observations',observations)]:
        for row in result[field]:
            local = row['id']; row.update(id=mapping[local],local_id=local,origin_branch=branch)
    return result


def validate_branch_result(branch_id, message, branch_plan):
    """Accept one fully finished tool payload, retaining raw responses even on error.

    `message` is either a raw provider response with choices, or the explicit
    {finish_reason, message} choice. A bare assistant message has insufficient
    completion provenance. Unknown localization and unresolved pairs are valid
    data; absent/malformed branch coverage is not.
    """
    result = {'branch_id':branch_id,'raw':deepcopy(message),'raw_payload':None,'normalized':None,'valid':False,'errors':[]}
    try:
        if branch_id not in ('A','B'): raise ValueError('unknown branch')
        if not isinstance(message,dict) or message.get('error'): raise ValueError('invalid provider response')
        if 'choices' in message:
            if not isinstance(message['choices'],list) or len(message['choices']) != 1: raise ValueError('expected exactly one response choice')
            choice = message['choices'][0]
        else: choice = message
        if not isinstance(choice,dict): raise ValueError('response choice must be object')
        if choice.get('finish_reason') not in ('stop','tool_calls'): raise ValueError('incomplete or unknown finish state')
        assistant = choice.get('message')
        if not isinstance(assistant,dict) or assistant.get('role')!='assistant': raise ValueError('expected assistant message')
        calls = assistant.get('tool_calls')
        if not isinstance(calls,list) or len(calls)!=1: raise ValueError('exactly one discovery tool call required')
        call = calls[0]
        if not isinstance(call,dict): raise ValueError('discovery tool call must be object')
        function = call.get('function')
        if not isinstance(function,dict): raise ValueError('discovery tool function must be object')
        if not isinstance(call.get('id'),str) or not call['id'] or call.get('type')!='function' or function.get('name')!='submit_capacity_discovery': raise ValueError('invalid discovery tool')
        text = function.get('arguments')
        if not isinstance(text,str): raise ValueError('discovery arguments must be JSON text')
        def unique(pairs):
            obj={}
            for k,v in pairs:
                if k in obj: raise ValueError('duplicate JSON key: '+k)
                obj[k]=v
            return obj
        payload = json.loads(text,object_pairs_hook=unique,parse_constant=lambda s: (_ for _ in ()).throw(ValueError('nonfinite JSON literal')))
        result['raw_payload'] = deepcopy(payload)
        if not isinstance(payload,dict): raise ValueError('discovery payload must be object')
        for field in ('observations','issues'):
            rows = payload.get(field)
            if not isinstance(rows,list): raise ValueError('missing '+field)
            ids=[]
            for row in rows:
                if not isinstance(row,dict) or not isinstance(row.get('id'),str) or not row['id']: raise ValueError('invalid '+field+' identity')
                ids.append(row['id'])
                if field=='issues': _strings(row.get('target_ids'), 'target_ids')
                if field=='observations': _strings(row.get('issue_ids'), 'issue_ids')
            if len(set(ids)) != len(ids): raise ValueError('duplicate '+field+' identity')
        inspected = _strings(payload.get('inspected_pair_ids'),'inspected_pair_ids')
        unresolved = _strings(payload.get('unresolved_pair_ids'),'unresolved_pair_ids')
        expected = set(branch_plan['assignment']['pair_ids'])
        if inspected & unresolved or inspected | unresolved != expected: raise ValueError('branch pair coverage incomplete or contradictory')
        coverage = payload.get('category_coverage')
        if not isinstance(coverage,dict) or set(coverage)!=set(CATEGORIES) or any(v not in ('inspected','unresolved') for v in coverage.values()): raise ValueError('category coverage incomplete')
        if payload.get('programs'): raise ValueError('discovery cannot include repair programs')
        result['normalized'] = _namespace_payload(payload,branch_id)
        result.update(valid=True, mechanical_coverage={'expected_pair_ids':sorted(expected),'inspected_pair_ids':sorted(inspected),'unresolved_pair_ids':sorted(unresolved),'category_coverage':deepcopy(coverage),'visual_inspection_proven':False})
    except (ValueError,TypeError,KeyError) as exc:
        result['errors'].append(str(exc))
    return result


def merge_branch_results(results, source_plan):
    """Merge every normalized row; retain invalid/raw branches and missing coverage."""
    expected = set(source_plan['branches'])
    errors = []
    if set(results)!=expected: errors.append('missing or unexpected discovery branches')
    merged = {'raw_results':{b:deepcopy(r.get('raw')) for b,r in sorted(results.items())},'branch_results':deepcopy(results),'observations':[],'issues':[],'possible_duplicates':[],'conflicts':[],'errors':errors,'mechanical_coverage':{},'visual_inspection_proven':False}
    for branch,result in sorted(results.items()):
        if not result.get('valid') or result.get('branch_id')!=branch:
            errors.append('invalid discovery branch '+branch); continue
        payload = result['normalized']
        for field in ('observations','issues'): merged[field].extend(deepcopy(payload[field]))
        merged['mechanical_coverage'][branch] = deepcopy(result['mechanical_coverage'])
    for field in ('observations','issues'):
        for left,right in itertools.combinations(merged[field],2):
            ids = [left['id'],right['id']]
            targets = set(left.get('target_ids',[])) & set(right.get('target_ids',[]))
            equal_text = isinstance(left.get('description'),str) and bool(left['description']) and left['description']==right.get('description')
            if equal_text or targets:
                merged['possible_duplicates'].append({'row_type':field,'ids':ids,'basis':'identical_description' if equal_text else 'overlapping_targets','deduplicated':False})
            if (targets or equal_text) and left.get('decision')!=right.get('decision'):
                merged['conflicts'].append({'row_type':field,'ids':ids,'decisions':[left.get('decision'),right.get('decision')],'basis':'mechanical candidate; requires explicit model disposition','resolved':False})
    merged['ready_for_repair'] = not errors
    return merged


def _svg_graph(svg_path):
    raw=Path(svg_path).read_bytes(); root=ET.fromstring(raw)
    by={n.get('id'):n for n in root.iter() if n.get('id')}
    if len(by)!=len([n for n in root.iter() if n.get('id')]): raise ValueError('duplicate SVG IDs')
    parents={child:parent for parent in root.iter() for child in parent}
    descendants={ident:{n.get('id') for n in node.iter() if n.get('id')} for ident,node in by.items()}
    ancestors={}; ancestor_nodes={}
    for ident,node in by.items():
        values=set(); nodes=[]
        while node in parents:
            node=parents[node]
            nodes.append(node)
            if node.get('id'): values.add(node.get('id'))
        ancestors[ident]=values
        ancestor_nodes[ident]=nodes
    refs={}
    for ident,node in by.items():
        values=set()
        # Anonymous containers also supply inherited fill, clipping, masks and
        # filters. Walk actual elements, not only the named ancestor ID ledger.
        for descendant in list(node.iter()) + ancestor_nodes[ident]:
            for key,value in descendant.attrib.items():
                values.update(re.findall(r'url\(\s*[\"\']?#([^\s)\"\']+)',value))
                if key.rsplit('}',1)[-1]=='href' and value.startswith('#'): values.add(value[1:])
        refs[ident]=values
    global_unknown=any(n.tag.rsplit('}',1)[-1] in ('style','script','animate','animateTransform') for n in root.iter())
    return by,descendants,ancestors,refs,global_unknown,hashlib.sha256(raw).hexdigest()


def _scope(issue, graph):
    by,desc,anc,refs,global_unknown,_=graph
    targets=issue.get('target_ids'); neighbors=issue.get('neighbor_ids',[]); explicit=issue.get('read_ids',[])
    unknown=global_unknown
    if not isinstance(targets,list) or not targets or any(not isinstance(x,str) or x not in by for x in targets): unknown=True
    if any(not isinstance(v,list) or any(not isinstance(x,str) or x not in by for x in v) for v in (neighbors,explicit)): unknown=True
    if issue.get('scope_unknown') is True: unknown=True
    writes=set(); reads=set()
    for ident in targets if isinstance(targets,list) else []:
        if isinstance(ident,str) and ident in by: writes.update(desc[ident]); reads.update(anc[ident])
    for ident in (neighbors if isinstance(neighbors,list) else [])+(explicit if isinstance(explicit,list) else []):
        if isinstance(ident,str) and ident in by: reads.update(desc[ident]); reads.update(anc[ident])
    pending=list(writes|reads); seen=set()
    while pending:
        ident=pending.pop()
        if ident in seen: continue
        seen.add(ident)
        for ref in refs.get(ident,()):
            if ref not in by: unknown=True; continue
            new=desc[ref]|anc[ref]
            reads.update(new);pending.extend(new-seen)
    return writes,reads,unknown


def _evidence(issue, plan, fallback_log):
    branch=issue.get('origin_branch'); known=plan['branches']
    if branch not in known: raise ValueError('issue missing valid originating branch')
    assets=set(); reason=[]
    pair_ids=issue.get('evidence_pair_ids',[]); asset_ids=issue.get('evidence_asset_ids',[])
    if not isinstance(pair_ids,list) or any(not isinstance(p,str) or p not in plan['pairs'] for p in pair_ids): reason.append('invalid pair references')
    else:
        for pid in pair_ids: assets.update(plan['pairs'][pid]['asset_ids'])
    if not isinstance(asset_ids,list) or any(not isinstance(a,str) or a not in plan['image_asset_ids'] for a in asset_ids): reason.append('invalid asset references')
    else: assets.update(asset_ids)
    if not pair_ids and not asset_ids: reason.append('absent evidence references')
    # Geometry comes only from explicit current-scene bounds supplied by the caller.
    # Explicit read objects need comparison evidence just like write/neighbor
    # objects. Any missing required bound retains the full originating branch.
    bounds=plan.get('node_bounds',{})
    targets=issue.get('target_ids',[])+issue.get('neighbor_ids',[])+issue.get('read_ids',[])
    if not targets or any(t not in bounds for t in targets): reason.append('target geometry unavailable')
    else:
        for pair in plan['pairs'].values():
            box=pair.get('display_mapping',{}).get('current')
            if not isinstance(box,list) or len(box)!=4: reason.append('pair geometry unavailable');continue
            for target in targets:
                bound=bounds[target]
                if not isinstance(bound,list) or len(bound)!=4: reason.append('target geometry unavailable');continue
                if bound[0] <= box[2] and box[0] <= bound[2] and bound[1] <= box[3] and box[1] <= bound[3]: assets.update(pair['asset_ids'])
    if reason:
        assets.update(known[branch]['asset_ids'])
        fallback_log.append({'issue_id':issue['id'],'origin_branch':branch,'reasons':sorted(set(reason)),'fallback_asset_ids':deepcopy(known[branch]['asset_ids'])})
    return set(close_evidence(plan,assets))


def _hazards(left,right):
    if left['unknown_scope'] or right['unknown_scope']: return ['unknown_scope']
    lw,lr=set(left['write_ids']),set(left['read_ids']); rw,rr=set(right['write_ids']),set(right['read_ids'])
    return sorted((lw & (rw|rr)) | (rw & lr))


def plan_repair_components(merged, svg_path, evidence_plan):
    """One conservative dependency graph covering every issue and observation.

    Target subtrees are writes; ancestors, neighbors, explicit reads and recursive
    SVG references are reads. Unknown scope connects to every unit. Shared reads
    alone do not connect. Unknown CSS/dynamic scope serializes the whole scene.
    """
    if not merged.get('ready_for_repair'): raise ValueError('incomplete discovery blocks repair planning')
    graph=_svg_graph(svg_path); revision=graph[-1]
    revisions={v['current_revision'] for v in evidence_plan['context']['images'].values()}
    if revisions!={revision}: raise ValueError('repair planning requires one exact bound scene revision')
    issues=deepcopy(merged['issues']); observations=deepcopy(merged['observations']); fallbacks=[]; units=[]
    if len({i['id'] for i in issues})!=len(issues): raise ValueError('duplicate merged issue identity')
    linked=set()
    for issue in issues:
        writes,reads,unknown=_scope(issue,graph)
        owned=[o for o in observations if issue['id'] in o.get('issue_ids',[])]
        linked.update(o['id'] for o in owned)
        assets=_evidence(issue,evidence_plan,fallbacks)
        for observation in owned:
            owrites,oreads,ounknown=_scope(observation,graph)
            writes.update(owrites);reads.update(oreads);unknown=unknown or ounknown
            assets.update(_evidence(observation,evidence_plan,fallbacks))
        units.append({'issue_ids':[issue['id']],'issues':[issue],'observation_ids':[o['id'] for o in owned],'observations':owned,'write_ids':sorted(writes),'read_ids':sorted(reads),'unknown_scope':unknown,'evidence_asset_ids':sorted(assets)})
    unlinked=[o for o in observations if o['id'] not in linked]
    for observation in unlinked:
        # A missing issue link does not erase explicit localization. Use the
        # exact same conservative potential-write/read and evidence closure as
        # issues, regardless of preserve/equivalent/outside-scope disposition.
        # Actually unlocalized or dynamic scope still connects globally.
        writes,reads,unknown=_scope(observation,graph)
        units.append({'issue_ids':[],'issues':[],'observation_ids':[observation['id']],
                      'observations':[observation],'write_ids':sorted(writes),'read_ids':sorted(reads),
                      'unknown_scope':unknown,'evidence_asset_ids':sorted(_evidence(observation,evidence_plan,fallbacks))})
    parent=list(range(len(units))); edges=[]
    def find(i):
        while parent[i]!=i: i=parent[i]
        return i
    for i,j in itertools.combinations(range(len(units)),2):
        hazard=_hazards(units[i],units[j])
        left=set(units[i]['issue_ids']+units[i]['observation_ids'])
        right=set(units[j]['issue_ids']+units[j]['observation_ids'])
        if left & right:
            hazard.append('shared_observation_responsibility')
        if any(set(conflict['ids']) & left and set(conflict['ids']) & right
               for conflict in merged.get('conflicts',[])):
            hazard.append('unresolved_discovery_conflict')
        if hazard:
            parent[find(j)]=find(i); edges.append({'left':i,'right':j,'hazards':hazard})
    groups={}
    for i,unit in enumerate(units): groups.setdefault(find(i),[]).append(unit)
    components=[]
    for index,group in enumerate(groups.values()):
        component={'id':f'component-{index:04d}','unknown_scope':any(u['unknown_scope'] for u in group)}
        for key in ('issue_ids','observation_ids','write_ids','read_ids','evidence_asset_ids'):
            component[key]=sorted({v for u in group for v in u[key]})
        component['issues']=[i for u in group for i in u['issues']]
        obs={o['id']:o for u in group for o in u['observations']}
        component['observations']=[obs[i] for i in component['observation_ids']]
        component['origin_branches']=sorted({r['origin_branch'] for r in component['issues']+component['observations']})
        components.append(component)
    return {'base_revision':revision,'components':components,'dependency_edges':edges,'evidence_fallbacks':fallbacks,'conflicts':deepcopy(merged.get('conflicts',[])),'all_issue_ids':[i['id'] for i in issues],'all_observation_ids':[o['id'] for o in observations],'visual_acceptance':'not_assessed'}


def _repair_tools():
    return [{'type':'function','function':{'name':'submit_capacity_repairs','description':'Explicit disposition for every owned issue and observation, plus guarded programs bound to the exact base revision.', 'parameters':{'type':'object','properties':{'decisions':{'type':'array','items':{'type':'object'}},'programs':{'type':'array','items':{'type':'object'}}},'required':['decisions','programs'],'additionalProperties':False}}}]


def build_repair_batches(components, base_plan, output_dir, max_batches=2):
    """Exhaustively admit one/two complete component bins before any HTTP.

    Complete candidate messages and original evidence are constructed first. No
    component is split and there is no fallback to a third request. CapacityError
    carries the full components/evidence plan and measured failed candidates.
    """
    out=Path(output_dir); out.mkdir(parents=True,exist_ok=True)
    if max_batches not in (1,2): raise ValueError('at most two repair batches permitted')
    items=components['components']; tools=deepcopy(base_plan.get('repair_tools',_repair_tools())); cache={}; attempts=[]
    audit={'status':'blocked_before_http','components':deepcopy(items),'base_revision':components['base_revision'],'evidence_fallbacks':deepcopy(components['evidence_fallbacks']),'attempts':attempts,'evidence_discarded':False}
    def batch(indices):
        key=tuple(indices)
        if key in cache: return cache[key]
        chosen=[items[i] for i in key]
        evidence=close_evidence(base_plan,{a for c in chosen for a in c['evidence_asset_ids']})
        messages=select_messages(base_plan,evidence)
        responsibility={'capacity_repair':{'base_revision':components['base_revision'],'components':chosen,'conflicts':[conflict for conflict in components.get('conflicts',[]) if set(conflict['ids']) & {r for c in chosen for r in c['issue_ids']+c['observation_ids']}], 'instruction':'For every issue and observation return an explicit preserve/repair/needs-localization decision with evidence. Retain conflicting rows. Programs must bind this exact revision and stay inside component write/read scope. Never silently omit an unresolved row. Use existing program_contract/method_pack and nested args.operations; all original SP, crop, arrow, typed and neighbor gates apply. Evidence images are initial snapshot only. Opaque resource bytes are executor resources, not visual evidence.'}}
        messages.append({'role':'user','content':json.dumps(responsibility,ensure_ascii=False)})
        try:
            capacity=plan_capacity_context(messages,tools)
        except CapacityError as exc:
            audit['capacity_contract_error']=exc.audit
            fail(str(exc))
        value={'component_ids':[c['id'] for c in chosen],'issue_ids':[i for c in chosen for i in c['issue_ids']],'observation_ids':sorted({i for c in chosen for i in c['observation_ids']}),'write_ids':sorted({i for c in chosen for i in c['write_ids']}),'read_ids':sorted({i for c in chosen for i in c['read_ids']}),'unknown_scope':any(c['unknown_scope'] for c in chosen),'asset_ids':evidence,'base_revision':components['base_revision'],'messages':messages,'tools':tools,'capacity':capacity}
        cache[key]=value;attempts.append({'component_ids':value['component_ids'],'capacity':capacity})
        return value
    def fail(reason):
        audit['reason']=reason;write_json(out/'failure-audit.json',audit)
        raise CapacityError('unschedulable: '+reason,audit)
    if not items:
        result={'batches':[],'parallel_safe':False,'disjointness_proof':[],'base_revision':components['base_revision']};write_json(out/'batch-plan.json',result);return result
    selected=None
    for i in range(len(items)):
        if batch([i])['capacity']['status']!='admitted': fail('indivisible component exceeds capacity')
    all_indices=tuple(range(len(items)))
    if batch(all_indices)['capacity']['status']=='admitted': selected=[batch(all_indices)]
    elif max_batches==2:
        # First component always in bin 0 removes symmetric duplicates. Exhaustive
        # enumeration avoids an optimistic greedy "cannot fit" conclusion.
        for count in range(1,len(items)):
            for rest in itertools.combinations(range(1,len(items)),count-1):
                left=(0,)+rest;right=tuple(i for i in all_indices if i not in left)
                if not right: continue
                one=batch(left)
                if one['capacity']['status']!='admitted': continue
                two=batch(right)
                if two['capacity']['status']=='admitted': selected=[one,two];break
            if selected: break
    if selected is None: fail('no complete assignment fits at most two batches')
    proof=[]
    for left,right in itertools.combinations(selected,2):
        hazards=_hazards(left,right)
        proof.append({'left':left['component_ids'],'right':right['component_ids'],'hazards':hazards,'disjoint':not hazards})
        if hazards: fail('cross-batch dependency hazard; components cannot generate independently')
    for i,value in enumerate(selected):
        value['id']=f'repair-{i+1}'
        write_json(out/value['id']/'messages.json',value['messages']);write_json(out/value['id']/'tools.json',value['tools'])
    result={'base_revision':components['base_revision'],'batches':selected,'parallel_safe':len(selected)==2 and all(p['disjoint'] for p in proof),'disjointness_proof':proof,'capacity_attempts':attempts,'all_issue_ids':deepcopy(components['all_issue_ids']),'all_observation_ids':deepcopy(components['all_observation_ids']),'evidence_fallbacks':deepcopy(components['evidence_fallbacks'])}
    write_json(out/'batch-plan.json',result)
    return result
