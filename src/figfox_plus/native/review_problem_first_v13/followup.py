"""One receipt-driven request. It runs only for priority issues that did not land."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ...state import write_json

PRIORITY = ('F', 'E', 'S1', 'S2')
LANDED = ('changed_unverified', 'executed_no_change')

PROMPT = '''This is the one-time receipt-driven followup request. Address only the unlanded issues in the list. Do not add new issues; do not rewrite issues that have already landed.
All provided 1/2 Crop pairs are available for inspection. The first image in each pair is the original-figure crop; the second is the current-render crop. For each issue, select the pair_id of the 1/2 Crop pair that contains it, use that pair as the repair reference, and then write the program according to category.
The full latest render and the current SVG reflect results after the previous execution round. Programs must modify this current SVG.
F Overlap and Overflow. Repair according to the identified reason. In relations, use predicate; do not write kind. For separate, specify a positive min_gap; for contain, specify a positive padding. contain: specify content as subject_id and frame as object_id, or specify frame as container_ids and content as target_ids. separate: specify the two objects as subject_id and object_id. Do not put frames into neighbor_ids. Frame modifications belong in operations using bp_patch. convergence is required, with max_iterations as 6.
E Alignment and Symmetry. When endpoint heights or arrow shaft lengths are incorrect, modify endpoints or lengths according to the original figure; do not merely move the entire arrow to the center. Both symmetric sides must be modified. convergence is required, with max_iterations as 6.
S1 Regular Cuboids and Lattices. Use sp_replace with kind as geometry. If unsegmented, data.shape is cuboid. If segmented, data.shape is lattice. Do not hand-draw polygons; do not paste photos. The main face must be slanted, and the side face must be visible.
S2 Inconsistent Patches. Use sp_photo to crop the corresponding region from the original figure and patch it in. args.source_crop specifies original figure pixels [x,y,w,h], which must enclose full_object_xywh and fall entirely within the original figure. args.crop_review is {object_complete:true, clipped:false, full_object_xywh:[x,y,w,h], edges_reviewed:{left:true,top:true,right:true,bottom:true}, evidence:all four edges of this element in the original figure fall inside the crop}. The key name is edges_reviewed; do not write sides. At the same level as method, provide source_location: {basis:original_semantic, description:this element in the original figure}. Programs containing only S2 must have depends_on as an empty array [].
Each item in programs is {id,issue_ids,image_id,base_revision,phase:preconstructor|reconstructor,route:module_program,target_ids,depends_on:[],rcd_predescription,args,relations?,convergence?}. For module programs, args={operations:[{method,target_ids,args}]}. base_revision uses the current revision in the message. issue_ids can only contain IDs from the list. Return the listed issues unchanged; do not add new issues. Programs with incomplete fields will not execute. Do not write lengthy repair rationales.'''


def _landed(issue, receipts):
    matched = [row for row in receipts if issue['id'] in (row.get('issue_ids') or [])]
    ok = [row for row in matched if row.get('status') in LANDED]
    if issue.get('category') in ('F', 'E'):
        return any((row.get('final_scene_check') or {}).get('status') == 'measured_converged' for row in ok)
    return bool(ok)


def open_issues(result):
    """Confirmed F, E, S1, and already detected S2 that have no landed receipt."""
    if not isinstance(result, dict):
        return []
    chosen = {}
    for issue in result.get('issues') or []:
        if not isinstance(issue, dict) or issue.get('decision') != 'confirmed':
            continue
        if issue.get('category') not in PRIORITY or not isinstance(issue.get('id'), str):
            continue
        chosen[issue['id']] = issue
    receipts = list(result.get('rcd') or [])
    for row in result.get('rejected_programs') or []:
        if isinstance(row, dict):
            receipts.append(row)
    opened = []
    for issue in chosen.values():
        if _landed(issue, result.get('rcd') or []):
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
    result = json.loads((root / 'result.json').read_text())
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
    inputs = json.loads((root / 'inputs.json').read_text())
    schedule = json.loads((root / 'schedule.json').read_text())
    methods = json.loads((root / 'methods.json').read_text())
    image_id = opened[0]['image_id']
    current = result['images'][image_id]
    catalog = inputs['images'][image_id]
    content = [{'type': 'text', 'text': json.dumps({
        'revision': current['revision'],
        'current_svg': _svg_text(Path(current['svg']).read_text()),
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
    for pair in catalog['crop_pairs']:
        content.append({'type': 'text', 'text': '1/2 Crop ' + pair['pair_id'] + '. The first image is the original-figure crop; the second is the current-render crop.'})
        content.extend(_image(pair['original_asset']))
        content.extend(_image(pair['current_asset']))
    messages = [{'role': 'system', 'content': PROMPT}, {'role': 'user', 'content': content}]
    write_json(out / 'messages.json', {'crop_pairs': len(catalog['crop_pairs']), 'issue_ids': [row['id'] for row in opened]})
    message = (sender or send)(messages, _tools_for(schedule, review_only=True), out, request_limit=1)
    write_json(out / 'message.json', message)
    plan, _call_id = _plan(message, schedule, review_only=True)
    allowed = {row['id'] for row in opened}
    programs = [program for program in plan.get('programs') or []
                if isinstance(program, dict) and set(program.get('issue_ids') or []) <= allowed and program.get('issue_ids')]
    dropped = [program.get('id') for program in plan.get('programs') or []
               if isinstance(program, dict) and program not in programs]
    known = {node.get('id') for node in ET.parse(current['svg']).getroot().iter() if node.get('id')}
    issues = []
    for row in opened:
        issue = dict(row)
        issue.pop('receipt', None)
        issue['target_ids'] = [item for item in (issue.get('target_ids') or []) if item in known]
        issue['neighbor_ids'] = [item for item in (issue.get('neighbor_ids') or []) if item in known]
        issues.append(issue)
    plan['issues'] = issues
    plan['programs'] = programs
    write_json(out / 'plan.json', {'programs': [program.get('id') for program in programs], 'dropped_program_ids': dropped})
    from .issues import validate_issues
    from .programs import execute_programs
    from .replay import filter_program_shapes, select_valid_programs
    images = {image_id: {'svg': current['svg'], 'png': current['png'], 'original': catalog['original_png']['path'],
                         'revision': current['revision']}}
    programs, shape_rejected = filter_program_shapes(programs)
    validate_issues(issues, programs, images)
    accepted, rejected = select_valid_programs(programs, issues, images)
    write_json(out / 'program-preflight.json', {'accepted': [program['id'] for program in accepted], 'rejected': rejected,
                                                 'shape_rejected': shape_rejected, 'dropped_program_ids': dropped})
    execution = {'status': 'no_accepted_program', 'rcd': []}
    if accepted:
        execution = execute_programs(accepted, issues, images, out / 'execution')
    summary = {'opened': True, 'status': 'completed', 'issue_ids': [row['id'] for row in opened],
               'accepted': [program['id'] for program in accepted],
               'rejected': [row.get('program_id') for row in rejected],
               'dropped_program_ids': dropped,
               'rcd': [{'program_id': row.get('program_id'), 'issue_ids': row.get('issue_ids'), 'status': row.get('status'),
                        'error': row.get('error')} for row in execution.get('rcd') or []]}
    write_json(out / 'followup-result.json', summary)
    return summary
