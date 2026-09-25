"""Problem-first inspection; host changes encoding, never supplies observations."""
from copy import deepcopy
from .inspection_contract import CATEGORIES, inspection_regions, expand_observations, _CHECK, _text, audit_inspection

PROMPT = '''按问题类型串联检查，不能先随意看全图再挑几个容易修的问题。
主顺序固定 E对齐 → F交叠/触边/出框 → B文字公式 → A知识内容、语义图标和箭头连接 → S1明显几何错误。
首次请求对一个类型做完以下整个行程，才进入下一类型：原图PNG对比现图PNG；结合原图检查现SVG；核对该类有关的全图现TP与结构候选；逐一查看全部既有配对Crop；再把同批Crop过一遍查漏和反证。上游Crop已经完成，禁止重新按疑点裁图替代它。每类都从头到尾看，不能以其他类型已看过代替。第二次请求若宿主确认首次记录完整，只需针对新全图逐问题复核和给纠正程序，无需重交旧三轮记录；若首次记录不完整，仍要以初始资产补齐，旧Crop不能冒充修复后的新图证据。
E先认出绑定整体、参照轴、成组对称和对应高度，再比较成员及邻居。F逐对象检查实际边缘、留白和容器，TP相交只是候选；正常包含、原图有意交叠不报错。B检查字序、符号、上下标、可读性，不能只挑字体细微差异。A沿每条连线从起点到终点核对方向、头部数量、箭身、连接与缺失；同时核对语义图标代表的物件身份。S1检查面边顶点是否能组成合理物体、长宽深关系、组合次序和局部乱码；普通示意波形、纹理或风格差异不等于几何损坏。原照片变成虚构几何也需确认。
如有 upstream_arrow_evidence，先借上游SAM锁定箭头候选，再用本轮原图与现图复核一次。SAM会漏检、误把字母识别为箭头，不是答案；原图资产坐标只用于原图候选，现图位置仍从语义与SVG/TP独立确定。未提供SAM就如实仅使用当前证据。
每类输出category_sweeps中的一项，按category_itinerary顺序给records。每条region绑定宿主区域，包含state、original_observation、current_observation、issue_ids；E/F加candidate_check，每类第一轮全图加svg_observation。只给简短可核实观察，不输出内部思维；不确定写uncertain，禁止补造或写“正常/同上”代替。
最后other_sweep再扫缺失和其余问题：examined_regions覆盖全部区域；findings每项给regions、decision(missed_primary|secondary|uncertain|ignored)、issue_ids及evidence。确凿主要漏检加入issues原有五类，并在相应主类记录引用；次要差异保留说明，不能替代主问题。没有额外发现时findings可空并给summary。不能预先否定真实缺失，也不能为了数量制造错误。
发现与修复分别评价，不能因为不会修而不报。定位先写主体、对象、周围关系，再绑定现图ID。TP仅现图，不能用于定位原图。保留完整方法库、生成动态代码、依赖顺序与实际RCD。一次输出中的完整记录只能证明提交了证据，不能冒称已证明没有漏检。
'''

def category_itinerary(schedule):
    regions=inspection_regions(schedule)
    return [{'category':c,'regions':deepcopy(regions)} for c in CATEGORIES]

def expand_category_sweeps(plan, schedule):
    regions=inspection_regions(schedule)
    sweeps=plan.get('category_sweeps')
    if not isinstance(sweeps,list) or [s.get('category') for s in sweeps]!=list(CATEGORIES):
        raise ValueError('category order must be E F B A S1')
    expected=[r['region'] for r in regions]
    combined={r['region']:{'region':r['region'],'checks':{}} for r in regions}
    for sweep in sweeps:
        records=sweep.get('records');category=sweep['category']
        if not isinstance(records,list) or [r.get('region') for r in records]!=expected:
            raise ValueError('region coverage or order incomplete')
        for row, region in zip(records,regions):
            entry=deepcopy(row);entry.pop('region')
            svg=entry.pop('svg_observation',None)
            if region['pass']==1:
                if not isinstance(svg,str) or not svg.strip():raise ValueError('missing SVG observation')
                _text(svg,'svg_observation')
                target=combined[region['region']]
                target['svg_observation']=target.get('svg_observation','')+category+': '+svg+'\n'
            combined[region['region']]['checks'][category]=entry
    other=plan.get('other_sweep',{})
    if other.get('examined_regions')!=expected or not isinstance(other.get('summary'),str) or not other['summary'].strip():
        raise ValueError('other sweep requires region coverage and summary')
    _text(other['summary'],'other summary')
    findings=other.get('findings')
    if not isinstance(findings,list):raise ValueError('other findings required')
    known={i['id']:i for i in plan.get('issues',[])}
    for item in findings:
        if item.get('decision') not in ('missed_primary','secondary','uncertain','ignored') or not isinstance(item.get('evidence'),str):
            raise ValueError('other finding requires decision and evidence')
        _text(item['evidence'],'other finding evidence')
        ids=item.get('issue_ids');where=item.get('regions')
        if not isinstance(where,list) or not where or any(x not in expected for x in where):raise ValueError('other region invalid')
        if not isinstance(ids,list) or any(i not in known for i in ids):raise ValueError('other issue reference invalid')
        if item['decision']=='missed_primary' and (not ids or any(known[i].get('decision')!='confirmed' for i in ids)):
            raise ValueError('missed primary requires confirmed issue')
        if item['decision']=='missed_primary':
            for ident in ids:
                cat=known[ident].get('category')
                if cat not in CATEGORIES or not any(ident in combined[r]['checks'][cat]['issue_ids'] for r in where):
                    raise ValueError('missed primary must be linked to its region and category observation')
    out=deepcopy(plan);out['inspection_records']=[combined[i] for i in expected]
    expand_observations(out,schedule)
    return out

def audit_problem_first(schedule,plan,issues):
    return audit_inspection(schedule,expand_category_sweeps(plan,schedule),issues)

_record=deepcopy(_CHECK)
_record['properties'].update(region={'type':'integer','minimum':0},svg_observation={'type':'string'})
_record['required'].append('region')
SCHEMA={
 'category_sweeps':{'type':'array','minItems':5,'maxItems':5,'items':{
     'type':'object','properties':{'category':{'enum':list(CATEGORIES)},'records':{'type':'array','items':_record}},
     'required':['category','records'],'additionalProperties':False}},
 'other_sweep':{'type':'object','properties':{
     'examined_regions':{'type':'array','items':{'type':'integer'}},
     'summary':{'type':'string'},'findings':{'type':'array','items':{
        'type':'object','properties':{'regions':{'type':'array','items':{'type':'integer'}},
        'decision':{'enum':['missed_primary','secondary','uncertain','ignored']},
        'issue_ids':{'type':'array','items':{'type':'string'}},'evidence':{'type':'string'}},
        'required':['regions','decision','issue_ids','evidence'],'additionalProperties':False}}},
     'required':['examined_regions','summary','findings'],'additionalProperties':False}}
