# TP v0.1 可执行关系与局部操作

> 此文为既有 TP 接口资料。当前一次调用方法的定位、坐标隔离和关系原则见 [TP 原则](single-call/tp-principles.md)，完整问题流程见 [逐问题 Mermaid](single-call/problem-routes.md)。本页的旧操作名不能直接当作 native 工具名。

所有坐标默认 SVG 画布单位。对象 matrix 将局部坐标映射至父对象，父链复合才是世界矩阵。执行 translate 的 dx/dy 是世界位移，不要自行重复加 crop 原点。crop_to_canvas 接受原图 crop xywh、显示 crop 尺寸、原图尺寸和画布尺寸。

关系需要 id、subject_ids、object_ids、predicate、params、description、priority。description 必须用图中名称和 ID 表述主宾语。priority=hard 优先；其他为软偏好。未知谓词返回 unresolved；冲突返回 conflict，均不代表视觉验收失败或成功。

| predicate | 语义与 params |
|---|---|
| align_left/right/top/bottom | 一个主体对一个参照；gap 默认0，正值向参照内部偏移 |
| center_x/center_y | 一个主体与参照中心横坐标/纵坐标相同 |
| contain | 一个主体的保守绘制边界放在参照边界内；padding>=0 |
| edge_gap | 多主体按给定顺序在一个容器内等边缘间距；包含两端间距；axis=x/y，padding>=0 |
| center_spacing | 多主体中心位于容器等宽/等高分区中点；axis=x/y，padding>=0；宽度不同则边缘间距不同 |
| center_symmetry | 主体中心与参照中心关于 params.center=[x,y] 对称；仅定位，不反射字形 |
| axis_symmetry | axis=x 指竖线 x=position，axis=y 指横线 y=position；仅中心位置镜像 |
| avoid | 一主体避开一障碍；directions 是 left/right/up/down 列表，max_distance 必填，gap>=0 |

avoid 按位移长度尝试允许的轴向候选，逐个检查已满足硬约束；最多检查四个方向，无可行解则 conflict。保守包围框相交只产生候选，不自动认定错误。inspect_overlaps 将 parent/child 交叠标为 hierarchy_overlap，legal_overlap 声明标为 declared_legal；该声明供检查展示，求解器不把它当主动移动规则。

操作格式：id、action、target_ids、args、可选 depends_on。依赖必须先执行。宿主传入 host_scope，模型不能自行扩大范围。先在副本执行；出错不修改原场景。

- translate：args={dx,dy}。父子同选仅移动最高根；scope 必须覆盖后代和受影响关联箭头。当前仅直箭头能随绑定对象自动重算端点。
- reconstruct：一个目标，args={data:完整新构造参数}。替换 data，保留 ID、matrix、parent_id；默认保留 kind，仅下文明确的无子对象局部素材转换允许指定 args.kind。不能借此跨对象删除。
- reroute：一个箭头，args={route,waypoints,radius?}。waypoints 是箭头局部坐标。保留颜色、头部、绑定等属性。line 两点，cubic 四点；polyline/rounded 至少两点。绑定端点必须与目标锚点吻合，否则拒绝。此操作不自动移动绑定对象。

示例：

```json
{"id":"route-1","action":"reroute","target_ids":["flow_arrow"],"args":{"route":"rounded","radius":8,"waypoints":[[30,40],[30,100],[200,100],[200,40]]}}
```

测量基于浏览器实际文字/公式排版。旋转后的包围框和描边外扩是保守估计，1e-3 SVG 单位是几何数值容差，不是像素质量分数。滤镜、裁剪及未建模 marker 明确不支持。渲染成功、关系 satisfied 或候选减少都不能代替参考图保真检查。

同批非直线联动：translate/reconstruct 影响绑定的非直线箭头时，批内后续必须有该箭头的 reroute。中间状态只在副本内，最终路径须通过绑定端点验证；缺失或失败整批拒绝。建议 reroute.depends_on 引用移动操作。

create：args.object 为完整新对象，target_ids=[新ID]。宿主只为已定位issue的父框下新增对象预留ID；不得覆盖已有对象。repair的crop_requests可供新picture/vector_asset引用，先本地兑现资产再编译。

### 局部素材替换

既有无子对象的geometry/picture/vector_asset可用reconstruct的args.kind切换为picture或vector_asset，并提供完整data={asset_id,x,y,width,height}。保留原ID、parent_id、matrix及引用。新素材须同批crop_requests指定原图绝对source_crop；目标xywh仍为对象局部坐标。普通照片用picture/raster，困难局部可用vector_asset/vector。不能替换有子对象的组或框，不删除邻居。

### 临时组合TP（可执行）

选择多个target_ids即临时组合，不新增group节点、不改变ID或parent_id。成员可以跨父节点，父子同时选只变换最高根一次。联合边界取实际绘制世界边界；辅助轴不画入成图。

- align：args={reference_ids:[参照对象ID...],mode:left|right|top|bottom|center_x|center_y,gap?:0}。目标组作为整体平移，对齐参照组联合边界；参照是只读的。移动组和参照层级不得交叉。若两组均须调整，给各自显式操作及独立参照/世界位移，不让实现猜该挪谁。
- scale：args={sx:正数,sy:正数,pivot:[世界x,世界y]}。围绕明确世界枢轴整体缩放，跨父矩阵正确换算；sx=sy保持字形比例。sx!=sy仅在有原图证据需要改变比例时使用，不拿压扁公式代替布局调整。
- translate/align/scale/reconstruct/reroute之后均记录joint_checks，包含全部声明关系和保守交叠候选。每一批渲染pack再次联合检查。它不是完整自动修复循环，更不能视为视觉通过。
- 直线绑定端点可自动联动，绑定的非直线仍需同批显式reroute。暂不声称能按非矩形真实内部自动求包含，AABB只能作为候选证据。

例：{"id":"align_parts","issue_id":"layout_issue","action":"align","target_ids":["part_a","part_b"],"args":{"reference_ids":["guide_a","guide_b"],"mode":"center_x"},"depends_on":[]}
