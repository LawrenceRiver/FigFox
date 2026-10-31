# 交付验证记录

日期：2026-10-15（D17/D18 补齐更新）（Asia/Shanghai）。全部评分数据为合成测试；没有真实模型调用、真实用户图评分或实测一致性声明。

## 运行与结果

在交付目录中执行：

```sh
python3 -m unittest discover -s tests -v
```

含 Pillow 12.3.0 的 Python 3.12.14 环境中 71 项测试全部通过，无跳过。系统 Python 3.14.6 无 Pillow 环境运行同一71项测试：67项通过，4项实际图片测试跳过；缺依赖状态另有独立测试验证。覆盖输入类型/未知字段/重复 ID/重复 JSON key/非有限数值/容器环；平移和等比缩放；布局失真；反向箭头与单一根因；少层；额外与平行重复边；容器归属；无公式 NA；证据不足 unknown；整页贴图；缺输出/缺材料/坏文件；文件失败不被评委缺操作材料遮蔽；真实编辑与分类型比例；软件操作链；伪验证和不合规模型响应拒绝；同根因关联与 critical 不被抵消；XML 实体不执行；源图待裁决；18 项顺序与提示词一致；结果 schema；CLI 全链路和拒绝路径。

以下端到端命令均成功退出：

```sh
python3 -m figfox_score evaluate examples/input.json --out examples/results/rules.json --csv examples/results/units.csv
python3 -m figfox_score prepare examples/input.json --out examples/results/request.json
python3 -m figfox_score mock examples/input.json --out examples/results/mock-response.json
python3 -m figfox_score import-response examples/input.json --response examples/results/mock-response.json --out examples/results/merged.json
python3 -m figfox_score evaluate examples/critical-input.json --out examples/results/critical.json
```

普通结果 pending_verification；critical 结果 unusable。mock 未改变普通结果覆盖率与可用结论。rules/merged/critical 均通过 result.schema.json 校验。

## PDF 与内容一致性

PDF 12 页；使用 Poppler 渲染，12 页逐页检查中文、字段、分页、标题和页码；未见重叠、裁切或缺字。条目以两项一页列出，未使用跨页表格。另用文本提取逐项核对注册表的 18 个标题及每项 7 个字段，与 PDF 一致。注册表、18 个专用提示词和结果项目顺序一致。核心规范无其它系统对比或旧条目去向。

## 包与边界

核心运行及测试仅需 Python >=3.10 标准库；D17 可选局部 PNG/JPEG 测量需 Pillow，依赖明确列在 requirements-pillow.txt。PDF 采用工作区构建脚本及 reportlab，预览和构建中间文件留在 work，不进入交付包。压缩包经过 CRC 完整性校验、解压重跑测试和逐文件 SHA256 一致性核对；无缓存、密钥或构建临时文件。

尚待对接：provider 图片/文本附件适配及真实评判器、真实视觉核实、目标软件编辑操作证据采集、任务级容差校准与实际样本评委一致性评估。当前程序不会自动理解图片语义、自动操作软件或自动验证模型建议的真实性。

## D17/D18 补齐验证

新增24项测试：局部同素材平移不变、局部单像素变动、等比缩放、PNG/JPEG支持、非法/越界区域拒绝、非等比变形与未授权平移拒绝、关闭不计算、缺Pillow明确unknown、身份未核实不计算、偷偷搜索字段拒绝；图表数据一致、超过显式容差、容差边界不误罚、轴尺度/单位/系列身份/图例错误、无数据与未核实unknown、不完整点对应unknown、重复映射拒绝、非有限容差拒绝、数据一致不通过图表视觉项、关键数据错误进入不可用结论。

新增 CLI 示例 measurements-input / measurements-error-input 两个场景已端到端运行；一致场景局部MAE/MSE=0、data_status=pass、D17/D18=unknown，图级pending_verification；变动场景MAE约0.0090890523、MSE约0.0062896482、y误差0.1超过容差0.01，D18=fail，图级unusable。数据比较使用输入十进制值避免浮点容差边界误罚。请求准备包含局部原图/候选附件路径及hash，不上传文件。

PDF维持12页和18项顺序；更新第1、3、12页并检查最新渲染，其余页面内容未改变。PDF的18标题和每项7个字段与注册表逐项核对一致。ZIP、SHA256SUMS与解压复测均已更新。
