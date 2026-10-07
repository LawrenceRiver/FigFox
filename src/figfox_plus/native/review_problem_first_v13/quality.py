"""Local execution acceptance gates. Pixel checks are not semantic visual acceptance."""
import math
from PIL import Image
from ..tight_tp import measure_tight, union_tight
from ..single_call.executor import _resolve_id, _relation_report, _perform

POLICY='''
Highest priority: zero tolerance for E (Alignment and Symmetry) and F (Overlap and Overflow). Inspect each category once and then make the determination. Except for clearly intentional overlaps present in the original figure, any overlap, boundary contact, or overflow is an immediate defect; do not wait for secondary confirmation. Mark legal_overlap only when supported by source evidence. All confirmed E/F defects must have repair programs; providing unresolved_reason does not count as completion.
E/F programs must include convergence={max_iterations:6,alignment_checks:[],repairs:[]}. E must have alignment_checks, each item being {id,target_ids,reference_ids,mode:center_x|center_y|left|right|top|bottom,tolerance:0.5,reference_evidence:semantic alignment relation from the original figure}; 0.5 allows only measurement error. F must have relations containing contain or separate, and including relevant neighbors. Each repairs item is {check_id,method:tp_align|tp_fit|tp_transform,target_ids,args}, with check_id matching the id of an alignment_check or relation. Relations are checked on rendered tight bounding boxes, including stroke and arrowheads. Do not require separate between source-intended connector junctions or shared endpoints. With repairs:[], the initial operations must satisfy every declared relation; a check alone cannot correct geometry. First execute original operations, then loop over the latest TP checks, executing the corresponding repair on failure; repairs that move elements by translation must use $measure/$calc to compute the latest delta, rather than iteratively accumulating fixed translations. Passing two consecutive times is required for measured convergence, with the second pass again including neighbors; non-convergence triggers rollback and marking as unresolved. Visual acceptance is still required.
If sp_photo appears, crop_review must have object_complete true, clipped false, full_object_xywh, and all four edges reviewed. source_crop must enclose the complete object. If the crop is incomplete, do not use sp_photo.
'''

def _luma(pixel):
    if isinstance(pixel,int):return float(pixel)
    return 0.2126*pixel[0]+0.7152*pixel[1]+0.0722*pixel[2]


def perimeter_std(image, box):
    x,y,w,h=[int(round(v)) for v in box]
    x=max(0,min(x,image.width-1));y=max(0,min(y,image.height-1))
    w=max(1,min(w,image.width-x));h=max(1,min(h,image.height-y))
    samples=[]
    for i in range(w):
        samples.append(_luma(image.getpixel((x+i,y))))
        samples.append(_luma(image.getpixel((x+i,min(image.height-1,y+h-1)))))
    for j in range(h):
        samples.append(_luma(image.getpixel((x,y+j))))
        samples.append(_luma(image.getpixel((min(image.width-1,x+w-1),y+j))))
    mean=sum(samples)/len(samples)
    return (sum((v-mean)**2 for v in samples)/len(samples))**0.5


def inset_frame_crop(image, frame, content, max_steps=80):
    """Shrink a frame crop one pixel at a time until its rim is no longer a flat border.

    The returned crop still contains content. This does not decide what the subject is.
    """
    x,y,w,h=[float(v) for v in frame]
    cx,cy,cw,ch=[float(v) for v in content]
    applied=0
    while applied<max_steps and perimeter_std(image,[x,y,w,h])<=18:
        nx,ny,nw,nh=x+1,y+1,w-2,h-2
        if nw<cw or nh<ch or nx>cx or ny>cy or nx+nw<cx+cw or ny+nh<cy+ch:
            break
        x,y,w,h=nx,ny,nw,nh
        applied+=1
    return [x,y,w,h],applied


def _box(value, what):
    if not isinstance(value,list) or len(value)!=4 or any(isinstance(v,bool) or not isinstance(v,(float,int)) or not math.isfinite(v) for v in value) or min(value[2:])<=0:
        raise ValueError('crop rejected: finite '+what+' xywh required')
    return [float(v) for v in value]


def crop_gate(op, original):
    if op.get('method')=='bp_program':
        for child in op.get('args',{}).get('operations',[]):crop_gate(child,original)
    if op.get('method')!='sp_photo':return
    proof=op.get('crop_review',op.get('args',{}).get('crop_review',{}))
    if not isinstance(proof,dict):proof={}
    if proof.get('object_complete') is not True or proof.get('clipped') is not False or not str(proof.get('evidence','')).strip():raise ValueError('crop rejected: whole-object visual evidence required')
    if any(proof.get('edges_reviewed',{}).get(k) is not True for k in ('left','top','right','bottom')):raise ValueError('crop rejected: all object edges must be reviewed')
    crop=_box(op['args'].get('source_crop'),'source_crop')
    obj=_box(proof.get('full_object_xywh'),'full_object')
    frame=proof.get('frame_xywh',op['args'].get('frame_xywh'))
    if frame is not None:
        fx,fy,fw,fh=_box(frame,'frame')
        x,y,w,h=crop
        if not (x>fx and y>fy and x+w<fx+fw and y+h<fy+fh):
            raise ValueError('crop rejected: source_crop must sit inside the frame edges')
    with Image.open(original) as im:
        rgb=im.convert('RGB');w,h=rgb.size
    x,y,cw,ch=crop;a,b,ow,oh=obj
    if not (0<=x<=a and 0<=y<=b and a+ow<=x+cw<=w and b+oh<=y+ch<=h):raise ValueError('crop rejected: incomplete object or crop outside original')

def _positive(value):
    return not isinstance(value,bool) and isinstance(value,(int,float)) and math.isfinite(value) and value>0


def validate_contract(p, selected, allowed, objects):
    emergency={i['category'] for i in selected}&{'E','F'}
    if not emergency:return
    c=p.get('convergence',{})
    limit=c.get('max_iterations')
    if not isinstance(limit,int) or isinstance(limit,bool) or not 2<=limit<=8:raise ValueError('emergency requires bounded convergence (2..8)')
    checks=c.get('alignment_checks',[]);rules=p.get('relations',[])
    if 'E' in emergency and not checks:raise ValueError('alignment requires measurable checks')
    if 'F' in emergency and not any(r.get('predicate') in ('contain','separate') for r in rules):raise ValueError('overlap/overflow requires illegal-overlap checks')
    for rule in rules:
        if rule.get('predicate')=='separate' and not _positive(rule.get('min_gap')):raise ValueError('separate requires a positive min_gap; touching counts as overlap')
        if rule.get('predicate')=='contain' and not _positive(rule.get('padding')):raise ValueError('contain requires a positive padding; flush edges count as overlap')
    ids={r['id'] for r in rules}
    for q in checks:
        if not q.get('id') or q['id'] in ids:raise ValueError('check IDs must be unique')
        ids.add(q['id'])
        if not q.get('target_ids') or not q.get('reference_ids') or not set(q['target_ids']+q['reference_ids'])<=allowed:raise ValueError('alignment check outside scope')
        if q.get('mode') not in ('center_x','center_y','left','right','top','bottom') or not q.get('reference_evidence'):raise ValueError('alignment check requires original relation')
        t=q.get('tolerance',.5)
        if isinstance(t,bool) or not isinstance(t,(int,float)) or not 0<=t<=.5:raise ValueError('alignment tolerance exceeds measurement allowance')
    for op in c.get('repairs',[]):
        if op.get('check_id') not in ids or op.get('method') not in ('tp_align','tp_fit','tp_transform') or not op.get('target_ids') or not set(op['target_ids'])<=objects or not isinstance(op.get('args'),dict):raise ValueError('invalid convergence repair scope')

class ConvergenceError(ValueError):
    def __init__(self,message,history):
        super().__init__(message)
        self.report={'status':'unresolved','history':history,'visual_acceptance':'pending'}


def converge(root,p,issue,original,folder,aliases,results):
    c=p['convergence'];history=[];clean=0
    for iteration in range(c['max_iterations']):
        failed=[];checks=[]
        if p.get('relations'):
            report=_relation_report(root,p['relations'],aliases)
            failed.extend(r['id'] for r in report['relations'] if r['status']!='satisfied')
            checks.append(report)
        for q in c.get('alignment_checks',[]):
            left=[_resolve_id(t,aliases) for t in q['target_ids']];right=[_resolve_id(t,aliases) for t in q['reference_ids']]
            tp=measure_tight(root,list(set(left+right)))
            a=union_tight(tp,left);b=union_tight(tp,right)
            mode=q['mode'];edge={'center_x':'cx','center_y':'cy'}.get(mode,mode)
            def value(box):
                if edge=='cx':return (box['left']+box['right'])/2
                if edge=='cy':return (box['top']+box['bottom'])/2
                return box[edge]
            delta=abs(value(a)-value(b));checks.append({'id':q['id'],'delta':delta})
            if delta>q.get('tolerance',.5):failed.append(q['id'])
        history.append({'iteration':iteration+1,'failed':failed,'checks':checks})
        if not failed:
            clean+=1
            if clean==2:return {'status':'measured_converged','history':history,'visual_acceptance':'pending'}
            continue
        clean=0;repairs=[op for op in c.get('repairs',[]) if op['check_id'] in failed]
        if not repairs:raise ConvergenceError('emergency unresolved: '+','.join(failed),history)
        for j,op in enumerate(repairs):_perform(root,op,issue,original,folder/f'loop-{iteration}-{j}',aliases,results)
    raise ConvergenceError('emergency unresolved: convergence limit reached',history)
