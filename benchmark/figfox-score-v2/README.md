# FigFox 评分标准 v2

本目录可完整交给接入同学。先读 `FigFox_评分标准.pdf`，再按下面命令运行。固定 18 项，不使用整图像素相似度主分；规则、模型建议、人工证据分开。当前未接真实 API，不需要 key、网络或网页登录。D17 可选局部图像测量需 Pillow；D18 显式数据核对仍仅用标准库。

## 快速开始

需要 Python 3.10 或以上。在本目录执行，无需安装任何第三方依赖：

```sh
python3 -m unittest discover -s tests -v
python3 -m figfox_score evaluate examples/input.json --out examples/results/rules.json --csv examples/results/units.csv
python3 -m figfox_score prepare examples/input.json --out examples/results/request.json
python3 -m figfox_score mock examples/input.json --out examples/results/mock-response.json
python3 -m figfox_score import-response examples/input.json --response examples/results/mock-response.json --out examples/results/merged.json
```

全部示例是**合成测试**，不是用户图、真实模型评分或实测一致性。默认示例预计输出 `pending_verification`，因为可见性、公式以外的语义项及软件编辑证据没有验证。mock 只示范协议，永远不能补齐真实覆盖率。

## 文件导航

- `FigFox_评分标准.pdf`：18 项目标、单位、证据、容许差异、边界与职责；统一判定和测量。
- `figfox_score/`：零运行依赖的 Python 包、CLI、规则引擎、适配器接口和权威 `registry.json`。
- `prompts/`：共用系统约束、D01-D18 专用评判提示词、全图逻辑终审。
- `schemas/`：严格输入、模型响应与结果 JSON Schema。
- `docs/对接指引.md`：下一位同学的接入步骤、能力边界、证据与安全约定。
- `docs/局部图像与图表数值接入.md`：D17/D18 可计算部分的字段、公式与复现示例。
- `docs/输入输出契约.md`：每个字段、测量、汇总和错误状态。
- `docs/18项职责注册表.md`：与 PDF 同源的条目明细。
- `examples/`：合成清单、SVG 夹具及离线结果。`request.json` 附件路径在换机器后应重新生成。
- `tests/`：语义清单规则、证据边界及导入校验测试。
- `VALIDATION.md`：本次交付实际检查结果。

## 重要使用约定

规则依据的是**已核实的语义清单和映射**，并不自行从 SVG 或图片识别科学含义。`semantic_evidence` 是接入方对清单、计数、身份、边框与匹配真实性的人工签认；仅模型提取的清单必须保持未验证。该签认不是程序替用户完成了审核。

本包从目录运行。复制整个目录或解压整个 zip 后运行即可；未提供 wheel 发布流程。PDF 构建依赖不属于运行依赖；交付 PDF 已构建。任何真实模型适配、目标软件操作或视觉证据采集，都还需要下一位同学接入。

## 可选局部测量与显式图表数据

D17 默认不启用。要运行 PNG/JPEG 局部测量，在已有 Pillow 的 Python 环境执行下面命令；没有 Pillow 时给出明确 unknown/未计算，不影响其它规则。可选依赖列于 requirements-pillow.txt，离线可使用预装库或本地 wheel。

```sh
python3 -m figfox_score evaluate examples/measurements-input.json --out examples/results/measurements.json
python3 -m figfox_score evaluate examples/measurements-error-input.json --out examples/results/measurements-error.json
```

第一个示例局部 MAE/MSE 为 0，数据核对一致，但 D17/D18 仍待视觉核实。第二个示例局部误差增加，图表数值超出明确容差，D18 失败并触发该合成关键单元的不可用结论。所有局部 PNG/JPEG 和数据均为合成夹具。
