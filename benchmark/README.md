# FigFox 实验工作区

使用同一套清单组织自己的输入、方法配置和运行结果。仓库只提供工具、模板与 FigFox 方法登记，不附带数据集图片、模型权重、密钥或实验输出。

```text
benchmark/
  datasets/<数据集编号>/dataset.json
  datasets/<数据集编号>/images/
  methods/figfox/method.json
  runs/<数据集编号>/figfox/<运行编号>/
  reports/
  templates/
```

## 登记自己的数据集

在项目根目录执行，下列操作不调用模型：

```bash
python scripts/benchmark.py add-dataset --id my-figures-v1 --source "My development figures" --input-dir /path/to/images
```

登记保留稳定样本编号、输入来源和 SHA-256。图片复制进本地 `images/`，并由 Git 排除。不要覆盖已经用于实验的数据集；变更输入时新建版本。

## 运行 FigFox

先按 [Windows 说明](../docs/windows.md) 或根目录 README 准备 Python、Node、Chromium、SAM 和模型凭据，然后：

```bash
python scripts/benchmark.py run-figfox --dataset my-figures-v1 --run-id test-001
```

也可选择已有样本编号：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-batch.ps1 -Dataset my-figures-v1 -Samples sample-0001 -RunId test-001 -Background
```

FigFox 当前只接受 PNG。该命令会调用模型；每图默认 1 USD 费用目标只提示，详细规则见 [批量运行说明](../docs/batch-experiments.md)。每次使用新运行编号，原始记录不覆盖。

## 收集与评估

已有运行可以重新汇总，不调用模型：

```bash
python scripts/benchmark.py collect benchmark/runs/my-figures-v1/figfox/test-001
```

原始 case 位于运行目录的 `raw/`，清单记录数据集与方法快照，汇总记录用量、估算费用、最终产物和未完成项。其他方法可用 `templates/method.json` 登记；对应代码、依赖与运行器由使用者另行提供。

固定开发集和未见评估集，在评估前冻结代码与提示词。能出图与视觉验收分别统计，不把开发图或恢复重放当成正式基准成绩。
