"""Read-only exact native measurements and asset locations for bounded planning.

Never infer source geometry, modify findings or supply fabricated executable repairs.
"""
import hashlib,json
import xml.etree.ElementTree as ET
from pathlib import Path

def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()
def build(root,checkpoint,state,additional_ids=()):
    root,checkpoint=Path(root),Path(checkpoint)
    svg=checkpoint/'current.svg';bounds_path=checkpoint/'bounds.json'
    bounds=json.loads(bounds_path.read_text());tree=ET.parse(svg)
    objects={};parents={};nodes={}
    def visit(node,parent=None):
        ident=node.get('id')
        if ident:
            if ident in nodes:raise ValueError('duplicate SVG object ID: '+ident)
            nodes[ident]=node;parents[ident]=parent
            objects[ident]={'tag':node.tag.rsplit('}',1)[-1],'parent_id':parent,'attributes':dict(node.attrib)}
            if node.tag.rsplit('}',1)[-1] in ('text','tspan'):objects[ident]['text']=''.join(node.itertext())
        for child in node:visit(child,ident or parent)
    visit(tree.getroot())
    requested={}
    for issue in state.get('required',[])+state.get('uncertain',[]):
        for key in ('target_ids','neighbor_ids'):
            for ident in issue.get(key,[]):requested[ident]=None
        if issue.get('container_id'):requested[issue['container_id']]=None
    for ident in additional_ids:requested[ident]=None
    relevant=set(requested)
    for ident in requested:
        current=parents.get(ident)
        while current:
            relevant.add(current);current=parents.get(current)
    descendants={ident:[n.get('id') for n in nodes[ident].iter() if n is not nodes[ident] and n.get('id')] for ident in sorted(relevant) if ident in nodes and objects[ident]['tag']=='g'}
    original=next((p for p in (root/'inputs/supplied-original.png',root/'inputs/original.png',checkpoint/'original.png') if p.is_file()),root/'inputs/supplied-original.png')
    return {'format':'native-planner-execution-evidence-v2','policy':'Exact current geometry only; NOT source-crop coordinates. Judge crop completeness from original pixels; retain unsupported unknowns. Native capability/quality guards apply.',
        'source_files':{'svg':{'path':str(svg.resolve()),'sha256':sha(svg)},'bounds':{'path':str(bounds_path.resolve()),'sha256':sha(bounds_path)}},
        'original_asset':{'path':str(original.resolve()),'exists':original.is_file(),'sha256':sha(original) if original.is_file() else None},
        'native_measured_bounds':({'canvas':bounds.get('canvas'),'field_scope':'Complete exact native records for relevant IDs; current measurements are never source crop coordinates. Native guards and original bounds.json remain unchanged.','objects':{ident:bounds['objects'][ident] for ident in sorted(relevant) if ident in bounds['objects']}} if state.get('capabilities',{}).get('code_methods') is True else {'available':False,'reason':'C0 disables native numerical measurement snapshots; only ordinary visible SVG attributes and topology are supplied.'}),
        'svg_objects':{ident:objects[ident] for ident in sorted(relevant) if ident in objects},'group_descendant_ids':descendants,
        'unbound_issue_object_ids':sorted(set(requested)-set(nodes))}

def scope_method_pack(pack,state):
    """Select category-specific repair cards for the exact active issue queue only.

    Generic operation, constructor, capability and validator contracts stay intact.
    Joint supplemental detection uses the unscoped cards, since it can add findings.
    """
    from copy import deepcopy
    result=deepcopy(pack)
    categories={issue.get('category') for issue in state.get('required',[])+state.get('uncertain',[])}
    cards=result.get('cards')
    if isinstance(cards,list) and all(isinstance(card,dict) and 'id' in card for card in cards):
        result['cards']=[card for card in cards if card['id'] in categories]
        result['repair_card_scope']={'active_categories':sorted(c for c in categories if c),'inactive_category_ids_not_repeated':[card['id'] for card in cards if card['id'] not in categories],'policy':'Planner repairs only actual queued findings. No enabled constructor, generic operation contract or native validator is removed. Full category cards remain unchanged in the native method-pack.json.'}
    return result

def scope_review_cards(pack,state):
    """Keep all detector rubrics; repeat repair manuals only for frozen active categories."""
    from copy import deepcopy
    result=deepcopy(pack);active={issue.get('category') for issue in state.get('required',[])+state.get('uncertain',[])}
    observation_fields={'id','name','definition','observe','counterevidence','semantic_location','version_hash'}
    inactive=[]
    for i,card in enumerate(result.get('cards',[])):
        if card['id'] not in active:
            inactive.append(card['id']);result['cards'][i]={key:value for key,value in card.items() if key in observation_fields}
    result['review_card_scope']={'full_repair_categories':sorted(c for c in active if c),'observation_only_categories':inactive,'policy':'All category observation/definition/counterevidence/location rubrics remain. Only queued categories repeat repair manuals. All constructors/native guards remain. Unsupported new findings stay unresolved.'}
    return result
