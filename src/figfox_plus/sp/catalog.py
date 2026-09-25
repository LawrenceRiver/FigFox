"""Executable geometry registry and model-facing instruction cards."""
import json
from .geometry import CONSTRUCTORS

_CARDS={
 'rect':('四条边组成矩形；宽高沿本地横纵轴。',['定位左上角。','指定宽、高和填色；整体由TP定位。'],
         {'x':'number','y':'number','width':'positive','height':'positive','fill':'color'},
         {'shape':'rect','x':0,'y':0,'width':40,'height':20},'width/height > 0'),
 'ellipse':('中心和两条半轴定义椭圆。',['确定中心。','确定横纵半径，不以宽高误填半径。'],
            {'cx':'number','cy':'number','rx':'positive','ry':'positive','fill':'color'},
            {'shape':'ellipse','cx':20,'cy':10,'rx':15,'ry':7},'rx/ry > 0'),
 'polygon':('至少三个按轮廓顺序连接的顶点构成闭合多边形。',['沿边界确定顶点顺序。','传入points，代码闭合轮廓。'],
            {'points':'list of [x,y]','fill':'color'},
            {'shape':'polygon','points':[[0,0],[30,0],[15,20]]},'at least 3 finite points; non-self-intersecting'),
 'cuboid':('主面由origin、u、v确定；depth描述深度方向。两个外侧邻面复用主面角点和深度向量，与主面共边。',
           ['识别主面一角origin及两条边向量u/v。','从参考识别深度方向和长度，使用depth_vector(length,angle)或明确depth。',
            '选择各面颜色；代码按depth方向选两个可见邻面。','整体作为一个几何对象，交由TP定位。'],
           {'origin':'[x,y]','u':'[dx,dy]','v':'[dx,dy]','depth':'[dx,dy] OR omit and supply depth_length/depth_angle',
            'depth_length':'positive; alternative to depth','depth_angle':'degrees; positive toward upper right',
            'colors':'optional front/top/right/bottom/left → color'},
           {'shape':'cuboid','origin':[0,20],'u':[30,0],'v':[0,30],'depth':[10,-10]},
           'non-collinear u/v; depth nonzero and shows two adjacent faces'),
 'cylinder':('圆柱用侧面路径和顶椭圆组成；顶椭圆与侧面同中心、同半径。',
             ['确定顶面中心x/y与radius及ry。','指定height，代码连接侧面和底弧。'],
             {'x':'number','y':'number','radius':'positive','height':'positive','ry':'optional positive'},
             {'shape':'cylinder','x':20,'y':10,'radius':15,'height':40},'radius/height/ry > 0'),
 'array':('同一子对象按两条步进向量组成规则阵列，每个单元保留稳定部件编号。',
          ['选择并描述一个item。','指定rows/cols与step_x/step_y，步进是相邻原点差，不是边缘间距。'],
          {'rows':'int 1..100','cols':'int 1..100','step_x':'[dx,dy]','step_y':'[dx,dy]',
           'item':'rect/ellipse/polygon/cuboid/cylinder spec'},
          {'shape':'array','rows':2,'cols':2,'step_x':[35,0],'step_y':[0,40],
           'item':{'shape':'cuboid','origin':[0,15],'u':[20,0],'v':[0,20],'depth':[7,-7]}},
          'rows*cols <= 400; nested arrays unsupported'),
 'cluster':('多个立方体有各自构造参数；列表顺序就是后方先画、前方后画的遮挡顺序。',
            ['分别识别成员的位置、投影和大小。','按参考遮挡顺序填写items；不靠x+y推断通用遮挡。'],
            {'items':'list of cuboid specs','order':'as_given'},
            {'shape':'cluster','items':[{'shape':'cuboid','origin':[0,15],'u':[20,0],'v':[0,20],'depth':[7,-7]}]},
            '1..400 cuboids; explicit order only'),
 'lattice':('三根基向量定义平行六面体；默认空心网格，可用colors指定可见面的平面填色。',
            ['确定origin/u/v/depth和各方向分格数量divisions。','选择grid=none/faces/volume；通常使用faces。',
             '需要竖向薄切片时给slices中的u方向比例(0,1)；不以实心砖代替空心箱。'],
            {'origin':'[x,y]','u':'[dx,dy]','v':'[dx,dy]','depth':'[dx,dy]',
             'divisions':'[nu,nv,nd]','shell':'optional boolean: boundary edges only, NOT filled faces; default true',
             'grid':'none|faces|volume','slices':'list of fractions in (0,1)',
             'stroke':'optional edge color','stroke_width':'positive finite edge width',
             'colors':'optional per-face front/top/right/bottom/left fills; enables visible-face grid only',
             'fill':'optional uniform face fill; colors overrides per face','dash':'optional SVG dash pattern; empty string for solid',
             'slice_fill':'optional slice fill','slice_opacity':'optional slice opacity'},
            {'shape':'lattice','origin':[0,20],'u':[50,0],'v':[0,60],'depth':[20,-20],
             'divisions':[3,4,3],'grid':'faces','slices':[0.25,0.6]},
            'non-degenerate projection; divisions 1..100; slices along u only; colors/fill provide flat faces with visible-only grid; texture unsupported: use vector_asset for complex texture'),
}

CATALOG={name:{'name':name,'forward_description':card[0],'inverse_steps':card[1],
                'parameters':card[2],'examples':[card[3]],'preconditions':card[4],
                'callable':CONSTRUCTORS[name],'anchors':['left','right','top','bottom','center'],
                'counterexamples':['不要把局部坐标当作整图坐标。','不要把组合部件当成无关联对象。'],
                'limitations':'平行投影构造；不自动恢复透视或未知遮挡。实际可见边界须经渲染测量。'}
         for name,card in _CARDS.items()}


def serializable_catalog():
    return [{k:v for k,v in entry.items() if k!='callable'} for entry in CATALOG.values()]


def manual():
    lines=['# SP 对象说明书','',
           '从可执行注册表生成。坐标为对象本地坐标；对象matrix映射到父坐标。',
           '对象kind仅允许frame/geometry/text/formula/arrow/picture/group/vector_asset。rect/cuboid/array等只能写在geometry或frame的data.shape，绝不能写在kind。',
           '颜色参数来自原图，不受固定色库限制。几何结构正确不等于原图保真通过。','',
           'depth_vector(length, angle_degrees) = (length*cos(angle), -length*sin(angle))。',
           '正角度朝右上。正面正方形是斜投影特例；等轴测可以使用斜向u/v。',
           '选择规则：cuboid只生成三个平面，不会生成网格；网格立方体/魔方必须用lattice并明确divisions、面填色和grid。噪声纹理不是网格，复杂多物体或纹理走分类asset。未知参数会被拒绝，不会替你猜构造。','']
    for name,e in CATALOG.items():
        example=e['examples'][0]
        if name in CONSTRUCTORS:
            example={'id':'example','name':'示例几何','kind':'geometry','data':example}
        lines.extend([f'## {name}',f'正向组成：{e["forward_description"]}','反向构造：'])
        lines.extend(f'{i}. {x}' for i,x in enumerate(e['inverse_steps'],1))
        lines.extend(['参数：'+json.dumps(e['parameters'],ensure_ascii=False),
                      '前提：'+e['preconditions'], '示例：', '```json',
                      json.dumps(example,ensure_ascii=False,indent=2),'```',
                      '限制：'+e['limitations'],'反例：'+'；'.join(e['counterexamples']),''])
    return '\n'.join(lines)


def _compile_example(obj):
    from .compiler import compile_scene
    return compile_scene({'version':'plus-0.1','canvas':{'width':320,'height':200},
                          'objects':[obj],'relations':[],'assets':[]})


_CONTENT_CARDS={
 'text':('文字保持为一个 text 对象，字号及基线位置定义排版，matrix 控制整体方向。',
         ['识别原文字、字号与字体。','用 x/y 指定首行基线，anchor 选择 start/middle/end；旋转写在对象 matrix。'],
         {'text':'string','x':'baseline x','y':'baseline y','font_size':'positive','font_family':'font stack','anchor':'start|middle|end','fill':'color','style':'font-weight/font-style/fill/letter-spacing/text-decoration'},
         {'text':'Face','x':20,'y':40,'font_size':24},
         '单行；字体须本地可用，不使用 textLength 压字。'),
 'formula':('TeX 在本地生成同一对象内的路径，根号、上下标和分数随对象整体移动。',
            ['从原图读出 TeX 结构。','指定 x/y 为公式视口左上角及 font_size；移动整体 matrix，不移动单个字形。'],
            {'tex':'TeX string','x':'viewport left','y':'viewport top','font_size':'positive'},
            {'tex':r'\sqrt{x^2+y_1}','x':20,'y':20,'font_size':28},
            '支持本地 MathJax base/ams/newcommand；不支持的命令报错，不能生成空对象替代。'),
 'arrow':('身体路径连接两端尖点；marker 三角形尖端与路径端点重合，头部底边在尖点后方。',
          ['从参考辨别 line/polyline/rounded/cubic，不把所有拐点圆角化。','依次填写 waypoints，选择 head_length/head_width 与 double。','圆角用 radius 裁到相邻段一半；Q 控制点是原拐点。连接对象重算由 TP 处理。'],
          {'waypoints':'ordered [x,y] points; cubic exactly four','route':'line|polyline|rounded|cubic','radius':'nonnegative','head_length':'positive','head_width':'positive','double':'boolean','stroke_width':'positive','stroke':'color','start':'optional {object_id,anchor}','end':'optional {object_id,anchor}'},
          {'waypoints':[[20,30],[100,30],[100,90]],'route':'rounded','radius':8,'head_length':10,'head_width':8},
          '拒绝零长线段；cubic 使用首末控制点确定端部切线。当前不自动避障；TP 联动仅支持 line，其他路线需显式重新布线。索引提供 tip/base_center/shaft_endpoint，身体终点与尖点重合并由头部覆盖。'),
 'frame':('底框是独立有 ID 的几何对象，内容通过 parent_id 引用它，不能把内容 ID 当底框 ID。',
          ['先确定底框范围与独立 ID。','选择已有 shape 构造；补框同样注册独立 ID，子对象在框本身之后绘制。'],
          {'shape':'registered geometry shape','other':'see matching geometry card'},
          {'shape':'rect','x':10,'y':10,'width':180,'height':100,'fill':'none'},
          '目前采用已有几何构造，不接受任意原生 path 字符串。'),
 'group':('组只提供共同坐标系与身份，子对象通过 parent_id 归属，不额外绘制占位框。',
          ['创建具有独立 ID 的 group，data 为空。','将成员 parent_id 指向该 ID；共同变换写在 group matrix。'],
          {},{},'空组无可见面积；不能把它当已完成的几何。')}
for _kind,_card in _CONTENT_CARDS.items():
    CATALOG[_kind]={'name':_kind,'forward_description':_card[0],'inverse_steps':_card[1],
      'parameters':_card[2],'examples':[{'id':'example','name':'示例','kind':_kind,'data':_card[3]}],
      'callable':_compile_example,'preconditions':'合法对象 ID；有限坐标；引用已有父对象。',
      'anchors':['left','right','top','bottom','center'],
      'counterexamples':['不把文字基线当公式左上角。','不以渲染成功声称原图保真。'],
      'limitations':_card[4]}
