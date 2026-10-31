"""Offline, lossless responsibility packets for one immutable prepared review.

Only image-bearing evidence units are selected. Every non-image block remains in
order, including captions for evidence owned elsewhere. Asset IDs in the appended
responsibility ledger distinguish supplied pixels from context-only captions.
"""
from copy import deepcopy
import base64
import hashlib
import io
import json
from pathlib import Path
import re
import xml.etree.ElementTree as ET

from PIL import Image
from .context_budget import plan_context

VERSION = 'capacity-split-v1'
CATEGORIES = ('E', 'F', 'B', 'A', 'S1')


class CapacityError(ValueError):
    """Fail closed with the full machine-readable preparation/scheduling audit."""
    def __init__(self, message, audit):
        super().__init__(message)
        self.audit = audit


def plan_capacity_context(messages, tools):
    """Apply this workflow's fixed deployment contract to the generic estimator.

    Reject configuration drift instead of allowing another workflow's environment
    to enlarge this request's window or change its reserved output/safety budget.
    """
    budget = plan_context(messages, tools)
    required = {'context_window_tokens':1048576, 'requested_output_tokens':64000,
                'max_output_tokens':64000, 'safety_tokens':32768}
    if any(budget[key] != value for key,value in required.items()):
        raise CapacityError('capacity workflow requires context 1048576, output 64000 and safety 32768',
                            {'status':'blocked_before_http','required':required,'configured_capacity':budget})
    return budget


def write_json(path, value):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _strings(value, label):
    if not isinstance(value, list) or any(not isinstance(x, str) or not x for x in value):
        raise ValueError(label + ' must be an explicit string array')
    if len(set(value)) != len(value):
        raise ValueError('duplicate ' + label)
    return set(value)


def discovery_tools():
    """Capacity output envelope; rows remain open to preserve model observations."""
    props = {key: {'type':'array', 'items':{'type':'object'}} for key in ('observations', 'issues')}
    props.update({key:{'type':'array','items':{'type':'string'}} for key in ('inspected_pair_ids','unresolved_pair_ids')})
    props['category_coverage'] = {'type':'object', 'properties':{c:{'enum':['inspected','unresolved']} for c in CATEGORIES}, 'required':list(CATEGORIES), 'additionalProperties':False}
    return [{'type':'function','function':{'name':'submit_capacity_discovery', 'description':'Submit every observation and issue, including equivalent, outside-scope and unresolved rows. No programs in discovery.', 'parameters':{'type':'object','properties':props,'required':list(props),'additionalProperties':False}}}]


def select_messages(plan, selected_assets):
    """Keep entire selected image messages; retain all other non-image context."""
    selected = set(selected_assets)
    messages = []
    for message, asset_ids in zip(plan['source_messages'], plan['message_assets']):
        chosen = selected.intersection(asset_ids)
        if chosen and chosen != set(asset_ids):
            raise ValueError('cannot cut an indivisible evidence message')
        copy = deepcopy(message)
        if asset_ids and not chosen:
            copy['content'] = [b for b in copy['content'] if b.get('type') != 'image_url']
        messages.append(copy)
    return messages


def close_evidence(plan, asset_ids):
    """Close over indivisible messages, which include complete original/current pairs."""
    selected = set(asset_ids) | set(plan['full_asset_ids'])
    unknown = selected - set(plan['image_asset_ids'])
    if unknown:
        raise ValueError('unknown evidence asset: ' + ', '.join(sorted(unknown)))
    for ids in plan['message_assets']:
        if selected.intersection(ids): selected.update(ids)
    return sorted(selected)


def _read_source(root):
    read = lambda name: json.loads((root / name).read_text())
    inputs, messages = read('inputs.json'), read('messages.json')
    if not isinstance(messages, list) or not messages: raise ValueError('missing source messages')
    resources = read('resource-uri-map.json') if (root/'resource-uri-map.json').exists() else {}
    hashes = {name:digest(root/name) for name in ('inputs.json','messages.json','resource-uri-map.json','methods.json','schedule.json','upstream-arrow-assets.json') if (root/name).exists()}
    if (root/'frozen.json').exists():
        for name, expected in read('frozen.json').items():
            if digest(root/name) != expected: raise ValueError('frozen source hash mismatch: ' + name)
            hashes[name] = expected
        hashes['frozen.json'] = digest(root/'frozen.json')
    assets, pairs, full, image_ids = {}, {}, [], []
    def add(asset, image=False):
        if not isinstance(asset,dict) or not all(asset.get(k) for k in ('asset_id','path','sha256')):
            raise ValueError('missing asset manifest member')
        ident = asset['asset_id']
        if ident in assets: raise ValueError('duplicate manifest asset ' + ident)
        path = Path(asset['path']); path = path if path.is_absolute() else root/path
        if digest(path) != asset['sha256']: raise ValueError('asset hash mismatch: ' + ident)
        assets[ident] = dict(deepcopy(asset), path=str(path.resolve()))
        if image:
            with Image.open(path) as source:
                if list(source.size) != asset.get('dimensions'): raise ValueError('asset dimensions mismatch: ' + ident)
            image_ids.append(ident)
        return ident
    for im, scene in inputs['images'].items():
        for key in ('original_png','current_png','current_svg','current_tp'):
            ident = add(scene[key], image=key.endswith('_png'))
            if key.endswith('_png'): full.append(ident)
        if scene.get('current_revision') != scene['current_svg']['sha256']: raise ValueError('current revision hash mismatch')
        for pair in scene['crop_pairs']:
            pid = pair.get('pair_id')
            if not isinstance(pid,str) or not pid or pid in pairs: raise ValueError('duplicate or missing pair identity')
            if not pair.get('original_asset') or not pair.get('current_asset'): raise ValueError('pair missing original/current member')
            ids = [add(pair[key], image=True) for key in ('original_asset','current_asset')]
            pairs[pid] = dict(deepcopy(pair), image_id=im, asset_ids=ids)
    arrows = read('upstream-arrow-assets.json') if (root/'upstream-arrow-assets.json').exists() else []
    arrow_ids = [add(a, image=True) for a in arrows]
    message_assets, transports, embedded = [], [], []
    seen = set()
    for mi, message in enumerate(messages):
        content = message.get('content'); ids = []; metadata = None
        if isinstance(content, list):
            for bi, block in enumerate(content):
                if block.get('type') == 'text':
                    try: parsed = json.loads(block['text'])
                    except (ValueError, TypeError): parsed = None
                    if isinstance(parsed,dict) and 'current_svg' in parsed: embedded.append(parsed)
                    if isinstance(parsed,dict) and 'asset_id' in parsed and 'sha256' in parsed: metadata = parsed
                elif block.get('type') == 'image_url':
                    if not metadata or metadata['asset_id'] not in image_ids: raise ValueError('image missing manifest metadata')
                    ident = metadata['asset_id']; asset = assets[ident]
                    if ident in seen: raise ValueError('duplicate source image asset ' + ident)
                    if metadata['sha256'] != asset['sha256']: raise ValueError('image metadata hash mismatch')
                    url = block['image_url']['url']
                    match = re.fullmatch(r'data:(image/[^;,]+);base64,(.+)', url, re.S)
                    if not match or match[1] != metadata.get('transport_encoding'): raise ValueError('invalid encoded image URL')
                    raw = base64.b64decode(match[2], validate=True)
                    with Image.open(io.BytesIO(raw)) as decoded, Image.open(asset['path']) as source:
                        if decoded.size != source.size or decoded.convert('RGBA').tobytes() != source.convert('RGBA').tobytes():
                            raise ValueError('encoded image pixels differ from manifest source: ' + ident)
                    transports.append({'asset_id':ident,'message_index':mi,'block_index':bi,'source_sha256':asset['sha256'],'transport_sha256':hashlib.sha256(raw).hexdigest(),'url_sha256':hashlib.sha256(url.encode()).hexdigest()})
                    ids.append(ident); seen.add(ident); metadata = None
        message_assets.append(ids)
    missing = set(image_ids)-seen
    if missing: raise ValueError('pair or asset missing image member: ' + ', '.join(sorted(missing)))
    for pid, pair in pairs.items():
        if not any(set(pair['asset_ids']) <= set(ids) for ids in message_assets): raise ValueError('pair must occupy one complete message: ' + pid)
    svg_audit = []
    for im, scene in inputs['images'].items():
        entries = [entry for entry in embedded if entry.get('image_id') == im]
        if len(entries) != 1: raise ValueError('missing or duplicate complete embedded SVG')
        entry = entries[0]; svg = entry['current_svg']; restored = svg
        for key in re.findall(r'embedded-resource:sha256:([0-9a-f]{64})', svg):
            if key not in resources or hashlib.sha256(resources[key].encode()).hexdigest() != key: raise ValueError('opaque resource reference hash mismatch')
            restored = restored.replace('embedded-resource:sha256:'+key, resources[key])
        tree = ET.fromstring(restored); raw_tree = ET.parse(assets[scene['current_svg']['asset_id']]['path']).getroot()
        ids = [node.get('id') for node in tree.iter() if node.get('id')]
        refs = set(re.findall(r'url\(\s*[\"\']?#([^\s)\"\']+)', restored))
        for node in tree.iter():
            refs.update(value[1:] for key,value in node.attrib.items() if key.rsplit('}',1)[-1]=='href' and value.startswith('#'))
        if refs-set(ids): raise ValueError('unresolved SVG reference: ' + ', '.join(sorted(refs-set(ids))))
        if ET.tostring(tree) != ET.tostring(raw_tree): raise ValueError('embedded SVG differs from source structure/resources')
        if len(ids) != len(set(ids)): raise ValueError('duplicate SVG identity')
        svg_audit.append({'image_id':im,'svg_id_count':len(ids),'svg_ids':ids,'unresolved_references':[],'structure_and_resources_preserved':True})
    return {'source_messages':messages,'message_assets':message_assets,'source_hashes':hashes,'assets':assets,'pairs':pairs,'full_asset_ids':full,'image_asset_ids':image_ids,'arrow_asset_ids':arrow_ids,'context':inputs,'transport_audit':transports,'svg_audit':svg_audit,'resource_map':resources}


def _ownership(assignments, plan):
    if not isinstance(assignments,dict): raise ValueError('assignments must be object')
    branches = assignments.get('branches')
    if not isinstance(branches,dict) or set(branches) != {'A','B'}: raise ValueError('exact branches A/B required')
    if any(not isinstance(b,dict) for b in branches.values()): raise ValueError('branch assignments must be objects')
    pairs = set(plan['pairs']); arrows = set(plan['arrow_asset_ids'])
    shared_pairs = _strings(assignments.get('shared_pair_ids',[]),'shared pairs')
    shared_arrows = _strings(assignments.get('shared_arrow_asset_ids',[]),'shared arrows')
    ledger = {'pairs':{},'arrows':{}}
    for kind,field,expected,shared in [('pairs','pair_ids',pairs,shared_pairs),('arrows','arrow_asset_ids',arrows,shared_arrows)]:
        if shared-expected: raise ValueError('unknown shared evidence')
        for branch, assignment in sorted(branches.items()):
            selected = _strings(assignment.get(field),branch+' '+field)
            if selected-expected: raise ValueError('unknown '+field)
            if not isinstance(assignment.get('owned_regions'),list): raise ValueError('owned_regions required')
            for ident in selected: ledger[kind].setdefault(ident,[]).append(branch)
        for ident in sorted(expected):
            owners = ledger[kind].get(ident,[])
            if not owners: raise ValueError('missing owner: '+ident)
            if (len(owners)==2) != (ident in shared): raise ValueError('shared ownership must be explicit: '+ident)
    records = assignments.get('cross_region_records',[])
    if not isinstance(records,list): raise ValueError('cross_region_records must be array')
    for record in records:
        if not isinstance(record,dict) or set(record.get('branches',[])) != {'A','B'}: raise ValueError('cross-region responsibility requires both branches')
        if not set(record.get('pair_ids',[])) <= shared_pairs or not set(record.get('arrow_asset_ids',[])) <= shared_arrows: raise ValueError('cross-region evidence must be explicitly shared')
    ledger['cross_region_records'] = deepcopy(records)
    return ledger


def prepare_branches(review_dir, assignments, output_dir):
    """Validate every source byte/pixel, preserve context, admit both complete wires.

    On any failure save failure-audit.json and raise CapacityError. This function
    never calls the provider, renders new evidence, or touches the source folder.
    """
    root = Path(review_dir).resolve(); out = Path(output_dir).resolve()
    if out == root or root in out.parents: raise ValueError('output must not alter prepared source directory')
    out.mkdir(parents=True,exist_ok=True)
    audit = {'status':'blocked_before_http','evidence_discarded':False,'assignments':deepcopy(assignments),'source_review_dir':str(root)}
    plan = None
    try:
        plan = _read_source(root)
        audit['source_hashes'] = plan['source_hashes']
        write_json(out/'source-audit.json',{key:plan[key] for key in ('source_hashes','assets','transport_audit','svg_audit')})
        owners = _ownership(assignments,plan)
        write_json(out/'ownership-audit.json',owners)
        tools = discovery_tools()
        plan.update(version=VERSION, assignments=deepcopy(assignments), ownership=owners, tools=tools, branches={}, source_capacity=plan_capacity_context(plan['source_messages'],tools))
        for branch, assignment in sorted(assignments['branches'].items()):
            selected = set(plan['full_asset_ids']) | set(assignment['arrow_asset_ids'])
            for pid in assignment['pair_ids']: selected.update(plan['pairs'][pid]['asset_ids'])
            selected = close_evidence(plan,selected)
            if set(selected) != set(plan['full_asset_ids']) | set(assignment['arrow_asset_ids']) | {a for pid in assignment['pair_ids'] for a in plan['pairs'][pid]['asset_ids']}:
                raise ValueError('message crosses undeclared ownership')
            messages = select_messages(plan,selected)
            responsibility = {'capacity_responsibility':{'branch_id':branch, **deepcopy(assignment), 'supplied_image_asset_ids':selected,'cross_region_records':deepcopy(assignments.get('cross_region_records',[])), 'shared_pair_ids':assignments.get('shared_pair_ids',[]),'shared_arrow_asset_ids':assignments.get('shared_arrow_asset_ids',[]), 'instruction':'Inspect owned and shared evidence in the original category order. This responsibility ledger limits the original global itinerary to the supplied pairs. Retained captions for other branches do not mean their pixels were supplied. Preserve every observation, equivalent/outside-scope/uncertain row and unresolved localization. Use submit_capacity_discovery with explicit pair coverage and category_coverage; no repair programs. Opaque embedded-resource hashes bind original bytes available to the executor, not visible image evidence. Coverage is mechanical, never proof of visual correctness.'}}
            messages.append({'role':'user','content':json.dumps(responsibility,ensure_ascii=False)})
            packet = {'messages':messages,'tools':deepcopy(tools),'context':deepcopy(plan['context']),'assignment':deepcopy(assignment),'asset_ids':selected,'capacity':plan_capacity_context(messages,tools)}
            plan['branches'][branch] = packet
            write_json(out/branch/'messages.json',messages); write_json(out/branch/'tools.json',tools)
        capacities = {b:v['capacity'] for b,v in plan['branches'].items()}
        write_json(out/'capacity-audit.json',capacities)
        plan['coverage'] = {'complete':True,'pair_count':len(plan['pairs']),'arrow_count':len(plan['arrow_asset_ids']),'image_count':len(plan['image_asset_ids']),'uncovered':[],'conflicts':[], 'visual_inspection_proven':False}
        write_json(out/'coverage-audit.json',plan['coverage'])
        if any(v['status']!='admitted' for v in capacities.values()):
            audit.update(capacity=capacities,coverage=plan['coverage']); raise ValueError('branch capacity exceeded; complete evidence retained')
        write_json(out/'plan.json',plan)
        return plan
    except (ValueError,KeyError,TypeError,OSError,ET.ParseError) as exc:
        audit['error'] = str(exc)
        if isinstance(exc,CapacityError): audit['capacity_contract_error'] = exc.audit
        if plan is not None and 'coverage' not in plan:
            assigned_pairs=set(); assigned_arrows=set()
            branches=assignments.get('branches',{}) if isinstance(assignments,dict) else {}
            for branch in (branches.values() if isinstance(branches,dict) else []):
                if not isinstance(branch,dict): continue
                for field,seen in [('pair_ids',assigned_pairs),('arrow_asset_ids',assigned_arrows)]:
                    values=branch.get(field,[])
                    if isinstance(values,list): seen.update(v for v in values if isinstance(v,str))
            audit['coverage']={'complete':False,'uncovered':sorted((set(plan['pairs'])-assigned_pairs)|(set(plan['arrow_asset_ids'])-assigned_arrows)),
                               'conflicts':[str(exc)],'visual_inspection_proven':False}
            write_json(out/'coverage-audit.json',audit['coverage'])
            if not (out/'ownership-audit.json').exists():
                write_json(out/'ownership-audit.json',{'assignments':deepcopy(assignments),'valid':False,'errors':[str(exc)]})
        write_json(out/'failure-audit.json',audit)
        raise CapacityError(str(exc),audit) from exc
