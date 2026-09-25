"""One look per category. The model decides; the host does not demand a second pass."""
from ..review_problem_first_v3.inspection_contract import inspection_regions


CATEGORIES = ('F', 'E', 'B', 'S1', 'D', 'S2')
PROMPT = '''这是第一次请求，交叠、对齐、字体公式、规则立方体、箭头、和原图完全不符一起找。programs 必须是空数组，不要写修复代码。
前面几类不要记图标缺失。看见就记。F 和 E 的 decision 用 confirmed。
F 交叠，贴住也算：
1. 几何体和文字的排列互相压住，或同一箭头、箭头头画了两层。
2. 文字、标题、几何该在框内，却贴边或伸出框。先写原因，可以多个：框、字、位置。
3. 省略号、虚线续接留在旧位置，或压在框上。
4. 内容画出整张图的边界。
原图本身就叠在一起的，不记。
E 对齐。原图里成对、对称、共轴、等高的结构要逐对检查。原图本来不对称的不要报，也不要把现图强行平均。现图自己左右看起来齐，不能代替原图的对称。
1. 成对箭头：两端高度、箭身长度、离中轴的距离。同起点或同底边，不算另一端已经对齐。
2. 用来示意的大图标、大几何：中心、边缘或轴线要对上。
3. 同一组的成员：中轴、两端高度、长度、间距都要看。
B 字体公式。字体不同没有关系，只要显示清晰、同一张图里大体统一。现有统一格式保留。文字本来显示正确就不要改。
公式要能用本地 MathJax 的 base、ams、newcommand 编译。只记这几类，decision 用 confirmed：上下标错了；根号一类符号编译错了；公式编译不出来。内容相同、只是位置错，归 E 或 F。不那么确定就标 uncertain。
S1 规则立方体。原图是正方体或长方体。身体可以分成几节，节线跟对应的边平行，格子是闭合的平行四边形。现图因为画法不再是正确的立方体，decision 用 confirmed：少了一个面、压成一块平面、邻面没有和主面共边；或者外壳还在，但分节线折成尖角、中间穿成三角、不跟边平行，节数或方向对不上原图，看起来是乱码。不要因为还有三个面、端点落在边上，就放过分节。不要把乱线当成纹理。几何已经正确、只是位置或交叠不对，归 E 或 F。颜色差异不记。主面顶边要跟原图一样斜，不要画成横平竖直的正面。顶面和侧面都要看得见。原图是多块立方体叠成一堆的，现图排成一条或一排扁块，也记，块数和叠法跟原图。分节折成尖角的那一块也要记，不要因为它整体还像一块方块就放过。每一个带分节的立方体都要单独看，包括最小的一块。节线不是闭合平行四边形就记。规则立方体单独再扫一遍已经给的 1/2 Crop。
D 箭头。只看这几件：头的尖和身的端点要尖对尖；方向跟原图一致；头的大小按原图像素；起点和终点是否落在框上，按原图。缺了、多了、方向反了、尖没对上、头的大小不对、该接框却悬空或该留空却接上，就记。decision 用 confirmed。不要把箭头当成交叠。
S2 和原图完全不符。这一类单独再扫一遍已经给的 1/2 Crop，对照里面的小贴块。颜色和原图完全不一致，或者这块东西完全没有，就记。decision 用 confirmed。这种要补上去。差一点点的颜色、位置不对，不归这类。
只看一次：整图原图对当前渲染、当前 SVG、以及已经给的 1/2 Crop。规则立方体、和原图完全不符，这两类各自再单独扫一遍 1/2 Crop。不要列区域编号，不要为没问题的地方写反证。
输出 compact_category_sweeps，顺序 F,E,B,S1,D,S2。没有问题的一类 candidates 为空数组。不要 other_sweep。'''

REPAIR_PROMPT = '''这是第二次请求。为已经列出的 F、E、B、S1、D、S2 一起写 programs。issues 原样带回，不要新增。
F 按原因改，可以多步。框就改容器的边，不要把内容缩进过小的框。字就改文字或符号。位置才平移。省略号和虚线跟着所属那一排走。
relations 用 predicate，不要写成 kind。separate 写正的 min_gap，contain 写正的 padding。legal_overlap 只有原图本身叠在一起才用。改框写在 operations，用 bp_patch。
每一条 relation 都要能对上当前 SVG 里已有的 id，否则程序不会运行。contain：内容写 subject_id，框写 object_id。也可以框写 container_ids、内容写 target_ids。separate：两个对象写 subject_id 和 object_id，或按这个顺序写进 target_ids。不要把框写进 neighbor_ids。
E 的端点高度或箭身长度不对时，按原图改端点或长度，不要只把整条平移到中心。对称的两侧都要改。大图标按原图的轴对齐。
B 只修编译不出来、上下标错误、根号一类符号编译错误。用 SP formula，tex 只能用 base、ams、newcommand 里能编译的命令。不要为了字体统一去改已经显示正确的文字。公式移动整体，不单挪一个字形。
S1 用 sp_replace，kind 是 geometry。没有分节的，data.shape 是 cuboid。原图身体分成几节的，包括分节线折乱的，data.shape 是 lattice，divisions 按原图正面和侧面各有几格，还是同一个物体，不要保留原来的折线。origin、u、v 定主面，depth 或 depth_length 加 depth_angle 定深度。各面颜色按原图。measurement_viewport 包住构造，target_tp 用现图该物体的范围，mode 用 contain。不要手绘 polygon，不要贴照片。u、v 跟原图主面一样斜，顶边斜就不要写成水平。depth 要让侧面看得见。多块叠成一堆的，按原图块数分成多块 cuboid，不要排成一条扁的。
D 用 sp_replace，kind 是 arrow。头的尖和身的端点重合。head_length、head_width 按原图像素。方向按原图。起点终点该接框就接到框上，该留空就留空。箭头程序 depends_on 为空。
S2 和原图完全不符。小贴块颜色和原图完全不一致，或这块完全没有的，用 sp_photo 从对应原图裁片切进来补上。
用 sp_photo 时必须写齐，缺一项程序不会运行。args.source_crop 是原图像素 [x,y,w,h]，要包住 full_object_xywh，并且落在原图内。args.crop_review 是 {object_complete:true, clipped:false, full_object_xywh:[x,y,w,h], edges_reviewed:{left:true,top:true,right:true,bottom:true}, evidence:原图这一块四边都在裁片内}。键名是 edges_reviewed，不要写成 sides。和 method 同级写 source_location：{basis:original_semantic, description:原图这一块}。填不齐就不要用 sp_photo。
alignment_checks 每项是 {id,target_ids,reference_ids,mode:center_x|center_y|left|right|top|bottom,tolerance:0.5,reference_evidence}。
convergence 是 {max_iterations:6, alignment_checks, repairs:[{check_id, method:tp_align|tp_transform|tp_fit, target_ids, args}]}。check_id 对上 relation 或 alignment_check 的 id。
互不依赖的程序 depends_on 为空。只含 D 或只含 S2 的程序 depends_on 必须是空数组，所以不要去改前面程序已经改过的同一个对象。其余程序先后改同一个对象时，后一个 depends_on 前一个的程序 id。
预检查不通过的程序不会运行。不要写修复理由长文。'''


def _object(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required, 'additionalProperties': False}


def _array(items):
    return {'type': 'array', 'items': items}


def build_schema(schedule, review_only=False):
    regions = inspection_regions(schedule)
    text = {'type': 'string'}
    refs = _array({'type': 'string'})
    region = {'type': 'integer', 'enum': [r['region'] for r in regions]}
    props = {}
    if not review_only:
        candidate = _object({
            'region': region, 'original_evidence': text, 'current_evidence': text,
            'decision': {'type': 'string', 'enum': ['confirmed', 'uncertain']},
            'issue_ids': refs,
        })
        props['compact_category_sweeps'] = _array(_object({
            'category': {'type': 'string', 'enum': list(CATEGORIES)},
            'whole_image_observation': text, 'svg_observation': text,
            'candidates': _array(candidate),
        }))
    props.update({name: _array({'type': 'object'}) for name in ('issues', 'programs', 'prior_issue_reviews')})
    return _object(props)


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, label):
    _need(isinstance(value, str) and bool(value.strip()), label + ' requires nonempty evidence')


def audit(schedule, plan, issues=None):
    report = {
        'coverage_kind': 'one_pass_decision',
        'records_complete': False, 'images_seen_verified': False,
        'semantic_completeness': 'not_assessed', 'visual_acceptance': 'not_assessed',
        'visual_passed': False, 'status': 'inspection_incomplete', 'errors': [],
        'limitations': ['One pass is a decision, not a second confirmation.',
                        'Execution and visual acceptance are separate.'],
    }
    try:
        catalog = inspection_regions(schedule)
        by_region = {r['region']: r for r in catalog}
        image_ids = {r['image_id'] for r in catalog}
        _need(isinstance(plan, dict), 'plan must be object')
        sweeps = plan.get('compact_category_sweeps')
        _need(isinstance(sweeps, list) and all(isinstance(s, dict) for s in sweeps), 'compact_category_sweeps required')
        _need([s.get('category') for s in sweeps] == list(CATEGORIES), 'category order must be ' + ' '.join(CATEGORIES))
        for sweep in sweeps:
            _text(sweep.get('whole_image_observation'), 'whole_image_observation')
            _text(sweep.get('svg_observation'), 'svg_observation')
            _need(isinstance(sweep.get('candidates'), list), 'candidates must be array')
        actual = plan.get('issues') if issues is None else issues
        _need(isinstance(actual, list), 'actual issues required')
        known = {}
        for issue in actual:
            _need(isinstance(issue, dict), 'issue must be object')
            ident = issue.get('id')
            _need(isinstance(ident, str) and bool(ident.strip()) and ident not in known, 'invalid/duplicate issue ID')
            _need(issue.get('category') in CATEGORIES and issue.get('image_id') in image_ids, 'issue category/image outside itinerary')
            _need(issue.get('decision') in ('confirmed', 'uncertain', 'preserved', 'duplicate'), 'invalid issue decision')
            known[ident] = issue
        linked = set()
        for sweep in sweeps:
            category = sweep['category']
            for row in sweep['candidates']:
                _need(isinstance(row, dict), 'candidate must be object')
                region_id = row.get('region')
                _need(type(region_id) is int and region_id in by_region, 'candidate region is not a host identity')
                _text(row.get('original_evidence'), 'candidate original_evidence')
                _text(row.get('current_evidence'), 'candidate current_evidence')
                decision = row.get('decision')
                _need(decision in ('confirmed', 'uncertain'), 'invalid candidate decision')
                refs = row.get('issue_ids')
                _need(isinstance(refs, list) and all(isinstance(i, str) for i in refs) and refs, 'candidate requires issue_ids')
                _need(len(refs) == len(set(refs)), 'duplicate issue reference')
                for ident in refs:
                    _need(ident in known, 'unknown issue reference')
                    issue = known[ident]
                    _need(issue['category'] == category and issue['image_id'] == by_region[region_id]['image_id'],
                          'candidate issue category/image mismatch')
                    _need(issue['decision'] == decision, 'candidate and issue decision mismatch')
                    linked.add(ident)
        required = {i for i, issue in known.items() if issue['decision'] in ('confirmed', 'uncertain')}
        _need(required <= linked, 'confirmed/uncertain issue lacks same-category candidate')
        report.update(records_complete=True, status='one_pass_recorded',
                      candidate_count=sum(len(s['candidates']) for s in sweeps), linked_issue_count=len(linked))
    except (ValueError, TypeError, KeyError) as exc:
        report['errors'].append({'code': 'invalid_lean_inspection', 'message': str(exc)})
    return report
