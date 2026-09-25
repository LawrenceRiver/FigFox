# 原生 SVG 的 TP / SP 执行说明

> 下文保留历史接口和多轮工具反馈说明，不代表当前一次调用方案。新的方法规范以 [一次调用 TP/SP 技术路线](single-call/README.md) 为入口；旧 `tool_repair.py` 尚未改造成单次计划执行器，不得把历史“下轮/续跑”当成继续调用 DeepSeek 的授权。

第一步保留 GPT-5.5 原生 SVG。现图 ID 是本次执行的真值，不能凭空编 ID。坐标只可由模型判断或已登记的代码测量产生；人工不提供原图答案。对象名称、图中文字和邻居必须写进问题证据。

## TP：位置与关系

原生 SVG 的 rect.x/y 不给后代建立坐标原点。只有 transform/viewBox 变换坐标系。TP 用浏览器真实排版后的文字/公式/路径边界和 CTM 将所有对象映射到统一 viewBox。旋转图形的外接框是保守证据；marker/clip/filter 会标 bounds_complete=false，不凭外接框自动宣布无碰撞。

一次选择 target_ids 可跨父组；祖先和后代同选只变换最上层，保留 ID 与层级。解散选择无需修改 SVG。
- translate: args={dx,dy}，世界坐标位移。
- align: args={reference_ids:[...],mode:left|right|top|bottom|center_x|center_y,gap?:number}，代码实时测量并算位移，无需猜 dx。
- scale: args={sx,sy,pivot:[world_x,world_y]}，缩放选中整体。
- fit: args={world_box:[x,y,w,h],uniform:true}，把选择的真实边界映射到模型判定的区域。
- constrain: args={movable_ids:[...],relations:[{id,subject_ids,object_ids,predicate,params}]}。predicate支持align_left/right/top/bottom、center_x/y、contain、edge_gap、center_spacing、axis_symmetry、center_symmetry、avoid、legal_overlap。关系名称来自原图，禁止为了把alert清零而创造关系。contain.params={padding}；avoid.params={directions:[left|right|up|down],max_distance,gap}；spacing.params={axis:x|y,padding}。代码最多6遍重新测量、检查所有关系，重复状态即停，返回冲突。非矩形内部不能以AABB认定通过，留视觉复查。可同时调整多组：各关系subject_ids分别指定需要移动的一组。结束后仍逐段核箭头。不会自动假定每条箭头都要贴框。

## SP：组成、反推步骤、可执行构造

SP不是把任意SVG简化成方块。先确定对象属于单体几何、魔方、复合几何照片、普通照片、文字、公式、箭头、框。
- sp: args={kind:geometry|frame|text|formula|arrow,data:{说明书里的完整构造参数}}。用已注册构造器生成局部，替换target_ids里的旧表示，保留第一个目标ID和原transform；多个目标会一起删除，不把新素材叠在旧几何上。data在第一个目标的本地坐标系；不知道时先看SVG transform。
- patch: args={attributes:{SVG原生属性:值或null},text?:string}。只改指定属性，保留其余样式。text仅用于text节点，替换完整文字内容。class中的样式优先级高于presentation attribute，必要时用svg或SP明确设置局部style。
- svg: args={fragment:"局部SVG片段"}。SP没有覆盖的形状可由API写局部矢量，不是执行任意程序。替换旧单元，保留首个目标ID和原transform。片段内部ID必须唯一，禁止外部URL、脚本和事件。不能替换整张图来回避局部检查。
- create: target_ids=[现有父组ID], args={id:新ID,kind,data}，调用SP补缺。不支持的形状可先以group建立身份，再局部svg重建。
- remove: args={}，移除精确目标；使用前说明原图确实没有它，或已在同批用新表示代替。不能随便删连接。

## 原生工具方法（当前入口）

`tool_repair.py` 实际读取的通用方法见 [tool-repair.md](../prompts/tool-repair.md)：发现 → 语义锁定对象/类型/数量 → 选工具及顺序 → 执行与待核验。差异先判断表达必要性；原图视觉取材与现图TP放置分离；三个观察遍次、修改后的目标与邻居两次复查、连锁问题回转均写入方法。当前为提示约束，不是宿主已逐遍强制验收，也不是效果已验证。

新运行不再按图名自动读取旧诊断候选。只有显式续跑入口保留原模型历史；不得作为新盲测。人工逐例答案、评估和已知坐标不进入运行提示。

当前原生 `sp_photo` 可选 raster/vector：复杂几何也可用完整干净的 raster；简单几何SP失败可以转照片，局部矢量化按需要选。下面 legacy `asset`、JSON ops 段描述旧接口，不用于覆盖当前原生工具协议。照片是对象/工具路线，缺陷仍使用 content/geometry 等现有类型。

## 照片分类与局部矢量化

### 原图取材与现图 TP 分离（2026-09-23）

- 原图取材：模型在原图独立找到指定图片的完整主体，按主体边界裁剪；禁止复制现图 TP 或用现图 TP 反推原图框。主体必须完整，不包含外框任何部分、邻近文字、其他对象或多余背景。
- 先查看原图拟裁区域，检查主体完整且取材干净，再矢量化或替换。不能通过切掉主体来躲开外框。
- 矩形不足以分离主体时，应按轮廓抠图；可以使用分割或 RMBG 去掉多余背景并保留透明底，保护主体内部有效颜色，不能仅按颜色误删主体。
- 现图放置：取材合格后，才用现图 `target_tp` 适配位置和尺寸。
- 实现边界：`sp_photo` 默认执行原图crop → 本地RMBG2 → 透明PNG或局部矢量化 → TP放置；保留两份素材和来源。RMBG失败报错，不自动回退矩形贴图；RMBG结果仍需检查主体完整性和邻居污染。remove_background=false用于保留必要照片背景，或看过RMBG结果确认主体被误伤、且原裁片完整干净时；保留两份证据，不得把外框和邻居随原裁片贴回。


asset: args={classification:photo|complex_geometry|abstract,source_crop:[原图x,y,w,h],target_box:[首个旧目标本地x,y,w,h],backend:imagetracerjs|vtracer}。
原始Input/Output照片用photo，保留Raster。多个几何组成的复杂局部或抽象纹理用complex_geometry/abstract，执行彩色曲线描摹生成真实path，不把raster改名为vector。单个几何/魔方优先SP。选择所有应被替换的旧图元作target_ids，代码移除它们再放新局部，避免重复。不可裁整张图、不可把邻近可编辑文字一起当照片。
用户暂称“微粒子贝塞尔碎片”的路线在这里是轻量彩色曲线矢量化候选；不声称确定了GPT-6曾用的工具。输出记录backend、参数、耗时、路径数供看图选择。

2026-09-23：用户确认 Privacy 精细版效果后，`vtracer` 默认采用该版参数：`colormode=color`、`hierarchical=stacked`、`mode=spline`、`filter_speckle=0`、`color_precision=8`、`layer_difference=4`、`corner_threshold=60`、`length_threshold=3.5`、`max_iterations=10`、`splice_threshold=30`、`path_precision=4`。参考结果为 `plus/runs/privacy-bezier-demo-20260923/privacy-fine.svg`。此设置仅作用于选择 `vtracer` 的调用，不改变 raster、pixelruns 或 imagetracerjs 的路线选择；细路径数量和文件体积会增加，仍需看图检查细线与边界。

sample_color: args={source_crop:[x,y,w,h],attribute:fill|stroke}，OpenCV对模型定位的原图ROI取主色并写到target_ids；不要让采样ROI混进邻居/白底。不是图像相似度评分。

## 每个请求的格式

仅JSON：{coverage:[{frame_id:"full或附图底框ID",categories:{14个category:checked|issue|uncertain|not_applicable},evidence:"原现图核对的具体内容"}],issues:[{id,frame_id,category,target_ids,description,original_evidence,current_evidence,op_ids,unresolved_reason?}],ops:[{id,issue_id,action,target_ids,args,depends_on:[]}],relations:[]}。
每个底框及full都检查14类。uncertain不能当pass。category对应typesetting/content/overlap/overflow/alignment/relative_size/planar_shape/arrow_geometry/arrow_route/fill_spill/missing/color/count/geometry。正常归checked；有缺陷归issue并关联问题；不适用和不确定在evidence说明依据。最后全图复查原图内容是否漏在底框外。
每个op绑定issue，所有改动目标必须是该issue的target_ids或其后代，相关箭头也列在问题目标里。每个问题可操作多个相互适配的对象。depends_on只能引用前面的op。每个问题内部原子执行：该问题失败时其操作都未应用；其他独立问题可成功。跨问题不要设depends_on，把必须共同调整的对象合并进同一问题。下轮以feedback.applied_ops和local_failures及实际现图为准。
填写检查表只证明记录完整，不能证明不漏问题，更不能当成最终验收。

为控制长度，coverage每行可用states替代categories，固定以上14类顺序，14个字符，C=checked/I=issue/U=uncertain/N=not_applicable，例如字符串长度必须为14。仍需frame_id和具体evidence，所有I必须有对应issue。

几何问题在issue里必须先声明object_class=single_geometry|rubiks_cube|complex_geometry|abstract。前两类用SP，后两类的重建必须用asset(classification=complex_geometry或abstract)；禁止用cluster/raw svg绕过分类。只有位置问题应归TP类别，不为了重构乱改正确几何。

位置保留：替换use实例时自动保留原SVG的x/y/width/height、symbol.viewBox及transform；新片段采用该实例引用内容的坐标系，不把世界坐标重复写进局部。颜色/纹理不同不足以证明形状错误；形状已正确时保留结构，选择局部样式/取色或纹理修复，不重画普通立方体来替代噪声几何。

### relink — 生成后素材核查
仅在附有原图SAM看板时使用：`action: "relink", target_ids: [现SVG image节点ID], args: {asset_id: "看板ID"}`。模型根据原图、现图和看板识别错配；宿主从本地登记表绑定裁片，仅改图片引用，保留全部位置、尺寸、变换和样式。不得提供路径或base64；不能用此操作重画对象或修改正确素材。

## 原图坐标定位与连锁修复补充（2026-09-23）


原图定位的具体做法：
- 先在原图全图中按对象外观、图中文字、所在区域与邻居关系找到对应主体，确认其完整范围；不要从现图 TP 推出原图位置。
- 根据原图实际宽高，用原图像素坐标给出候选 [x,y,width,height]。如果观察的是缩放预览或局部 crop，要将观察坐标按显示比例、crop 原点换回原图像素坐标，不能把预览坐标直接提交。
- 用 inspect_regions.original_boxes 查看候选区域；逐边检查左、上、右、下是否完整包含主体。切掉主体就扩展，包含外框、标签或邻居就收紧并再次查看，直到完整且干净。记录原图定位依据与最终框；该框是视觉定位结果，不是现图 TP 的实测结果。
- 对普通位置/对齐问题，原图框与周边关系作为布局参照，现图仍用实测 TP 修改。对素材提取，最终框还必须排除外框任何部分与多余背景；矩形做不到时需要轮廓抠图。sp_photo现默认调用本地RMBG2后再嵌入或矢量化；必须检查透明结果是否保留完整主体。

逐问题修复与连锁复查：
- 每个 confirmed 问题都必须确定具体 TP/SP/BP 修复方法、目标与相关邻居、预期结果及复查依据；写入该问题 description 和 operations。不能只识别或只标类型后跳过。受工具能力限制的项明确记录阻碍和下一动作，保留未解决。
- 按依赖关系串联修复：修 A → 看最新图并重测 → 检查 A 和受影响邻居 → 为新增/复发问题选择方法并二次修复 → 再检查。可联合调整一个问题内的相互适配对象；仅独立且不会互相影响的问题可以批量执行。
- 连锁反应也是正式问题：通过 submit_diagnosis 新增观察或修订旧观察，保留其来源与证据；已解决问题若复发必须重新打开，不受“避免重复修改”限制。
- 每轮回到整图检查交叠、出框、对齐，覆盖所有区域、容器边缘及跨区域关系；局部正确不能代替全图检查。原图本身有意的交叠或错落布局应保留，TP 相交只是候选。
- 持续进行“修复—局部与邻居复查—全图检查—二次修复”，直到最新整图没有不符合原图的交叠、出框、对齐基础问题。此条件只是基础问题完成条件，其他已确认问题也须逐项修复和验收。
- finish_review 的 global_review 必须分别说明全图交叠、出框、对齐的检查结果。任何基础问题仍存在或不确定，都不得声称整图修复完成；达到宿主轮次上限或遇到真实能力阻碍时，明确报告未完成和剩余项，不能把停止运行当作验收通过。
