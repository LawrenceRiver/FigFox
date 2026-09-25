"""Case-independent review methods, bound to the real TP/SP/BP implementation.

Only explicit package modules are inspected. No run directories, task reports,
annotations or private evaluation files are searched or loaded.
"""
from copy import deepcopy
import hashlib
import inspect
import json

from ...sp.catalog import CATALOG
from ...sp import geometry, content, arrows, compiler
from .. import tp_v2, sp_v2, repair_toolbox
from ..single_call.qlist import QLIST

ORDER = ('E', 'F', 'B', 'A', 'S1')
_LOCATION = '先描述主体、参照对象、附近文字、颜色和上下左右关系，再绑定当前 SVG 稳定对象身份；原图独立语义定位，不继承现图 TP 坐标。'
_RCD = '仅记录真实执行：问题与程序身份、方法版本、输入输出 revision、实际参数或代码哈希、结果与错误、回退链、本体和邻居检查、仍待视觉核验项。预描述不能冒充已修复。'
_POSITION_CHECK = '重新测量最新对象；先检查本体关系，再检查周围邻居及受影响的连接。机械无报警仍需原图视觉对照。'

# These are generic methods, not image-specific repair prescriptions.
_DETAILS = {
 'A': {
  'observe': ['检查文字、术语、拼写、公式知识含义；还要检查确定语义的图标身份、箭头方向、重复头部、缺失连接和结构成员。图标替换成另一类符号不是可忽略的风格差异，关系错误也不是相似度问题。'],
  'counterevidence': ['不因原图印刷小瑕疵强行复刻错误；没有可靠知识依据时标不确定，不臆造专业结论。'],
  'prepare_parameters': ['绑定当前文字或公式对象；给出旧内容、新内容、改正依据和需要保留的样式。', '记录对 B 排版步骤的依赖；改内容后对象宽度可能变化。'],
  'execute': ['BP bp_patch 的 text 修改合法 text 节点；公式更换 tex 后交 SP formula 构造。', '有混合字形或多行结构时先核对组成；bp_patch.text 会移除子节点，不能未经规划抹去原排版。'],
  'postcheck': ['复核知识含义及未改内容；内容变化后再进入 B 渲染、测量和布局。', _POSITION_CHECK],
  'fallback': ['知识依据不足保留未解决，不强制修改；执行失败回滚该事务。'],
  'methods': ['bp_patch','sp_replace'],
 },
 'B': {
  'observe': ['核对字形、字号、符号、上下标、分数、根号、基线及实际渲染；参照原图，保留 A 已纠正的内容。'],
  'counterevidence': ['不把所有布局冲突归为字体问题；内容相同但只是位置错误交 E/F。'],
  'prepare_parameters': ['确定当前 SVG 的对象身份、代码位置和样式；text 的 x/y 是基线，formula 的 x/y 是视口左上角。', '准备 kind、data、measurement_viewport、target_tp；构造视口与现图目标区域分开，保留非问题文字样式。'],
  'execute': ['SP text/formula 构造并测量后 sp_replace；公式由已有本地 MathJax 渲染，移动整体而非单字形。'],
  'postcheck': ['查看真正渲染的符号和样式，不能用编译成功代替正确；构造后更新身份和测量，再做布局。', _POSITION_CHECK],
  'fallback': ['不支持的公式命令或字体依赖不可用则记录错误；回滚，不用空对象替代。'],
  'methods': ['sp_replace','measure','tp_transform'],
 },
 'C': {
  'observe': ['比较源和目标、每条线段、折点、角度、曲线形式和缺段；描述路线经过哪两个邻居之间及相对分隔位置。'],
  'counterevidence': ['原图有意留空或弯曲不应强行接框或直线化；单纯箭头头部问题交 D。'],
  'prepare_parameters': ['读取当前路径及端点；按原图语义确定每段路线和邻居约束，准备 d/points 或完整 waypoints。'],
  'execute': ['BP bp_patch 更新路径 d/points；需要重构可 SP arrow 指定 route 与 waypoints。', '补缺段后重新检查全线；不依靠 TP 自动重布复杂折线。'],
  'postcheck': ['核对每段经过区域、转角、与框连接以及是否新增遮挡；随后 D 检查头身。', _POSITION_CHECK],
  'fallback': ['不能可靠判定路线则留未解决；无效路径或连接被破坏时整条修改回滚。'],
  'methods': ['bp_patch','sp_replace'],
 },
 'D': {
  'observe': ['PNG 对 PNG 查箭头缺失、重复和方向，不用 SVG 节点数猜数量。', '依次检查箭身按原图是否露出、接框或留空、同尺度头部形状和像素大小、尖端与线端点。'],
  'counterevidence': ['箭身显露本身不是错误；原图露出则现图也应露出。接框还是留空由原图决定。', '三角形可为等腰或等边，不强制等边；尖点接端点而不是线中点。'],
  'prepare_parameters': ['指定路线、方向、waypoints、head_length/head_width、stroke_width 和颜色；同等显示尺度估计头部大小。', '核对是否 double；缺失时准备新对象身份和插入容器，既有时保留替换身份关系。'],
  'execute': ['SP arrow 构造；箭身在下，头部在上，marker 尖点与路径端点重合。必要 BP 补接线与路线。', '补缺失箭头后仍走完整四项检查。'],
  'postcheck': ['检查箭身显露、接框或留空、头大小与方向、尖端端点，以及重复箭头；关联 E 对称和 C 路由。', _POSITION_CHECK],
  'fallback': ['构造或连接失败回滚；复杂避障需明确重写路线，现有 SP 不自动避障。'],
  'methods': ['sp_replace','bp_add','bp_patch'],
 },
 'E': {
  'observe': ['主动比较整体对整体的中轴线、左右距轴绝对值、上下对应高度、箭身长度、中心、边缘与等距关系。', '整体可包含内外框、文字及多个成员；先识别绑定整体，不能只看单个小对象。'],
  'counterevidence': ['对齐或对称必须有原图依据；原图非对称结构不能强制平均。'],
  'prepare_parameters': ['列出绑定成员、参照整体、对齐轴及需保留的内部相对位置；读取当前整体 TP 与邻居。', '根据原图关系计算当前 SVG 中的平移或成员修正；嵌套对象使用根坐标变换而非误改本地坐标。'],
  'execute': ['BP/TP 对绑定整体微调坐标；tp_align 支持既有模式，复杂镜像关系用明确计算后的 tp_transform。', '不随意改变内容；长度确需修改时结合 C/D 的独立构造步骤。'],
  'postcheck': ['复测整体对齐及成员完整性、箭头连接，确认内外框没有分离。', _POSITION_CHECK],
  'fallback': ['关系不明确标不确定；绑定移动破坏结构时回滚并重新确定绑定集合。'],
  'methods': ['measure','tp_align','tp_transform','bp_patch'],
 },
 'F': {
  'observe': ['检查至少两方的分离、留白和包含关系：文字、公式、几何、图片、框与连接。', '原图留白而现图触边也需检查；正确包含和原图本有的交叠不是错误。'],
  'counterevidence': ['紧贴可见字形的最小外接矩形不是强制正方形；轴对齐 TP 相交仅是候选，稀疏图形可能并未碰撞。'],
  'prepare_parameters': ['语义定位全部参与对象并测量当前紧 TP；定义每对有原图依据的关系。', '回原图判断改文字、上框、底框还是多方；准备平移、缩放或框边坐标，兼顾邻居。'],
  'execute': ['TP 变换/适配或 BP 改底框；在有界回转中重测，直到所声明关系不报警且视觉与原图关系一致。'],
  'postcheck': ['第一遍查原参与对象；第二遍专查邻居、新 TP 报警及邻居关联对象。', '视觉不符仍未通过；连锁问题重新分类，不能仅隐藏警报。'],
  'fallback': ['无进展或达到本地回转上限时停止并记录未解决；错误尝试回滚，不能无限移动挤坏邻居。'],
  'methods': ['measure','check_tp','tp_transform','tp_fit','bp_patch'],
 },
 'S1': {
  'observe': ['PNG 对 PNG 查缺失、主体结构、闭合面、共边、深度、遮挡、纹理、相对尺寸及外来边线。', '先看交叠线索，再估计原图尺寸；交叠不自动证明对象尺寸错，也可能是位置或底框错。'],
  'counterevidence': ['高度相似的内容不因微小像素差报内容错误；区别 A 的知识内容问题。', '构造成功或删除黑色填充不代表几何结构已重建正确。'],
  'prepare_parameters': ['在原图独立语义定位对象与周围参照，只取尺寸和关系；再定位当前 SVG 邻居、容器和锚边来决定放置坐标。', '简单几何准备构造参数、共边向量、面色和组合遮挡顺序；照片准备原图独立 source_crop 与当前 target_tp。'],
  'execute': ['简单规则几何优先 SP geometry 构造再渲染；复杂素材可直接 sp_photo。', '原图裁切必须完整干净、去外来边线；RMBG 后检查主体是否受损，受损可保留干净原裁片。', '精确表达优先 raster；抽象表达可选择 vector。现有 vector 后端不等于已实现专用微粒子贝塞尔算法。', '按现图容器及邻居选对齐边，保比例放入；不要把原图像素坐标当 SVG 坐标。'],
  'postcheck': ['真实查看几何结构或裁片完整性、背景损伤、锚边和尺寸；比较当前容器余量。', _POSITION_CHECK],
  'fallback': ['几何视觉复刻不合格转 sp_photo；机械失败可预声明本地回退，视觉失败需要看到新图后决定。', 'RMBG 损伤主体回原裁片；裁切不准重新独立定位，不借现图 TP 截原图。'],
  'methods': ['sp_replace','sp_photo','measure','tp_fit','tp_transform'],
 },
 'S2': {
  'observe': ['原图与现图比较平面轮廓、方向、边界、开闭和填充区域。'],
  'counterevidence': ['三维面与深度结构错误归 S1，不能只改二维填色掩盖。'],
  'prepare_parameters': ['语义定位当前形状，提取节点属性或顶点；按原图确定新轮廓并保留现图位置关系。'],
  'execute': ['BP 修改 d/points 或对应几何属性；也可 SP 的平面构造器替换。'],
  'postcheck': ['检查轮廓、方向、自交和边缘填充。', _POSITION_CHECK],
  'fallback': ['不能以现有属性表达时构造新对象，隔离执行能力不可用则明确未解决。'],
  'methods': ['bp_patch','sp_replace'],
 },
 'S3': {
  'observe': ['逐对象检查语义对应的面、文字、箭头、背景和描边颜色，区分阴影、抗锯齿与真正色块差异。'],
  'counterevidence': ['两图同一坐标不保证相同内容；不从混合边缘或背景取色替换主体。'],
  'prepare_parameters': ['独立定位原图对应部件的干净 ROI；绑定现图实际生效的 fill/stroke/CSS 或共享引用。'],
  'execute': ['sample_colors 用 OpenCV 返回 ROI 众数颜色；把实际采样结果接入 BP，而不是只取样不修改。', '共享样式或 symbol 会影响其他对象，必须确定范围后修改。'],
  'postcheck': ['渲染核对颜色真正生效、改对部件，且没有改变共享的无关对象。'],
  'fallback': ['渐变、纹理或混合 ROI 无法用众数代表时重新选干净区域或保留不确定；不臆造单色。'],
  'methods': ['sample_colors','bp_patch'],
 },
 'S4': {
  'observe': ['查看成对放大 PNG，数可见语义单元，并考虑遮挡、重复和缺失；不能数 SVG path 代替对象。'],
  'counterevidence': ['一个对象可由多个路径组成；被遮住的成员不等于缺失。'],
  'prepare_parameters': ['列出原图与当前可见单元及差异；绑定重复组合和插入容器，准备增删身份、排列和遮挡顺序。'],
  'execute': ['BP 原子增删或组合，必要时 SP array/cluster 重构；保留单元间实际差异。'],
  'postcheck': ['重新看 PNG 数量与遮挡；新增对象必须真实可见。', _POSITION_CHECK],
  'fallback': ['分辨率不足标不确定；增删不完整或邻居被破坏则回滚整个事务。'],
  'methods': ['bp_add','bp_remove','sp_replace'],
 },
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def build_method_pack(qlist=None, registry=None):
    """Return a detached JSON-compatible versioned method pack.

    Optional arguments verify the caller's taxonomy/registry against this
    versioned implementation; arbitrary caller prose or callables are not read
    into the model context. Sources are readable implementation excerpts, not a
    standalone runtime or a grant to execute code outside an isolated executor.
    """
    if qlist is not None and [q.get('id') for q in qlist] != list(ORDER):
        raise ValueError('Q list must contain the five priority categories')
    if registry is not None and (set(registry) != set(CATALOG) or any(
            registry[name].get('parameters') != CATALOG[name]['parameters'] or
            registry[name].get('callable') is not CATALOG[name]['callable'] for name in CATALOG)):
        raise ValueError('registry must match the actual executable catalog')
    sources = {}
    def source(obj):
        key = obj.__name__ if inspect.ismodule(obj) else obj.__module__ + ':' + obj.__name__
        if key not in sources:
            code = inspect.getsource(obj)
            sources[key] = {'code':code, 'sha256':hashlib.sha256(code.encode()).hexdigest(), 'readonly':True,
                            'scope':'implementation source; imports/dependencies supplied by runtime'}
        return key
    # Shared dependencies are embedded once; no arbitrary path or caller source.
    for module in (geometry, content, arrows, compiler):
        source(module)
    constructors = []
    for name, entry in CATALOG.items():
        card = {k:deepcopy(v) for k,v in entry.items() if k not in {'callable','examples'}}
        fn = entry['callable']
        card.update(callable=fn.__module__+'.'+fn.__name__, signature=str(inspect.signature(fn)),
                    source_ref=source(inspect.getmodule(fn)) if inspect.getmodule(fn) is geometry else source(fn))
        constructors.append(card)
    helpers = {}
    for fn in (tp_v2.selection,tp_v2.transform,tp_v2.align,tp_v2.fit,
               sp_v2.construct,sp_v2.measure_construction_adaptive,sp_v2.replace,
               repair_toolbox._run_operation,repair_toolbox._patch,repair_toolbox._add,
               repair_toolbox._remove,repair_toolbox._photo):
        helpers[fn.__name__] = {'callable':fn.__module__+'.'+fn.__name__,
                                'signature':str(inspect.signature(fn)), 'source_ref':source(fn)}
    from ..single_call.executor import _sample_colors
    helpers['sample_colors'] = {'callable':_sample_colors.__module__+'._sample_colors',
                               'signature':str(inspect.signature(_sample_colors)), 'source_ref':source(_sample_colors)}
    cards=[]
    for base in sorted((q for q in QLIST if q['id'] in ORDER),key=lambda q:ORDER.index(q['id'])):
        card = {k:deepcopy(base[k]) for k in ('id','name','definition')}
        card.update(deepcopy(_DETAILS[base['id']]), semantic_location=_LOCATION, rcd=_RCD)
        if base['id']=='S1':
            card.update(name='明显几何结构与比例错误',definition='原本应成立的几何体或组合在现图中结构不成立、面与边矛盾、组成乱码或比例严重失真；原照片被错画成几何也算，但普通照片纹理、色差和风格不是此类。',
                observe=['先判断原图物件身份：照片、规则几何还是复杂几何。对几何检查面边顶点、体积、组合连接及长宽深比例。'],
                prepare_parameters=['先明确原物件身份和结构错误，绑定现图目标与邻居；几何准备类型、比例与连接，照片准备原图完整裁片。原图尺寸参考与现图放置坐标分开。'],
                counterevidence=['几何成立、比例合理、表达清楚时保留。普通照片细节还原为次要，但原照片被改成虚构几何必须处理。'],
                execute=['原物件是照片却被改成几何：直接原图完整裁切 → SP照片，不再次构造几何。原物件是规则几何：SP重建与组合，失败回退完整原图裁片；复杂几何不能可靠构造也可直接走照片。',
                    '完整裁片先检查所有边和突出部分，去掉不属于物件的框线；RMBG损伤主体则保留干净原裁片。放置按现图容器和邻居选择锚边并保持比例，不能放大残缺裁片冒充全部。',
                    '优先精确裁片。专用微粒子贝塞尔后端未实现，不能把普通矢量化称作该方法。'],
                fallback=['几何失败回退照片；完整裁切无法确认则保留未解决，不嵌入残缺物件。'])
        if base['id']=='A':
            card.update(name='知识、语义符号与关键连接错误',definition='知识内容，以及语义图标身份、箭头方向/重复/缺失/连接关系或结构成员缺失导致表达错误；可用抽象风格和细微纹理不是此类。',
                prepare_parameters=['先判断子类型。文字公式准备旧内容、新内容、依据和样式；图标准备原图身份、完整素材与现图容器；箭头准备起终点、头部、路线、连接框与邻居。',
                    '箭头借上游SAM候选定位后仍在成对PNG确认，不能以节点数或SAM尖角数代替真实数量。绑定所有组成路径、marker与相关框，避免只改一个重复头。',
                    '缺失成员在原图与现图PNG确认后准备完整结构、插入容器与稳定新ID；不要数路径充当语义成员。'],
                execute=['文字：BP改内容，必要时SP公式后进入B。图标：完整原图裁片经SP照片放入或用可靠SP构造，保持身份意义。',
                    '箭头：先BP修完整路线与折点，再SP箭头或BP修头身；检查箭身应否露出、接框或留空、同尺度头部像素大小、尖点对线端点，箭身在下头在上。方向由原图决定。重复头只移除确凿多余成员。',
                    '缺失箭头或成员通过BP增补或SP构造，再完整检查方向、连接、对齐与邻居。共享marker修改须限定实际受影响对象。'],
                postcheck=['按子类型复核知识、图标身份或整条箭头的起终点/头身/数量/连接。文字再查排版，结构和连线再查E/F，不能只检查文字内容。',_POSITION_CHECK],
                fallback=['知识或路线证据不足标不确定；失败回滚该事务，保留明确未解决项。图标裁片不完整则放弃。'])
            card['methods']=['bp_patch','bp_add','bp_remove','sp_replace','sp_photo','measure']
        if base['id']=='E':
            card['observe'].append('先从原图建立对应成员的配对，再逐对核对现图两端的高度、长短和相对轴距；同起点或同底边不代表另一端已对齐。外层整体整齐也不能豁免内部成员。当前线段分组与端点数值仅是候选，必须确认原图确有对应关系。')
        if base['id']=='F':
            card['observe'].append('不要因对象大致处在容器内就判正常：逐边检查可见主体与框线的留白，包含与触边可以同时发生。省略符号、文字末行、几何突出边和连线头身也属于可见主体。')
        if base['id']=='B':
            card['execute'].append('若自行重建XML文字结构，先区分父节点text、子节点text和tail；明确整段替换还是局部替换，不能留下旧字符串再追加新公式。渲染后核对可见文字完整序列，避免重复或丢失。')
        if base['id']=='S1':
            card['observe'].append('逐个辨认几何组合中的单体并追踪共享边和前后遮挡，尤其小物件不能因总体轮廓近似而跳过。检查是否存在不可能的面连接、突出的杂乱楔形或严重长宽深失真；着色和纹理不同但体结构成立应保留。')
        if base['id']=='S1':
            card['observe'].append('每块Crop先辨认其中所有几何主体及各自的参照文字，再逐个核对可见面、共边、遮挡和比例，不能用“小方块均正常”概括。查看current_diagnostics的open_filled_contour：开放描边是否被默认填充连成了多余楔形；这只是候选，须回原图逐个反证，不能统一删fill。')
        card['version_hash'] = _digest(card)
        cards.append(card)
    pack = {
        'format':'review-method-pack-v1', 'inspection_order':list(ORDER),
        'repair_order':{'main':['A','B','S1','E','F'],'dependency_insertions':[]},
        'principles':{'tp_domain':'current_svg_only','diagnostic_crops':'immutable upstream paired inputs; never generated here',
          'inspection':'category-major sequential inspection: each of five types completes full PNG, SVG/TP and both complete upstream crop sweeps before next type; other/missing sweep last',
          'semantic_location':_LOCATION,'tolerance':'原图印刷瑕疵可容忍；高度相似不按像素差报内容错误；不豁免交叠、缺失、反向、结构失真。',
          'ordering':'内容/构造→稳定身份映射→最新测量→布局/连接→本体检查→邻居检查',
          'isolation':'方法来源仅限显式包代码；禁止输入历史答案、圈注或私有验收；新代码只能进入验证过的隔离执行器。'},
        'operation_contract': {
          'envelope':'method, target_ids, args; method is not nested in args',
          'coordinates':'TP/world insertion: current SVG root viewBox; BP scalar attributes: element-local; source_crop and sample ROI: independently located original pixels',
          'measure':{'args':{},'returns':'objects keyed by current IDs with measured tight_bbox/status'},
          'check_tp':{'args':{},'returns':'declared relationship report; not automatic visual judgment'},
          'tp_transform':{'args':{'world_matrix':'six finite invertible affine numbers'},'returns':'selected_ids, before, after, world_matrix'},
          'tp_align':{'args':{'reference_ids':'independent current IDs','mode':'center_x|center_y|left|right|top|bottom'},'returns':'TP transform report'},
          'tp_fit':{'args':{'target_tp':'left,top,right,bottom','mode':'contain|stretch'},'returns':'TP transform report'},
          'sp_replace':{'args':{'kind':'geometry|frame|text|formula|arrow','data':'matching constructor parameters','measurement_viewport':'local construction bounds','target_tp':'current scene bounds','mode':'contain|stretch'},'returns':'replacement_id, constructor_data, construction_measurement and replacement report'},
          'sp_photo':{'args':{'source_crop':'independent original pixel [x,y,width,height]','target_tp':'current scene bounds','representation':'raster|vector','remove_background':'boolean, default true','backend':'vector backend, default vtracer','padding':'nonnegative','mode':'contain|stretch'},'returns':'replacement_id, asset, source_mapping, representation, padded_target_tp'},
          'bp_patch':{'args':{'attributes':'allowed scalar SVG attributes by tag; see constraints','text':'optional replacement for text node, removes existing children'}, 'constraints':{'attributes':sorted(repair_toolbox._PATCH_ATTRS), 'geometry_by_tag':{k:sorted(v) for k,v in repair_toolbox._GEOMETRY_BY_TAG.items()}, 'style':sorted(repair_toolbox._STYLE_ATTRS), 'href':'local use references only, checked for scope and cycles'}, 'returns':'target_ids, applied attributes and text'},
          'bp_add':{'args':{'parent_id':'selected g/svg ID or @parent for common container of targets','svg':'one to five inert fragments; unique IDs on every new element'},'returns':'added_ids, resolved_parent_id, world_to_parent_matrix'},
          'bp_remove':{'args':{},'returns':'removed_ids'},
          'sample_colors':{'args':{'regions':'list of independently located original pixel xywh ROIs'},'returns':'samples with modal_rgb/modal_hex; connect returned value to actual patch'},
          'bp_program':{'args':{'operations':'ordered native TP/SP/BP operations'},'returns':'real operation reports; failing transaction must not partially apply'},
        },
        'cards':cards, 'constructors':constructors, 'helpers':helpers, 'sources':sources,
        'capabilities':{'automatic_visual_acceptance':False,'automatic_original_localization':False,
          'server_side_execution_verified':False,'micro_bezier_specialized_backend':False,
          'geometry':'真实构造器见 constructors；不自动恢复未知透视或纹理。',
          'photos':'sp_photo 按已给原图 ROI 裁切；RMBG/矢量化依赖可用后端，不自动判定主体损伤。',
          'generated_code':'是否可运行由隔离执行器探针决定，本方法包不授予宿主执行权限。'},
        'rcd_contract':_RCD,
    }
    pack['version_hash'] = _digest(pack)
    return pack
