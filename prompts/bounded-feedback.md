# 最后一次模型反馈：执行证据优先，最多两次请求

这是同一任务的第二次、最后一次模型请求。现在的 SVG/PNG/TP 已是实际执行后的结果。previous_model_issues 是你前一次的预测，不是真值；compiler_blocked 与 actual_rcd 是程序记录，不是人工验收。不要把旧诊断当答案，不重做已正确的修改，不请求第三次。

先逐项核对原图与现图，给每个旧 issue 一个 prior_issue_results 条目：
{issue_id:旧ID,status:resolved|persists|false_positive|uncertain,evidence:实际可见证据,issue_ids:[本轮对应issue的ID]}。
旧问题一个也不能丢。persists 必须对应本轮 issues 中的条目；resolved 需要实际修后图证据，不能只依据 executed_changed。这里是模型复核，仍不是人工验收。

随后独立检查全部图，不限于旧问题：
1. 整图按 A,B,C,D,E,F,S1,S2,S3,S4 顺序检查。先记录疑点，不能停在容易发现的文字问题。
2. 全部成对 crop 从左上到右下检查；每窗先边界接触与邻居，再几何面/单元结构，再沿线追踪箭身、箭尖、来源和去向，最后看字形与颜色。看不清记 uncertain，不猜。
3. 反向遍历 crop，只查遗漏、重复、错误归因；重新检查声称正常的几何和连接。原图合法叠放不报错，现图是否仍能辨认不是几何正确的证据。
每轮按既定 coverage 提交覆盖表。覆盖表只能证明你提交了记录，不能代替逐处观察；不得自称代码验证了视觉全正确。检查清单与动作列表分离：不会修的真实问题也完整输出并写 unresolved_reason。

最后生成真正符合本地模块的 Ask_data，按 A→F 和对象依赖排序。修复代码必须与现图 ID 对接：
- bp_add.target_ids 是已有的定位锚点；新 ID 只写进 args.svg，创建后的后续动作才用新 ID。parent_id="@parent" 可沿已有锚点找共同父节点。所有嵌套节点（含 tspan）都需要唯一新 ID。
- sp_replace/sp_photo 已经替换 target_ids，不要先删除它。目标必须是 issue.target_ids 中的实际对象或后代；不得把邻居底框当作待替换图标。要改底框尺寸，用 BP/TP 或把底框明确列为该问题的目标并说明原图证据。
- 需要先删再新增的组合放在同一个 bp_program，失败整体回滚。不要把它拆成两步以致后一步失败而原物丢失。
- 公式优先 sp_replace kind="formula"，data 使用实际 SP 卡要求的 tex、font_size 等参数。measurement_viewport 包住 data 本地构造坐标；target_tp 才是现图落点。不要用 target_tp 代替构造的测量窗口。
- 位置或字号不一致时先看原图决定改对象还是改容器；不要仅为让框内检测通过把字号压到明显小于同类文字。实际 CSS 类可能覆盖属性，必要时修改对应对象的局部 style。
- 颜色取样的结果必须用 $result 接到 fill/stroke；写 data 标记并不等于换色。
- 每次修改都要给原对象、容器及受影响邻居定义有原图证据的关系；自己构造失败可预先给 when:failed 的回退程序。真实错误无法可靠解决就保留 unresolved_reason，不伪造成功。

回复完整 single-call-v1 JSON，加 prior_issue_results。不要输出独立的任意 Python/shell，不要反复讨论同一疑点耗尽输出空间。本地执行器会执行允许的模块、保留每步 RCD，再渲染最终图。
