# FigFox 批量运行与费用记录

批量入口保留正式 `chain` 的步骤，逐图运行，各图分别保存来源校验、原始模型记录、费用和 SVG/PNG。不并行扩大模型请求数量，也不自动重试失败请求。

## 文件夹或指定 PNG

从项目根目录运行自己的图片：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-batch.ps1 -InputDir "D:\figures" -Out "D:\results\batch-001"
```

默认扫描第一层 PNG。输出目录必须尚不存在；不指定 `-Out` 时放到 `runs/experiments/<时间>/`。后台执行加 `-Background`。

也可直接指定图片：

```bash
python scripts/batch-experiment.py /path/to/a.png /path/to/b.png --out /path/to/new-batch
```

注册数据集的方式见 [实验工作区](../benchmark/README.md)。仓库不附带本地开发图片、数据集压缩包或实验产物。

## 费用目标与显式硬预算

默认 `--target-usd 1` 只记录和提示，超过目标继续正常生成。每图共用费用记录，推理 token 已包含在输出中，不重复计费；缺失用量报告未确定。

如需自行选择硬限制，用 `--budget-usd <金额>`。它预留整个计划请求的最坏费用；无法承担则拒绝发送，保留已有输出，不缩减模型回复。

GPT 默认输出额度 128,000；它的最坏输出预留可能超过 1 USD，而实际图片费用通常小得多。目标模式不要求这份预留，不把费用目标转换成隐藏输出限制。

## 汇总与恢复

每个 `case-*` 包含来源文件、`case.json`、`console.log`、原始 `run/` 记录、`costs.json`、`summary.json` 及可用最终产物。批量根目录生成总汇、来源清单和价格说明。重新收集已有结果不发起模型请求：

```bash
python scripts/batch-experiment.py --collect-only --out /path/to/existing-batch
```

失败恢复是显式操作，会产生其实际执行步骤对应的模型费用；默认主链不会自动使用这些工具。已有完整首稿可以通过 `scripts/resume-experiment.py` 复用，经来源哈希和记录校验后继续。`scripts/retry-deepseek-step.py`、`scripts/continue-figfox-review.py` 和 `scripts/recover-figfox-batch.py` 的具体范围见各工具 `--help`。

恢复保留原始请求、失败记录与历史费用，不重复计入旧调用。只有当用户明确选择新硬预算时才重新启用硬限制；1 USD 费用目标仍只提示。

状态 `completed_with_issues` 表示已有有效产物但问题尚未全部落实。费用估算及工程回归不代替视觉验收和正式数据集评测。后台进度与通知见 [监控说明](experiment-monitoring.md)。
