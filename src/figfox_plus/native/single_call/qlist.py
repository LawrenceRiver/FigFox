"""User taxonomy: six ordered categories and four on-demand categories."""
QLIST = [
    {'id':'A','name':'内容问题','definition':'知识性文字、拼写、术语或公式内容错误。用上下文及可靠知识确认；不同于照片几何刻画错误。','checks':['区分印刷瑕疵','知识不确定不猜改'],'legacy_types':['content']},
    {'id':'B','name':'字体公式','definition':'符号、字体、字号、根号、上下标、编译渲染与原图参照不符。保留 A 已改正内容；用正确 SP 渲染。','checks':['原图参照','当前 SVG 位置','先构造再测量'],'legacy_types':['typesetting']},
    {'id':'C','name':'线走向','definition':'线经过区域、缺段、走向、折点坐标或角度、曲线形式不符。按邻框之间的语义关系定位，BP 修改。','checks':['源目标','逐段经过区域','缺段','折点和曲线'],'legacy_types':['arrow_route']},
    {'id':'D','name':'箭头','definition':'箭头缺失或头身关系不符。PNG 对 PNG 查缺失，补上后按四项检查。','checks':['PNG 缺失检查','箭身是否露出','接框或留空','同尺度头部像素及方向','尖端必须对线端点'],'legacy_types':['arrow_geometry','missing']},
    {'id':'E','name':'对齐','definition':'绑定整体之间共轴、边缘、中心、等距或左右对称不符；先绑定成员，再按中轴线微调坐标。','checks':['绑定整体及内外框','中轴线与距轴绝对值','连接联动'],'legacy_types':['alignment']},
    {'id':'F','name':'交叠与出框','definition':'两个或以上对象违反分离、留白或包含关系。双方 TP 报警，回原图判断改谁，再检查邻居及邻居关联对象。','checks':['正确包含不误报','贴边留白','双方或多方','原参与关系','邻居新增警报','原图关系软验收'],'legacy_types':['overlap','overflow']},
    {'id':'S1','name':'照片几何相对大小与内容错误','definition':'照片、几何、图案的刻画错误、相对大小、结构、缺失或素材边缘污染。不是 A 知识性内容问题。','checks':['PNG 缺失检查','交叠线索与原图尺寸','现图邻居位置','简单几何 SP','失败回原图 crop','无外来边线','RMBG 主体','精确 crop 或抽象矢量'],'legacy_types':['relative_size','geometry','missing','fill_spill']},
    {'id':'S2','name':'平面图形','definition':'平面形状、方向、轮廓或填色越过应有边界；看原图、语义锁定现图，用 BP 改形状。','checks':['正确轮廓','方向','填色及描边边界'],'legacy_types':['planar_shape','fill_spill']},
    {'id':'S3','name':'颜色','definition':'每个对象都核对颜色；语义定位原图同一内容色块，用 OpenCV 取色并换色，不用相同坐标假定对应。','checks':['干净 ROI','正确部件','fill 或 stroke','CSS 和共享引用'],'legacy_types':['color']},
    {'id':'S4','name':'相似但数量不同','definition':'放大 PNG 对照后的语义单元数量不符；不是 SVG path 数量。BP 补删或组合。','checks':['放大与遮挡','保留单元差异','增删身份','数量后的布局'],'legacy_types':['count']},
]
BY_ID = {q['id']:q for q in QLIST}
MAIN_ORDER = ['A','B','C','D','E','F']
TOLERANCE = {'printing_artifacts_only':True,
             'similar_depiction_not_content_error':True,
             'general_usable_difference_exemption':False}


def markdown():
    lines=['# Q list：6 个顺序主类 + 4 个随时类',
           '历史 14 类仅是本地工具适配标签，模型输出只能使用本表 10 类。缺失、填色污染、几何细项保留为子检查，不丢掉。',
           '容忍只限原图印刷瑕疵；内容非常相似不报视觉内容错误，不泛化为所有差异能用就忽略。','']
    for q in QLIST:
        lines += [f"## {q['id']} {q['name']}", q['definition'], '必须检查：'+'；'.join(q['checks'])+'。','']
    return '\n'.join(lines)
