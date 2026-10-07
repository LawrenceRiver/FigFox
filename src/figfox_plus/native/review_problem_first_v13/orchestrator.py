"""Twelve-input handoff, complete inspection and at most one tool feedback turn."""
import base64
import io
from PIL import Image
from copy import deepcopy
from figfox_plus import file_lock as fcntl
import hashlib
import json
import re
from pathlib import Path
import shutil
from ...state import write_json
from .inputs import validate_bundle
from .inspection import make_schedule
from .evidence import validate_observations
from .inspection_contract import expand_observations, inspection_regions, audit_inspection, INSPECTION_SCHEMA, INSPECTION_PROMPT
from .methods import build_method_pack
from .transport import send
from .problem_first import PROMPT as PROBLEM_PROMPT, SCHEMA as PROBLEM_SCHEMA, category_itinerary, expand_category_sweeps, audit_problem_first
from .context_tables import model_line_facts
from .input_encoding import compact_category_itinerary
from .lean_inspection import PROMPT as PROBLEM_PROMPT, REPAIR_PROMPT, build_schema as compact_schema, audit as audit_compact
from ..strict_review_envelope import build_schema, decode_envelope
from ..current_line_facts import build_line_facts
from ..review_photo_previews import collect_photo_previews
from .quality import POLICY
from .issues import effective_issue_rows, source_pending_ids
from .diagnostics import build_diagnostics
from ..tight_tp import measure_tight
import xml.etree.ElementTree as ET

TOOLS=[{'type':'function','function':{'name':'execute_review_program','description':'Submit all inspection observations, detected issues and executable programs. Host returns real execution and rendered images. No implicit model calls.',
 'parameters':{'type':'object','properties':{'observations':{'type':'array','items':{'type':'object'}},'observation_rows':{'type':'array','items':{'type':'object'}},'observation_evidence':{'type':'object'},'issues':{'type':'array','items':{'type':'object'}},'programs':{'type':'array','items':{'type':'object'}},'prior_issue_reviews':{'type':'array','items':{'type':'object'}}},'required':['issues','programs'],'additionalProperties':False}}}]
PROMPT=PROBLEM_PROMPT + '\n' + '''Each item in issues is {id,image_id,category,description,original_evidence,current_evidence,target_ids,neighbor_ids,decision:confirmed|uncertain|preserved|duplicate}. In the first request, programs is fixed as []. Tool arguments must be JSON with compact_category_sweeps, issues, and programs; do not wrap them in an outer arguments layer. Do not output other_sweep.
'''
PROGRAM_CONTRACT='''Write programs only in the second request. Each item in programs is {id,issue_ids,image_id,base_revision,phase:preconstructor|reconstructor,route:module_program|generated_python,target_ids,depends_on:[],rcd_predescription,args?,source_code?,relations?,convergence?,when?}. For module programs, args={operations:[{method,target_ids,args}]}. Methods follow the provided method_pack. Dynamic programs use INPUT_SVG and OUTPUT_SVG paths, performing tree.write after ET.parse. For every category, programs mutating the same SVG object or overlapping group/child scopes must declare depends_on on the preceding program; independent scopes use []. This includes adding an outline to a group whose children another program changes. Write F, E, B, S1, D, and S2 programs together. For F, use predicate; min_gap for separate and padding for contain must both be positive numbers. For E, when endpoints or lengths are incorrect, modify endpoints or lengths; do not merely translate to the center. For B, repair only compilation failures, subscript/superscript errors, and compilation errors in symbols such as radicals. Do not modify text that differs in font but displays clearly. For S1, preserve the actual source projection and supply independent original-pixel evidence under the policy below. Supported SP, native and scoped generated_python routes remain available; unsupported pixel evidence preserves the object and records the unresolved reason in the existing precheck. Explicit planar source counterevidence remains binding. For D, use sp_replace with kind as arrow; the arrowhead tip and the shaft endpoint must coincide, arrowhead dimensions must match the original figure in pixels; dependencies follow the same scope rule as every other category. For S2, restore an existing structural boundary with bp_patch and original-pixel stroke/style evidence while preserving children; use sp_photo only for a small missing or completely inconsistent image patch. TP target_tp and measurement_viewport use {left,top,right,bottom}, or the equivalent edge array [left,top,right,bottom]; source_crop remains original-pixel [x,y,width,height]. In relations, subject_id and object_id must be existing object IDs in the current SVG, or use container_ids and target_ids; do not use neighbor_ids. sp_photo requires crop_review with object_complete true, clipped false, full_object_xywh, edges_reviewed with all four edge entries set to true, and evidence, along with source_location.basis set to original_semantic. Programs failing structural pre-checks will not execute.
''' + POLICY + '\n' + '''Generated Python mutations must stay within the issue target_ids and their descendants. Neighbor IDs are context, not additional replacement targets; use the existing typed module operations for source-justified neighboring label or frame adjustments. Never expand issue targets or alter evidence merely to pass scope validation.'''
TOOLS[0]['function']['parameters']['properties']={
 **PROBLEM_SCHEMA,
 'issues':{'type':'array','items':{'type':'object'}},
 'programs':{'type':'array','items':{'type':'object'}},
 'prior_issue_reviews':{'type':'array','items':{'type':'object'}}}


def _tools_for(schedule,review_only=False):
    result=deepcopy(TOOLS)
    result[0]['function']['parameters']=compact_schema(schedule,review_only=review_only)
    return result


def _svg_text(value):
    return re.sub(r'data:image/[^"\s<>]+',lambda m:'embedded-resource:sha256:'+hashlib.sha256(m.group(0).encode()).hexdigest(),value)

def _feedback_brief(feedback):
    value=deepcopy(feedback)
    for row in value.get('execution_result',{}).get('rcd',[]):
        row.pop('measurement',None)
        row.pop('actual_parameters',None)
    value.get('execution_result',{}).pop('aliases',None)
    return value


def _hash(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _assets(inputs):
    for im in inputs['images'].values():
        for key in ('original_png','current_svg','current_png','current_tp'):yield im[key]
        for pair in im['crop_pairs']:
            yield pair['original_asset'];yield pair['current_asset']


def _image(asset):
    raw=Path(asset['path']).read_bytes();mime='image/png'
    # Transport only: lossless encoding, verified decoded pixels and dimensions.
    with Image.open(io.BytesIO(raw)) as original:
        rgba=original.convert('RGBA');out=io.BytesIO()
        rgba.save(out,format='WEBP',lossless=True,exact=True,method=4)
        encoded=out.getvalue()
        with Image.open(io.BytesIO(encoded)) as check:
            if check.size!=rgba.size or check.convert('RGBA').tobytes()!=rgba.tobytes():
                raise ValueError('lossless transport pixel mismatch')
        if len(encoded)<len(raw):raw=encoded;mime='image/webp'
    return [{'type':'text','text':json.dumps({'asset_id':asset['asset_id'],'sha256':asset['sha256'],'transport_encoding':mime,'pixels_unchanged':True})},
            {'type':'image_url','image_url':{'url':'data:'+mime+';base64,'+base64.b64encode(raw).decode(),'detail':'original'}}]


def prepare(bundle, task_dir, *, upstream_arrow_specs=None):
    inputs=validate_bundle(bundle)
    if len(inputs['images']) != 1:
        raise ValueError('one_image_per_review: prepare each image as an independent task')
    root=Path(task_dir).resolve();root.mkdir(parents=True,exist_ok=False)
    assets=root/'inputs';assets.mkdir()
    for i,a in enumerate(_assets(inputs)):
        dest=assets/(f'{i:04d}'+Path(a['path']).suffix)
        shutil.copyfile(a['path'],dest);a['path']=str(dest)
    inputs=validate_bundle(inputs);schedule=make_schedule(inputs);methods=build_method_pack()
    write_json(root/'inputs.json',inputs);write_json(root/'schedule.json',schedule);write_json(root/'methods.json',methods)
    diagnostic_pack={};context_svgs={}
    for key,im in inputs['images'].items():
        context_svgs[key]=Path(im['current_svg']['path']).read_text(encoding='utf-8')
        measured=measure_tight(ET.fromstring(Path(im['current_svg']['path']).read_text(encoding='utf-8')))
        measured['current_revision']=im['current_revision']
        tp_file=root/(key+'-full-tight-tp.json');write_json(tp_file,measured)
        report=build_diagnostics(im['current_svg']['path'],tp_file)
        report['current_revision']=im['current_revision']
        # Geometric bounds can expose unclipped viewport overflow that raster TP cannot.
        coarse=build_diagnostics(im['current_svg']['path'],im['current_tp']['path'])
        report['unclipped_geometry_overflow_candidates']=[r for r in coarse['relation_candidates'] if r['kind']=='canvas_overflow']
        write_json(root/(key+'-diagnostics.json'),report)
        diagnostic_pack[key]={'current_revision':im['current_revision'],'coverage':report['coverage'],
            'relation_columns':['kind','object_ids','intersection_size','margins_ltrb'],
            'relation_candidates':[[r['kind'],r['object_ids'],r.get('intersection_size'),r.get('margins_ltrb')] for r in report['relation_candidates']],
            'structure_candidates':report['structure_candidates'],'unmeasurable':report['unmeasurable'],
            'unclipped_geometry_overflow_candidates':report['unclipped_geometry_overflow_candidates'],
            'normal_containment_count':len(report['normal_containment']),
            'instructions':report['instruction']}
    write_json(root/'current-diagnostics.json',diagnostic_pack)
    line_pack={}
    for key,im in inputs['images'].items():
        facts=build_line_facts(im['current_svg']['path']);facts['current_revision']=im['current_revision']
        write_json(root/(key+'-line-facts.json'),facts);line_pack[key]=facts
    write_json(root/'current-line-facts.json',line_pack)
    from ..line_alignment_candidates import summarize_line_alignment
    alignment_pack={key:summarize_line_alignment(facts) for key,facts in line_pack.items()}
    write_json(root/'current-line-alignment-candidates.json',alignment_pack)
    from ..coincident_path_candidates import build_coincident_path_candidates
    coincident_pack={key:build_coincident_path_candidates(inputs['images'][key]['current_svg']['path'],facts)
                     for key,facts in line_pack.items()}
    write_json(root/'current-coincident-path-candidates.json',coincident_pack)

    from .upstream_arrows import freeze_arrow_evidence
    arrow_context={};arrow_assets=[];arrow_provenance={}
    for key,im in inputs['images'].items():
        evidence=freeze_arrow_evidence((upstream_arrow_specs or {}).get(key),im['original_png'],root/'upstream-arrows'/key)
        for a in evidence['image_assets']:a['asset_id']=key+'/'+a['asset_id']
        for a in evidence['model_context']['arrows']:a['asset_id']=key+'/'+a['asset_id']
        arrow_context[key]=evidence['model_context'];arrow_assets.extend(evidence['image_assets']);arrow_provenance[key]=evidence['provenance']
    write_json(root/'upstream-arrow-provenance.json',arrow_provenance)
    write_json(root/'upstream-arrow-assets.json',arrow_assets)

    content=[{'type':'text','text':json.dumps({'input_inventory':{str(i):v for i,v in enumerate(['original Crop','current SVG','current PNG','original PNG','current Crop','current TP','SP library','BP library','Q list','Ask_data contract','Reconstructor interface','Preconstructor interface'],1)},
       'schedule':schedule,'upstream_arrow_evidence':arrow_context,'current_line_facts':{k:model_line_facts(v) for k,v in line_pack.items()},'current_line_alignment_candidates':alignment_pack,'current_coincident_path_candidates':coincident_pack,'current_diagnostics':diagnostic_pack,'method_pack':methods,'program_contract':PROGRAM_CONTRACT,'context_asset_policy':'Complete SVG vector paths and line facts are retained. Embedded resource references identify immutable assets shown in the supplied original/current PNGs. Generated code must read INPUT_SVG and preserve unrelated content.'},ensure_ascii=False)}]
    for key,im in inputs['images'].items():
        content.append({'type':'text','text':json.dumps({'image_id':key,'revision':im['current_revision'],
          'current_svg':context_svgs[key],'current_tp':json.loads(Path(im['current_tp']['path']).read_text(encoding='utf-8')),
          'crop_pairs':[{k:v for k,v in p.items() if k not in ('original_asset','current_asset')} for p in im['crop_pairs']]},ensure_ascii=False)})
        content.extend(_image(im['original_png']));content.extend(_image(im['current_png']))
        for pair in im['crop_pairs']:
            content.extend(_image(pair['original_asset']));content.extend(_image(pair['current_asset']))
    for arrow_asset in arrow_assets:content.extend(_image(arrow_asset))
    messages=[{'role':'system','content':PROMPT},{'role':'user','content':content}]
    resources={}
    for item in content:
        if item['type']!='text':continue
        data=json.loads(item['text'])
        if 'schedule' in data:
            data.update(compact_category_itinerary(data.pop('schedule')))
            data['schedule_encoding']='Region ids are only for citing a problem. Do not list every region. One look per category, then decide.'
        if 'current_svg' in data:
            def reference(match):
                raw=match.group(0);digest=hashlib.sha256(raw.encode()).hexdigest();resources[digest]=raw
                return 'embedded-resource:sha256:'+digest
            data['current_svg']=re.sub(r'data:image/[^\"\s<>]+',reference,data['current_svg'])
            data['svg_resource_encoding']='Opaque embedded image data URIs use host resource references. Exact original SVG/URIs remain with executor. View actual pixels in supplied PNG/Crops; never replace these references or report them as corruption.'
        item['text']=json.dumps(data,ensure_ascii=False,separators=(',',':'))
    write_json(root/'resource-uri-map.json',resources)
    from ..review_image_message_format import format_initial_image_messages
    messages,presentation_audit=format_initial_image_messages(messages,inputs,
        upstream_arrow_assets=arrow_assets,upstream_arrow_context=arrow_context)
    messages.append({'role':'user','content':'This is the first request; identify defects only, with programs as []. Inspect the full-image original-vs-current comparison, the current SVG, and the 1/2 Crop pairs once each. For regular cuboids and inconsistent patches, perform a separate pass over the 1/2 Crop pairs for each. Record urgent alignment and overlap issues upon observation. Do not restate the reasoning.'})
    write_json(root/'image-presentation-audit.json',presentation_audit)
    # Prepared formatting is not the wire body. Admission happens in transport
    # after lossless formatting compaction, against documented provider limits.
    write_json(root/'prepared-capacity.json',{'formatted_message_bytes':len(json.dumps(messages,ensure_ascii=False).encode()),
        'semantic_fields_removed':[], 'model_request_sent':False})
    write_json(root/'messages.json',messages)
    write_json(root/'frozen.json',{p.name:_hash(p) for p in [root/'inputs.json',root/'schedule.json',root/'methods.json',root/'messages.json',root/'current-diagnostics.json',root/'upstream-arrow-provenance.json',root/'upstream-arrow-assets.json',root/'current-line-facts.json',root/'current-line-alignment-candidates.json',root/'current-coincident-path-candidates.json',root/'image-presentation-audit.json']})
    return inputs


def _plan(message, schedule=None, *, review_only=False, repair_context=None):
    calls=message.get('tool_calls',[])
    channel='tool_calls';call_id=None
    if calls:
        if len(calls)!=1 or calls[0].get('function',{}).get('name')!='execute_review_program':
            raise ValueError('expected_one_execute_review_program_tool_call')
        source=calls[0]['function']['arguments'];call_id=calls[0]['id']
    else:
        channel='content';source=message.get('content')
        if not isinstance(source,str) or not source.strip():raise ValueError('expected_review_json_content')
    raw_source=source
    if channel=='content':
        stripped=source.strip()
        if stripped.startswith('```'):
            match=re.fullmatch(r'```json\s*\n(.*?)\n```',stripped,re.DOTALL)
            if not match:raise ValueError('content must be pure JSON or one json fence')
            source=match.group(1)
    from ..review_json_syntax import parse_complete_json
    plan,syntax_edits=parse_complete_json(source)
    if not isinstance(plan,dict):raise ValueError('plan must be object')
    issues_binding=None
    if 'issues' not in plan and repair_context is not None:
        # Only a repair continuation can reuse host-bound discovery evidence.
        # Explicit empty/invalid fields and discovery omissions remain binding.
        previous=deepcopy(repair_context['issues'])
        if not isinstance(previous,list):raise ValueError('missing issues')
        from .issues import validate_issues
        validate_issues(deepcopy(previous),[],repair_context['images'])
        plan['issues']=previous
        issues_binding={'source':'previous_discovery','issue_ids':[i['id'] for i in previous],
                        'image_revisions':{k:v['revision'] for k,v in repair_context['images'].items()}}
    wrapped=any(isinstance(items,list) and any(isinstance(item,dict) and key in item for item in items) for items,key in ((plan.get('programs'),'program_json'),(plan.get('prior_issue_reviews'),'review_json')))
    legacy='category_checks' not in plan and not wrapped
    if legacy:
        if 'category_sweeps' in plan and not isinstance(plan['category_sweeps'],list):raise ValueError('category_sweeps must be array')
        if 'prior_issue_reviews' in plan and not isinstance(plan['prior_issue_reviews'],list):raise ValueError('prior_issue_reviews must be array')
        actual_review_only=not bool({'compact_category_sweeps','category_sweeps','other_sweep'} & plan.keys())
        contract='legacy_tool' if channel=='tool_calls' else 'legacy_content'
        if actual_review_only:contract+='_review_only'
        if actual_review_only and not review_only:
            plan['_inspection_envelope_error']={'error':'response mode mismatch','expected_review_only':review_only,'actual_review_only':actual_review_only}
            plan['_raw_inspection_envelope']={key:deepcopy(plan[key]) for key in ('category_sweeps','other_sweep') if key in plan}
            contract+='_inspection_mode_error'
    else:
        # Host records already passed semantic validation; do not reshape them
        # into the provider's strict issue schema or invent its placeholder fields.
        raw_plan=dict(plan,issues=[]) if issues_binding else plan
        actual_review_only=not bool({'category_checks','other_sweep'} & raw_plan.keys())
        try:
            if actual_review_only and not review_only:raise ValueError('response mode mismatch')
            if schedule is not None:plan=decode_envelope(raw_plan,inspection_regions(schedule))
            contract='strict_review_only' if review_only else 'strict_full'
        except ValueError as exc:
            if schedule is None:raise
            # Strictly decode the existing execution fields independently. Never
            # create missing issue fields, observations, coordinates or programs.
            execution={key:raw_plan[key] for key in ('issues','programs','prior_issue_reviews') if key in raw_plan}
            plan=decode_envelope(execution,inspection_regions(schedule))
            plan['_inspection_envelope_error']={'error':str(exc),'expected_review_only':review_only,'actual_review_only':actual_review_only}
            plan['_raw_inspection_envelope']={key:deepcopy(raw_plan[key]) for key in ('category_checks','other_sweep') if key in raw_plan}
            contract='execution_only_after_envelope_error'
    if issues_binding:plan['issues']=previous
    for key in ('issues','programs'):
        if not isinstance(plan.get(key),list):raise ValueError('missing '+key)
    # Relation IDs are audit labels, not geometry. Supply missing unreferenced
    # labels deterministically, but never guess the target of a check_id link.
    for program in plan['programs']:
        if not isinstance(program,dict):continue
        relations=program.get('relations',[])
        convergence=program.get('convergence') or {}
        if not isinstance(relations,list) or not isinstance(convergence,dict):continue
        checks=convergence.get('alignment_checks') or []
        repairs=convergence.get('repairs') or []
        if not isinstance(checks,list) or not isinstance(repairs,list):continue
        known={r['id'] for r in relations+checks if isinstance(r,dict) and isinstance(r.get('id'),str)}
        check_only=[r for r in repairs if isinstance(r,dict) and set(r)=={'check_id'} and r['check_id'] in known]
        if check_only:
            repairs=[r for r in repairs if r not in check_only]
            convergence['repairs']=repairs
            program.setdefault('host_normalizations',[]).extend(
                {'kind':'remove_check_only_repair_reference','check_id':r['check_id']} for r in check_only)
        if any(not isinstance(r,dict) or r.get('check_id') not in known for r in repairs):continue
        for index,relation in enumerate(relations):
            if not isinstance(relation,dict) or 'id' in relation:continue
            digest=hashlib.sha256(json.dumps(relation,sort_keys=True).encode()).hexdigest()[:12]
            ident=f'auto_relation_{index}_{digest}'
            while ident in known:ident+='x'
            relation['id']=ident;known.add(ident)
            program.setdefault('host_normalizations',[]).append(
                {'kind':'unreferenced_relation_id','relation_index':index,'assigned_id':ident})
    plan['_syntax_edits']=syntax_edits
    plan['_response_metadata']={'response_channel':channel,'contract':contract,'source_sha256':hashlib.sha256(raw_source.encode()).hexdigest()}
    if issues_binding:plan['_response_metadata']['issues_binding']=issues_binding
    return plan,call_id


def _reviews(plan,prior,images):
    rows=plan.get('prior_issue_reviews',[]);expected={i['id'] for i in prior};seen=set()
    current={i['id'] for i in plan['issues']}
    for row in rows:
        if row.get('issue_id') not in expected or row['issue_id'] in seen:raise ValueError('invalid prior issue review')
        issue=next(i for i in prior if i['id']==row['issue_id'])
        if row.get('revision')!=images[issue['image_id']]['revision']:raise ValueError('stale visual review')
        if row.get('status') not in ('resolved','persists','false_positive','uncertain') or not str(row.get('evidence','')).strip():raise ValueError('invalid visual review')
        if row['status']=='persists' and (not row.get('issue_ids') or not set(row['issue_ids'])<=current):raise ValueError('persisting issue omitted')
        seen.add(row['issue_id'])
    if seen!=expected:raise ValueError('missing prior issue disposition')


def _review_audit(plan,prior,images):
    try:_reviews(plan,prior,images)
    except Exception as exc:return {'status':'failed','error':type(exc).__name__+': '+str(exc),'visual_acceptance':'not_assessed'}
    return {'status':'records_valid','visual_acceptance':'not_assessed'}


def run(task_dir, *, sender=None, request_limit=2, initial_candidates=None):
    if type(request_limit)!=int or request_limit not in (1,2):raise ValueError('request_limit must be 1 or 2')
    root=Path(task_dir).resolve()
    with (root/'pipeline.lock').open('a', encoding='utf-8') as lock:
        fcntl.flock(lock,fcntl.LOCK_EX)
        for name,digest in json.loads((root/'frozen.json').read_text(encoding='utf-8')).items():
            if _hash(root/name)!=digest:raise ValueError('frozen input modified: '+name)
        for asset in json.loads((root/'upstream-arrow-assets.json').read_text(encoding='utf-8')):
            if _hash(asset['path'])!=asset['sha256']:raise ValueError('frozen upstream arrow asset modified')
        inputs=validate_bundle(json.loads((root/'inputs.json').read_text(encoding='utf-8')))
        if len(inputs['images']) != 1:raise ValueError('one_image_per_review')
        if build_method_pack()['version_hash']!=json.loads((root/'methods.json').read_text(encoding='utf-8'))['version_hash']:
            raise ValueError('method_library_changed_since_prepare')
        result_file=root/'result.json'
        if result_file.exists():return json.loads(result_file.read_text(encoding='utf-8'))
        messages=json.loads((root/'messages.json').read_text(encoding='utf-8'));schedule=json.loads((root/'schedule.json').read_text(encoding='utf-8'))
        images={k:{'svg':i['current_svg']['path'],'png':i['current_png']['path'],'original':i['original_png']['path'],'revision':i['current_revision']} for k,i in inputs['images'].items()}
        all_issues=[];all_rcd=[];all_rejected=[];review_audits=[];coverage={'records_complete':False,'visual_acceptance':'not_assessed'};first_issues=[]
        repair_candidates=list(initial_candidates or [])
        for n in range(request_limit):
            turn=root/f'phase-{n+1}';turn.mkdir(exist_ok=True)
            if (turn/'message.json').exists():message=json.loads((turn/'message.json').read_text(encoding='utf-8'))
            else:
                message=(sender or send)(messages,_tools_for(schedule,review_only=n>0 and coverage.get('records_complete',False)),root,request_limit=request_limit)
                write_json(turn/'message.json',message)
            expected_review_only=n>0 and coverage.get('records_complete',False)
            review_audit={'status':'not_required','visual_acceptance':'not_assessed'}
            raw_calls=message.get('tool_calls',[])
            call_id=raw_calls[0].get('id') if len(raw_calls)==1 else None;plan=None
            try:
                plan,call_id=_plan(message,schedule,review_only=expected_review_only,
                                  repair_context={'issues':first_issues,'images':images} if n>0 else None)
                write_json(turn/'raw-plan.json',plan)
                from ..review_result_id_normalization import normalize_unreferenced_result_ids
                plan,id_audit=normalize_unreferenced_result_ids(plan)
                write_json(turn/'result-id-normalization.json',id_audit)
                for change in id_audit['changes']:
                    plan['programs'][change['program_index']].setdefault('host_normalizations',[]).append(
                        dict(change,kind='unreferenced_result_id_namespace'))
                if 'category_sweeps' in plan:
                    try:plan=expand_category_sweeps(plan,schedule)
                    except (ValueError,KeyError,TypeError) as exc:
                        write_json(turn/'category-audit-error.json',{'error':str(exc)})
                if n==0:
                    first_issues=plan['issues']
                    plan['programs']=[]
                write_json(turn/'plan.json',plan)
                if plan.get('_inspection_envelope_error'):
                    coverage={'records_complete':False,'inspection_complete':False,'visual_acceptance':'not_assessed','inspection_envelope_error':plan['_inspection_envelope_error']}
                    write_json(turn/'inspection-envelope-error.json',plan['_inspection_envelope_error'])
                elif n==0 or not coverage.get('records_complete'):
                    try:coverage=audit_compact(schedule,plan,plan['issues'])
                    except (ValueError,KeyError,TypeError) as exc:
                        coverage={'records_complete':False,'inspection_complete':False,'error':str(exc),'visual_acceptance':'not_assessed'}
                if n==0:
                    feedback={'execution_result':{'status':'discovery_only'},'coverage':coverage,'visual_passed':False}
                else:
                    from .replay import filter_program_shapes
                    plan['programs'],shape_rejected=filter_program_shapes(plan['programs'])
                    shape_rejected.extend(plan.get('_decode_rejections',[]))
                    all_rejected.extend(shape_rejected)
                    write_json(turn/'program-shape-rejections.json',shape_rejected)
                    from .issues import validate_issues
                    validate_issues(plan['issues'],plan['programs'],images)
                    from .programs import execute_programs
                    from .replay import select_valid_programs
                    accepted,rejected=select_valid_programs(plan['programs'],plan['issues'],images,prior_executed=all_rcd)
                    all_rejected.extend(rejected)
                    rejected=shape_rejected+rejected
                    write_json(turn/'program-preflight.json',{'accepted':[p['id'] for p in accepted],'rejected':rejected})
                    write_json(turn/'normalized-programs.json',accepted)
                    if not accepted:
                        feedback={'execution_result':{'status':'precheck_failed','rejected':rejected},'coverage':coverage,'visual_passed':False}
                    else:
                        result=execute_programs(accepted,plan['issues'],images,turn/'execution',prior_executed=all_rcd)
                        result['rejected_programs']=rejected
                        images={k:dict(v,original=images[k]['original']) for k,v in result['images'].items()};all_rcd.extend(result['rcd'])
                        feedback={'execution_result':result,'coverage':coverage,'visual_passed':False}
            except (ValueError,KeyError,TypeError) as exc:
                feedback={'execution_result':{'error':str(exc)},'coverage':coverage,'visual_passed':False}
            feedback['inspection_envelope_error']=plan.get('_inspection_envelope_error') if plan else None
            feedback['syntax_edits']=plan.get('_syntax_edits',[]) if plan else []
            feedback['review_audit']=review_audit
            feedback['response_metadata']=plan.get('_response_metadata',{}) if plan else {}
            review_audits.append(dict(review_audit,model_turn=n+1))
            if plan:
                all_issues.extend(dict(i,model_turn=n+1) for i in plan['issues'])
            write_json(turn/'feedback.json',feedback)
            found=[i for i in first_issues if i.get('decision') in ('confirmed','uncertain')]
            if n==0 and n+1<request_limit and found:
                # Preserve upstream continuation, including original reasoning,
                # tool identities and every whole-image/crop evidence message.
                messages.append(message)
                note=json.dumps({'issues':found},ensure_ascii=False)
                if raw_calls:
                    for raw_call in raw_calls:
                        messages.append({'role':'tool','tool_call_id':raw_call['id'],'content':note})
                messages.append({'role':'user','content':REPAIR_PROMPT+'\n'+PROGRAM_CONTRACT+'\n'+note})
        result={'status':('inspection_incomplete' if not coverage.get('records_complete') else 'execution_failed' if feedback['execution_result'].get('error') else 'partially_executed' if any(r.get('status') in ('failed','blocked') for r in all_rcd) else 'visual_review_pending'),
                'images':images,'issues':all_issues,'rcd':all_rcd,'coverage':coverage,'visual_passed':False,
                'rejected_programs':all_rejected,'review_audits':review_audits,'request_limit':request_limit,'final_model_visual_review':False,'last_feedback':feedback}
        result['effective_issues']=effective_issue_rows(all_issues)
        result['repair_candidates']=repair_candidates
        critical=[i for i in result['effective_issues'] if i.get('decision')=='confirmed' and i.get('category') in ('E','F','B','A','S1','D','S2')]
        from .followup import _landed
        result['emergency_unresolved']=[i['id'] for i in critical if not _landed(i,all_rcd+all_rejected)]
        if result['emergency_unresolved']:result['status']='emergency_unresolved'
        result['source_geometry_pending']=source_pending_ids(result['effective_issues'], all_rejected)
        if (result['source_geometry_pending'] and result['status'] in ('visual_review_pending','emergency_unresolved')
                and set(result['emergency_unresolved']) <= set(result['source_geometry_pending'])):
            result['status']='source_verification_pending'
        write_json(result_file,result)
        from .report import write_report
        from .followup import run_followup
        follow_dir=root.parent/(root.name+'-followup')
        try:
            result['followup']=run_followup(root,follow_dir,sender=sender)
        except Exception as exc:
            result['followup']={'opened':True,'status':'failed','error':type(exc).__name__+': '+str(exc)}
        from .followup import reconcile_followup
        follow_state=follow_dir/'execution/state.json'
        if result['followup'].get('status')=='completed':
            state=json.loads(follow_state.read_text(encoding='utf-8')) if follow_state.is_file() else {'images':images,'rcd':[]}
            result=reconcile_followup(result,state)
        write_json(result_file,result)
        write_report(root,inputs,result['effective_issues'],
                     list(result.get('effective_rcd',result['rcd']))+result['rejected_programs'],
                     coverage,output_images=result['images'],candidates=result['repair_candidates'])
        return result
