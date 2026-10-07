"""One receipt-driven request. It runs only for priority issues that did not land."""
import hashlib
from copy import deepcopy
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ...state import write_json
from .source_geometry import REPAIR_POLICY
from ..color_guard import BOUNDARY_REPAIR
from .issues import effective_issue_rows, source_pending_ids

PRIORITY = ('F', 'E', 'S1', 'S2')
LANDED = ('changed_unverified', 'executed_no_change')

PROMPT = '''This is the one-time receipt-driven followup request. Address only the unlanded issues in the list. Do not add new issues; do not rewrite issues that have already landed.
convergence.repairs permits ONLY tp_align, tp_fit or tp_transform. Put bp_patch, bp_remove and construction operations in args.operations, never in repairs. Use repairs:[] if the initial operations suffice. Do not repeat fixed translations/scales in a repair loop; compute any remaining delta from current measurements. Do not weaken a failed relation or delete its participants just to pass the check.
D Arrow defects: use sp_replace with kind:"arrow" and the method-pack arrow data contract; dependencies follow the same scope rule as every other category. Do not submit a BP-only arrow repair. B Formula defects: use SP text/formula as specified by the method pack. A Semantic defects: follow the method pack and preserve unrelated content.
Each relation requires a unique non-empty id. Reference that exact id as check_id in convergence.repairs.
Use repairs:[] when no corrective action is supplied. A repair action requires check_id, method, target_ids and args; a check_id alone is not an action. Relations are always checked even when repairs is empty.
All provided 1/2 Crop pairs are available for inspection. The first image in each pair is the original-figure crop; the second is the current-render crop. For each issue, select the pair_id of the 1/2 Crop pair that contains it, use that pair as the repair reference, and then write the program according to category.
The full latest render and the current SVG reflect results after the previous execution round. Programs must modify this current SVG.
F Overlap and Overflow. Repair according to the identified reason. In relations, use predicate; do not write kind. For separate, specify a positive min_gap; for contain, specify a positive padding. contain: specify content as subject_id and frame as object_id, or specify frame as container_ids and content as target_ids. separate: specify the two objects as subject_id and object_id. Do not put frames into neighbor_ids. Frame modifications belong in operations using bp_patch. convergence is required, with max_iterations as 6.
E Alignment and Symmetry. When endpoint heights or arrow shaft lengths are incorrect, modify endpoints or lengths according to the original figure; do not merely move the entire arrow to the center. Both symmetric sides must be modified. convergence is required, with max_iterations as 6.
S1 Regular Cuboids and Lattices. Reinspect original depth and supply independent source_geometry proofs as described below. Preserve planar or uncertain objects; match actual source projection and visible faces.
S2 Inconsistent Patches and Structural Boundaries. Restore an existing outline with bp_patch and original-pixel stroke/style evidence, preserving children; do not rasterize the whole panel. For a small missing or inconsistent image patch, use sp_photo. args.source_crop specifies original figure pixels [x,y,w,h], which must enclose full_object_xywh and fall entirely within the original figure. args.crop_review is {object_complete:true, clipped:false, full_object_xywh:[x,y,w,h], edges_reviewed:{left:true,top:true,right:true,bottom:true}, evidence:all four edges of this element in the original figure fall inside the crop}. The key name is edges_reviewed; do not write sides. At the same level as method, provide source_location: {basis:original_semantic, description:this element in the original figure}. Omit unused optional settings. For every category, programs mutating the same SVG object or overlapping group/child scopes must declare depends_on on the preceding program; independent scopes use []. This includes adding an outline to a group whose children another program changes.
Each item in programs is {id,issue_ids,image_id,base_revision,phase:preconstructor|reconstructor,route:module_program,target_ids,depends_on:[],rcd_predescription,args,relations?,convergence?}. For module programs, args={operations:[{method,target_ids,args}]}. base_revision uses the current revision in the message. issue_ids can only contain IDs from the list. Retain the listed issue IDs/evidence; an explicitly reviewed false or uncertain S1 detection may be downgraded under the source policy below. Echo other issues unchanged; do not add new issues. Programs with incomplete fields will not execute. Do not write lengthy repair rationales.''' + '\n' + REPAIR_POLICY + '\n' + BOUNDARY_REPAIR


def _landed(issue, receipts):
    matched = [row for row in receipts if issue['id'] in (row.get('issue_ids') or [])]
    if not matched or any(row.get('status') not in LANDED for row in matched):
        return False
    if issue.get('category') in ('F', 'E'):
        return all((row.get('final_scene_check') or {}).get('status') == 'measured_converged' for row in matched)
    return True


def _receipts(result):
    if 'effective_rcd' in result:
        return list(result['effective_rcd'] or [])
    return list(result.get('rcd') or []) + list(result.get('rejected_programs') or [])


def _audit_prior_geometry(root, result, state, followed):
    """Recheck retained E/F receipts against the final scene without applying repairs."""
    from .quality import converge, ConvergenceError
    programs = {}
    aliases = {}
    for path in sorted(root.glob('phase-*/normalized-programs.json')):
        programs.update({p['id']: p for p in json.loads(path.read_text(encoding='utf-8'))})
        checkpoint = path.parent / 'execution/state.json'
        if checkpoint.is_file():
            for image_id, mapping in json.loads(checkpoint.read_text(encoding='utf-8')).get('aliases', {}).items():
                aliases.setdefault(image_id, {}).update(mapping)
    for image_id, mapping in state.get('aliases', {}).items():
        aliases.setdefault(image_id, {}).update(mapping)
    issues = {i['id']: i for i in result.get('effective_issues', effective_issue_rows(result.get('issues') or []))}
    checks = {}
    for row in _receipts(result):
        if row.get('status') not in LANDED or not any(
                ref not in followed and issues.get(ref, {}).get('category') in ('E', 'F')
                for ref in row.get('issue_ids', [])):
            continue
        image_id, program_id = row['image_id'], row['program_id']
        final = state.get('images', {}).get(image_id)
        if not final or final['revision'] == result['images'][image_id]['revision']:
            continue
        try:
            audit = deepcopy(programs[program_id])
            audit['convergence']['repairs'] = []
            audit['convergence']['max_iterations'] = 2
            scene = ET.parse(final['svg']).getroot()
            checks[program_id] = converge(scene, audit, {}, result['images'][image_id]['original'],
                                           root / 'followup-final-audit', aliases.get(image_id, {}), {})
        except Exception as exc:
            checks[program_id] = {'status': 'unresolved', 'error': str(exc)}
            if isinstance(exc, ConvergenceError):
                checks[program_id].update(exc.report)
        checks[program_id]['revision'] = final['revision']
    return checks


def reconcile_followup(result, state):
    """Derive the final status from committed receipts, retaining failed history."""
    if (result.get('followup') or {}).get('status')!='completed':
        return result
    final=deepcopy(result)
    final['repair_candidates']=list(result.get('repair_candidates') or [])+list(result['followup'].get('repair_candidates') or [])
    previous=_receipts(result)
    effective=effective_issue_rows(list(result.get('effective_issues',result.get('issues')) or [])
                                 + list(result['followup'].get('effective_issues') or []))
    final['effective_issues']=effective
    all_issues={i['id']:i for i in effective}
    issues={key:i for key,i in all_issues.items() if i.get('decision')=='confirmed'}
    followed=set(result['followup'].get('issue_ids',[])) or {key for r in state.get('rcd',[]) for key in r.get('issue_ids',[])}
    # A rejected program affects its own issues, not every successful program
    # in that round. Preserve original rcd separately as immutable history.
    receipts=[]
    for row in previous:
        remaining=[key for key in row.get('issue_ids',[]) if key not in followed]
        if remaining:
            retained=deepcopy(row)
            retained['issue_ids']=remaining
            checked=result['followup'].get('prior_scene_checks',{}).get(row.get('program_id'))
            if checked is not None:
                retained['final_scene_check']=deepcopy(checked)
            receipts.append(retained)
    receipts.extend(state.get('rcd') or [])
    receipts.extend(result['followup'].get('rejected_programs') or [])
    final['effective_rcd']=receipts
    def finally_landed(key):
        if key not in all_issues:return False
        return _landed(all_issues[key],receipts)
    unresolved={key for key in issues if not finally_landed(key)}
    critical={key for key,issue in issues.items() if issue.get('category') in ('F','E','B','A','S1','D','S2')}
    unrecovered_failure=any(r.get('status') in ('failed','blocked') and (
        not r.get('issue_ids') or any(not finally_landed(key)
                                    for key in r['issue_ids'])) for r in receipts)
    final.setdefault('status_before_followup',result.get('status'))
    final['emergency_unresolved']=sorted(unresolved & critical)
    final['images']=state.get('images') or result['images']
    if not result.get('coverage',{}).get('records_complete'):
        final['status']='inspection_incomplete'
    elif final['emergency_unresolved']:
        final['status']='emergency_unresolved'
    elif unresolved or unrecovered_failure:
        final['status']='partially_executed'
    else:
        final['status']='visual_review_pending'
    final['source_geometry_pending']=source_pending_ids(effective, receipts)
    if (final['source_geometry_pending'] and final['status'] in ('visual_review_pending','emergency_unresolved')
            and set(final['emergency_unresolved']) <= set(final['source_geometry_pending'])):
        final['status']='source_verification_pending'
    final['visual_passed']=False
    return final


def open_issues(result):
    """Confirmed supported critical issues with no complete committed repair."""
    if not isinstance(result, dict):
        return []
    chosen = {}
    for issue in result.get('effective_issues',effective_issue_rows(result.get('issues') or [])):
        if not isinstance(issue, dict) or issue.get('decision') != 'confirmed':
            continue
        if issue.get('category') not in PRIORITY or not isinstance(issue.get('id'), str):
            continue
        chosen[issue['id']] = issue
    receipts = _receipts(result)
    opened = []
    for issue in chosen.values():
        if _landed(issue, receipts):
            continue
        errors = []
        for row in receipts:
            if issue['id'] not in (row.get('issue_ids') or []):
                continue
            if row.get('status') in LANDED and issue.get('category') not in ('F', 'E'):
                continue
            if row.get('status') in LANDED and (row.get('final_scene_check') or {}).get('status') == 'measured_converged':
                continue
            errors.append({'program_id': row.get('program_id') or row.get('id'),
                           'status': row.get('status'), 'error': row.get('error')})
        opened.append({'id': issue['id'], 'image_id': issue.get('image_id'), 'category': issue['category'],
                       'description': issue.get('description'), 'target_ids': issue.get('target_ids'),
                       'neighbor_ids': issue.get('neighbor_ids'), 'original_evidence': issue.get('original_evidence'),
                       'current_evidence': issue.get('current_evidence'), 'decision': issue.get('decision'),
                       'receipt': errors})
    return opened


def run_followup(task_dir, out_dir, *, sender=None):
    """Send one request for open priority issues. A clear receipt does not call the model."""
    root = Path(task_dir).resolve()
    result = json.loads((root / 'result.json').read_text(encoding='utf-8'))
    opened = open_issues(result)
    if not opened:
        return {'opened': False, 'status': 'not_opened', 'issue_ids': []}
    out = Path(out_dir).resolve()
    if out == root or root in out.parents or out in root.parents:
        raise ValueError('follow-up directory must be outside the finished task')
    out.mkdir(parents=True, exist_ok=False)
    write_json(out / 'open-issues.json', opened)
    from .orchestrator import _image, _plan, _svg_text, _tools_for
    from .transport import send
    inputs = json.loads((root / 'inputs.json').read_text(encoding='utf-8'))
    schedule = json.loads((root / 'schedule.json').read_text(encoding='utf-8'))
    methods = json.loads((root / 'methods.json').read_text(encoding='utf-8'))
    image_id = opened[0]['image_id']
    current = result['images'][image_id]
    catalog = inputs['images'][image_id]
    content = [{'type': 'text', 'text': json.dumps({
        'revision': current['revision'],
        'current_svg': _svg_text(Path(current['svg']).read_text(encoding='utf-8')),
        'open_issues': opened,
        'method_pack': methods,
        'instruction': PROMPT,
    }, ensure_ascii=False)}]
    content.append({'type': 'text', 'text': 'Full original figure'})
    content.extend(_image(catalog['original_png']))
    latest = Path(current['png']).read_bytes()
    content.append({'type': 'text', 'text': 'Full latest render'})
    content.extend(_image({'path': current['png'], 'asset_id': image_id + '/latest-render',
                           'sha256': hashlib.sha256(latest).hexdigest()}))
    # Crops in the original bundle predate previous repairs. Regenerate the
    # current side from this round's committed render using the saved mapping.
    from PIL import Image
    crop_audit=[]
    for index,pair in enumerate(catalog['crop_pairs']):
        mapping=pair['display_mapping']['current']
        with Image.open(current['png']) as rendered:
            crop=rendered.crop(tuple(mapping))
            crop_path=out/f'current-crop-{index:03d}.png'
            crop.save(crop_path)
        current_asset={'path':str(crop_path),'sha256':hashlib.sha256(crop_path.read_bytes()).hexdigest(),
                       'asset_id':pair['current_asset']['asset_id'],'dimensions':list(crop.size)}
        crop_audit.append({'pair_id':pair['pair_id'],'mapping':mapping,'revision':current['revision'],**current_asset})
        content.append({'type': 'text', 'text': '1/2 Crop ' + pair['pair_id'] + '. The first image is the original-figure crop; the second is the current-render crop.'})
        content.extend(_image(pair['original_asset']))
        content.extend(_image(current_asset))
    write_json(out/'current-crops.json',crop_audit)
    messages = [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': content}]
    write_json(out / 'messages.json', {'crop_pairs': len(catalog['crop_pairs']), 'issue_ids': [row['id'] for row in opened]})
    message = (sender or send)(messages, _tools_for(schedule, review_only=True), out, request_limit=1)
    write_json(out / 'message.json', message)
    known = {node.get('id') for node in ET.parse(current['svg']).getroot().iter() if node.get('id')}
    issues = []
    for row in opened:
        issue = dict(row)
        issue.pop('receipt', None)
        issue['target_ids'] = [item for item in (issue.get('target_ids') or []) if item in known]
        issue['neighbor_ids'] = [item for item in (issue.get('neighbor_ids') or []) if item in known]
        issues.append(issue)
    images = {image_id: {'svg': current['svg'], 'png': current['png'], 'original': catalog['original_png']['path'],
                         'revision': current['revision']}}
    plan, _call_id = _plan(message, schedule, review_only=True,
                          repair_context={'issues':issues,'images':images})
    allowed = {row['id'] for row in opened}
    programs = [program for program in plan.get('programs') or []
                if isinstance(program, dict) and set(program.get('issue_ids') or []) <= allowed and program.get('issue_ids')]
    dropped = [program.get('id') for program in plan.get('programs') or []
               if isinstance(program, dict) and program not in programs]
    reviewed={i['id']:i for i in effective_issue_rows(issues + plan.get('issues', []))}
    # Followup scope is fixed. Only an evidenced S1 downgrade changes detection;
    # never accept new targets or unrelated issue rewrites from this response.
    for issue in issues:
        candidate=reviewed.get(issue['id'],{})
        if issue.get('category')=='S1' and candidate.get('decision') in ('preserved','uncertain'):
            issue['decision']=candidate['decision']
            issue['source_review']=candidate['source_review']
    plan['issues'] = issues
    plan['programs'] = programs
    write_json(out / 'plan.json', {'programs': [program.get('id') for program in programs], 'dropped_program_ids': dropped})
    from .issues import validate_issues
    from .programs import execute_programs
    from .replay import filter_program_shapes, select_valid_programs
    programs, shape_rejected = filter_program_shapes(programs)
    validate_issues(issues, programs, images)
    accepted, rejected = select_valid_programs(programs, issues, images)
    write_json(out / 'program-preflight.json', {'accepted': [program['id'] for program in accepted], 'rejected': rejected,
                                                 'shape_rejected': shape_rejected, 'dropped_program_ids': dropped})
    execution = {'status': 'no_accepted_program', 'rcd': []}
    if accepted:
        execution = execute_programs(accepted, issues, images, out / 'execution')
    prior_checks = _audit_prior_geometry(root, result, execution, allowed)
    summary = {'opened': True, 'status': 'completed', 'execution_directory':str(out/'execution'), 'issue_ids': [row['id'] for row in opened],
               'accepted': [program['id'] for program in accepted],
               'rejected': [row.get('program_id') for row in rejected],
               'rejected_programs': rejected + shape_rejected,
               'effective_issues': issues,
               'repair_candidates': [],
               'prior_scene_checks': prior_checks,
               'dropped_program_ids': dropped,
               'rcd': [{'program_id': row.get('program_id'), 'issue_ids': row.get('issue_ids'), 'status': row.get('status'),
                        'error': row.get('error')} for row in execution.get('rcd') or []]}
    write_json(out / 'followup-result.json', summary)
    return summary
