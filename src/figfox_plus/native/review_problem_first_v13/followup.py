"""One receipt-driven request. It runs only for priority issues that did not land."""
import hashlib
import json
import xml.etree.ElementTree as ET
from pathlib import Path

from ...state import write_json

PRIORITY = ('F', 'E', 'S1', 'S2')
LANDED = ('changed_unverified', 'executed_no_change')

PROMPT = '''这是回执之后的一次请求，只此一次。只处理清单里还没落地的问题。不要新增问题，不要重写已经落地的问题。
已经给的 1/2 Crop 全部可以看。每一对的第一张是原图，第二张是当前渲染。每个问题都要选定包含它的那一个 pair_id，对着这一对来改，再按类别写程序。
整张最新渲染和当前 SVG 是上一轮执行之后的结果。程序要改这份当前 SVG。
F 交叠。按原因改。relations 用 predicate，不要写成 kind。separate 写正的 min_gap，contain 写正的 padding。contain：内容写 subject_id，框写 object_id。也可以框写 container_ids、内容写 target_ids。separate：两个对象写 subject_id 和 object_id。不要把框写进 neighbor_ids。改框写在 operations，用 bp_patch。要写 convergence，max_iterations 用 6。
E 对齐。端点高度或箭身长度不对时，按原图改端点或长度，不要只把整条平移到中心。对称的两侧都要改。要写 convergence，max_iterations 用 6。
S1 规则立方体。用 sp_replace，kind 是 geometry。没有分节的，data.shape 是 cuboid。有分节的，data.shape 是 lattice。不要手绘 polygon，不要贴照片。主面要斜，侧面要看得见。
S2 和原图完全不符。用 sp_photo 从对应原图裁片切进来补上。args.source_crop 是原图像素 [x,y,w,h]，要包住 full_object_xywh，并且落在原图内。args.crop_review 是 {object_complete:true, clipped:false, full_object_xywh:[x,y,w,h], edges_reviewed:{left:true,top:true,right:true,bottom:true}, evidence:原图这一块四边都在裁片内}。键名是 edges_reviewed，不要写成 sides。和 method 同级写 source_location：{basis:original_semantic, description:原图这一块}。只含 S2 的程序 depends_on 必须是空数组。
programs每项{id,issue_ids,image_id,base_revision,phase:preconstructor|reconstructor,route:module_program,target_ids,depends_on:[],rcd_predescription,args,relations?,convergence?}。模块程序 args={operations:[{method,target_ids,args}]}。base_revision 用消息里的当前 revision。issue_ids 只能是清单里的 id。issues 原样带回清单，不要新增。字段不齐的程序不会运行。不要写修复理由长文。'''


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
    content.append({'type': 'text', 'text': '整张原图'})
    content.extend(_image(catalog['original_png']))
    latest = Path(current['png']).read_bytes()
    content.append({'type': 'text', 'text': '整张最新渲染'})
    content.extend(_image({'path': current['png'], 'asset_id': image_id + '/latest-render',
                           'sha256': hashlib.sha256(latest).hexdigest()}))
    for pair in catalog['crop_pairs']:
        content.append({'type': 'text', 'text': '1/2 Crop ' + pair['pair_id'] + '。第一张是原图，第二张是当前渲染。'})
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
