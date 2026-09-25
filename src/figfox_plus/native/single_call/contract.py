"""Validate a complete single-response program before any scene mutation."""
import json
import math
import re
import xml.etree.ElementTree as ET
from copy import deepcopy
from .qlist import BY_ID, MAIN_ORDER

MUTATIONS={'tp_transform','tp_align','tp_fit','sp_replace','sp_photo','bp_patch','bp_add','bp_remove'}
METHODS=MUTATIONS|{'bp_program','measure','sample_colors','check_tp'}
PROTOCOL='''
EXECUTABLE single-call-v1 contract (this overrides older documentation field names):
Return one JSON object:
{version:"single-call-v1",input_revisions:{image_id:revision},
 coverage:[{image_id,pass:1|2|3,region,states,evidence}],
 issues:[{id,image_id,category:A|B|C|D|E|F|S1|S2|S3|S4,description,
 original_evidence,current_evidence,target_ids,neighbor_ids,
 decision:confirmed|uncertain|preserved|duplicate,duplicate_of?,unresolved_reason?}],
 ask_data:[{id,issue_id,phase:preconstructor|reconstructor,method,target_ids,args,
 depends_on:[],rcd_predescription,source_location?,when?,max_attempts?,until?}],
 relations:{image_id:[{id,subject_id,object_id,predicate:separate|contain|legal_overlap,
reference_evidence,min_gap?,padding?}]}}
relations is an object keyed by actual image_id. For contain, subject_id is the
inner content and object_id is its enclosing container (subject INSIDE object).
coverage states is exactly 10 C/I/U/N characters in Q list order A,B,C,D,E,F,S1,S2,S3,S4.
C = checked with no confirmed defect; I = at least one confirmed issue; U = uncertain;
N = this category does not apply to this region. Do not use C to mean confirmed.
Compact coverage may use regions:[region_id,...] instead of region. One record per image
per pass is preferred: pass 1 regions=["full"], passes 2/3 regions=all supplied region_ids.
Its states summarize the whole pass. Still inspect every region and category; do not
spend output or reasoning computing a separate defect-to-tile coordinate membership table.
Pass 1 covers full; passes 2 and 3 each cover every supplied region_id. If no crop exists,
region_ids contains full. Include actual evidence; U means uncertain, not normal.
ask_data IS the ordered executable program, not a tool request awaiting another reply.
Main-category actions follow A..F per image; S1..S4 can be inserted where dependencies allow.
Steps share current object IDs and always read the latest scene. Dependencies refer only to
earlier steps. Confirmed issues need executable steps or an explicit unresolved_reason.
method is a native TP/SP/BP method, measure, sample_colors, check_tp, or bp_program.
bp_program args={operations:[{method,target_ids,args},...]}; these are composable local
constructor instructions, executed atomically. No arbitrary Python or shell is executed.
Preconstructor and reconstructor are executable phases of this local program. Server-side
sandbox execution is unavailable in the configured transport. RCD is produced after execution.
Dynamic values: {"$measure":{"ids":[real IDs],"edge":"left|top|right|bottom|width|height|cx|cy"}}
reads the latest current SVG only; {"$calc":"add|sub|mul|div|min|max","values":[...]} uses those
values; {"$result":{"step":earlier_step,"path":["samples",0,"modal_hex"]}} reads a prior result.
sample_colors args={regions:[[original x,y,width,height],...]}; source_location must state
{basis:"original_semantic",description:original subject and neighbours}. Its result has samples.
sp_photo also requires source_location and a literal independent original source_crop; never
use current TP expressions there. It uses local crop/RMBG; semantic crop iteration isn't a
provided capability. Mark uncertain visual checks instead of requesting more DeepSeek calls.
when={step:earlier_step,status:failed|executed_changed|executed_no_change|blocked} selects a
predeclared branch. Dependencies except this trigger must have succeeded. max_attempts is
1..4; >1 requires until="relations_satisfied" and explicit relations involving this step.
Repeat only a bounded declared local operation with fresh measurements; stop on no progress.
No code or review predescription is evidence of visual acceptance. Missing tools or semantic
verification capabilities must remain unresolved, never an invented success.
'''


def normalize_plan(raw,manifest=None):
    """Canonicalize equivalent wire shapes only; never invent parameters or proof."""
    plan=deepcopy(raw);changes=[]
    for step in plan.get('ask_data',[]):
        ops=[step]+step.get('args',{}).get('operations',[]) if isinstance(step.get('args'),dict) else [step]
        for op in ops:
            if op.get('method')=='tap_transform' and isinstance(op.get('args'),dict):
                matrix=op['args'].get('world_matrix')
                if isinstance(matrix,list) and len(matrix)==6 and all(type(v) in (int,float) and math.isfinite(v) for v in matrix):
                    op['method']='tp_transform';changes.append('tap_transform -> tp_transform (literal six-number world_matrix preserved)')
    if manifest:
        for item in plan.get('coverage',[]):
            region=item.get('region')
            if not isinstance(region,str) or '..' not in region:continue
            parts=region.split('..')
            ordered=manifest['images'].get(item.get('image_id'),{}).get('region_ids',[])
            if len(parts)!=2 or any(p not in ordered for p in parts) or ordered.index(parts[0])>ordered.index(parts[1]) or 'regions' in item:
                raise ValueError('unknown region range')
            item['regions']=ordered[ordered.index(parts[0]):ordered.index(parts[1])+1]
            del item['region'];changes.append('expand explicit region range '+region)
    if isinstance(plan.get('relations'),list):
        grouped={}
        for item in plan['relations']:
            if not isinstance(item,dict) or not isinstance(item.get('image_id'),str):
                raise ValueError('relation list requires explicit image_id')
            im=item['image_id']
            grouped.setdefault(im,[]).append({k:v for k,v in item.items() if k!='image_id'})
        plan['relations']=grouped;changes.append('relations: list with image_id -> keyed object')
    for step in plan.get('ask_data',[]):
        args=step.get('args',{})
        if isinstance(args,dict) and 'source_location' in args:
            if 'source_location' in step and step['source_location']!=args['source_location']:
                raise ValueError('conflicting source_location fields')
            step['source_location']=args.pop('source_location')
            changes.append(str(step.get('id'))+': args.source_location -> step.source_location')
    return plan,changes


def _string(value, name):
    if not isinstance(value,str) or not value.strip():raise ValueError(name+' is required')


def _safe_id(value):
    _string(value,'id')
    if not re.fullmatch(r'[A-Za-z0-9_.:-]{1,120}',value):raise ValueError('invalid plan ID')


def _finite(value):
    if isinstance(value,float) and not math.isfinite(value):raise ValueError('nonfinite value')
    if isinstance(value,dict):
        for v in value.values():_finite(v)
    if isinstance(value,list):
        for v in value:_finite(v)


def _literal_crop(value):
    return isinstance(value,list) and len(value)==4 and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in value)


def validate_plan(plan, manifest, *, _defer_relation_objects=False):
    _finite(plan)
    if plan.get('version')!='single-call-v1':raise ValueError('wrong plan version')
    expected={k:v['revision'] for k,v in manifest['images'].items()}
    if plan.get('input_revisions')!=expected:raise ValueError('stale or incomplete input revisions')
    if not all(isinstance(plan.get(k),list) for k in ('coverage','issues','ask_data')):raise ValueError('missing plan lists')
    required={(im,p,r) for im,data in manifest['images'].items() for p in (1,2,3)
              for r in (['full'] if p==1 else data['region_ids'])}
    seen=set()
    for item in plan['coverage']:
        if ('region' in item)==('regions' in item):raise ValueError('coverage needs region or regions')
        regions=item.get('regions',[item.get('region')])
        if not isinstance(regions,list) or not regions or not all(isinstance(r,str) for r in regions):
            raise ValueError('invalid coverage regions')
        for region in regions:
            key=(item['image_id'],item['pass'],region)
            if key not in required or key in seen:raise ValueError('invalid or duplicate coverage')
            seen.add(key)
        _string(item.get('evidence'),'coverage evidence')
        if not isinstance(item.get('states'),str) or not re.fullmatch('[CIUN]{10}',item['states']):raise ValueError('coverage needs ten states')
    if seen!=required:raise ValueError('incomplete three-pass coverage')
    issues={};known={im:set(v['object_ids']) for im,v in manifest['images'].items()}
    for issue in plan['issues']:
        _safe_id(issue.get('id'))
        if issue['id'] in issues or issue.get('image_id') not in known:raise ValueError('invalid issue identity')
        if issue.get('category') not in BY_ID:raise ValueError('Q list has ten categories, not legacy labels')
        if issue.get('decision') not in {'confirmed','uncertain','preserved','duplicate'}:raise ValueError('invalid issue decision')
        for field in ('description','original_evidence','current_evidence'):_string(issue.get(field),field)
        for field in ('target_ids','neighbor_ids'):
            if not isinstance(issue.get(field),list) or not set(issue[field])<=known[issue['image_id']]:raise ValueError('unknown issue objects')
        issues[issue['id']]=issue
    for issue in issues.values():
        if issue['decision']=='duplicate':
            prior=issues.get(issue.get('duplicate_of'),{})
            if prior.get('decision')!='confirmed' or prior.get('image_id')!=issue['image_id'] or prior.get('category')!=issue['category']:
                raise ValueError('duplicate must reference the same confirmed defect category and image')
    reported={(c['image_id'],category) for c in plan['coverage']
              for category,state in zip(BY_ID,c['states']) if state=='I'}
    confirmed={(i['image_id'],i['category']) for i in issues.values() if i['decision']=='confirmed'}
    if reported!=confirmed:raise ValueError('coverage issue states must match confirmed Q list categories')
    relations=plan.get('relations',{})
    if not isinstance(relations,dict) or set(relations)-set(known):raise ValueError('unknown relation image')
    for im,rules in relations.items():
        ids=set()
        for r in rules:
            _safe_id(r['id'])
            if r['id'] in ids:raise ValueError('duplicate relation ID')
            ids.add(r['id'])
            if r['subject_id']==r['object_id']:raise ValueError('relation needs distinct objects')
            if r['predicate'] not in {'separate','contain','legal_overlap'}:raise ValueError('unsupported relation')
            _string(r.get('reference_evidence'),'relation evidence')
            for key in ('min_gap','padding'):
                value=r.get(key,0)
                if isinstance(value,bool) or not isinstance(value,(int,float)) or value<0:raise ValueError('invalid relation margin')
    steps={};ranks={};attempted=set()
    for step in plan['ask_data']:
        _safe_id(step.get('id'))
        if step['id'] in steps or step.get('issue_id') not in issues:raise ValueError('invalid step identity')
        issue=issues[step['issue_id']];im=issue['image_id'];category=issue['category']
        if issue['decision']!='confirmed':raise ValueError('only confirmed issues can mutate')
        if category in MAIN_ORDER:
            rank=MAIN_ORDER.index(category)
            if rank<ranks.get(im,-1):raise ValueError('main steps must follow A-F order')
            ranks[im]=rank
        if step.get('phase') not in {'preconstructor','reconstructor'}:raise ValueError('invalid execution phase')
        if step.get('method') not in METHODS or not isinstance(step.get('args'),dict):raise ValueError('invalid method or arguments')
        if not isinstance(step.get('depends_on'),list) or not set(step['depends_on'])<=set(steps):raise ValueError('dependency must precede step')
        _string(step.get('rcd_predescription'),'RCD predescription')
        if 'when' in step:
            w=step['when']
            if w.get('step') not in steps or w.get('status') not in {'failed','executed_changed','executed_no_change','blocked'}:raise ValueError('invalid branch trigger')
        attempts=step.get('max_attempts',1)
        if type(attempts) is not int or not 1<=attempts<=4:raise ValueError('invalid local attempts')
        if attempts>1 and (step.get('until')!='relations_satisfied' or not relations.get(im)):raise ValueError('repeat requires explicit checked relations')
        operations=step['args'].get('operations',[]) if step['method']=='bp_program' else [step]
        if not operations:raise ValueError('empty BP program')
        if not isinstance(step.get('target_ids'),list) or not set(step['target_ids'])<=known[im]:raise ValueError('unknown step targets')
        scope=set(issue['target_ids']+issue['neighbor_ids'])
        destructive_scope=set(issue['target_ids'])
        parents=manifest['images'][im].get('parents',{})
        for oid in known[im]:
            ancestor=oid;visited=set()
            while ancestor and ancestor not in visited:
                if ancestor in scope:scope.add(oid);break
                visited.add(ancestor);ancestor=parents.get(ancestor)
            ancestor=oid;visited=set()
            while ancestor and ancestor not in visited:
                if ancestor in destructive_scope:destructive_scope.add(oid);break
                visited.add(ancestor);ancestor=parents.get(ancestor)
        for op in operations:
            if op.get('method') not in (MUTATIONS if step['method']=='bp_program' else METHODS):raise ValueError('invalid program instruction')
            if not isinstance(op.get('target_ids'),list) or not set(op['target_ids'])<=scope:raise ValueError('operation outside issue scope')
            if op['method'] in {'bp_remove','sp_replace','sp_photo'} and not set(op['target_ids'])<=destructive_scope:
                raise ValueError('destructive replacement/removal requires explicit issue targets, not neighbors')
            args=op.get('args',{})
            if op['method'] in {'sp_photo','sample_colors'}:
                loc=step.get('source_location',{})
                if loc.get('basis')!='original_semantic':raise ValueError('original material needs independent semantic location')
                _string(loc.get('description'),'source description')
                crops=[args.get('source_crop')] if op['method']=='sp_photo' else args.get('regions',[])
                if not crops or not all(_literal_crop(c) for c in crops):raise ValueError('original crop cannot use TP expressions')
            if op['method']=='bp_add':
                fragment=ET.fromstring('<g>'+args.get('svg','')+'</g>')
                fresh=[n.get('id') for n in fragment.iter() if n.get('id')]
                if len(fresh)!=len(set(fresh)) or set(fresh)&known[im]:raise ValueError('new SVG IDs must be unique')
                known[im].update(fresh);scope.update(fresh)
                destructive_scope.update(fresh)
                issue= dict(issue,target_ids=issue['target_ids']+fresh)
                issues[issue['id']]=issue
        # Expressions may read only known measurements and already completed steps.
        def expressions(value):
            if isinstance(value,dict):
                if '$measure' in value:
                    spec=value['$measure']
                    if not spec.get('ids') or not set(spec['ids'])<=known[im] or spec.get('edge') not in {'left','top','right','bottom','width','height','cx','cy'}:raise ValueError('invalid measurement reference')
                if '$result' in value and value['$result'].get('step') not in steps:raise ValueError('result reference must precede step')
                if '$calc' in value and value['$calc'] not in {'add','sub','mul','div','min','max'}:raise ValueError('unsupported expression')
                for v in value.values():expressions(v)
            elif isinstance(value,list):
                for v in value:expressions(v)
        expressions(step['args']);steps[step['id']]=step;attempted.add(issue['id'])
    for i in issues.values():
        if i['decision']=='confirmed' and i['id'] not in attempted and not i.get('unresolved_reason'):raise ValueError('confirmed issue needs steps or unresolved reason')
    if not _defer_relation_objects:
        for im,rules in relations.items():
            if any(not {r['subject_id'],r['object_id']}<=known[im] for r in rules):raise ValueError('unknown relation objects')
    return {'issues':issues,'steps':steps,'coverage_complete':True}
