# FigFox

Windows / PowerShell 使用 [Windows 运行说明](docs/windows.md)。

复杂图片输入容量、SVG 容错、异常停滞保护与失败产物保留见 [主流程稳定性说明](docs/pipeline-reliability.md)。后台运行、状态页与通知见 [监控说明](docs/experiment-monitoring.md)。

批量运行可使用 [benchmark/ 实验工作区](benchmark/README.md) 登记自己的数据集，或直接使用 [文件夹批量入口](docs/batch-experiments.md)。仓库不附带实验图片。

把论文插图从原图做成可编辑 SVG，再按原图检查并改回来。一条命令走完构图、裁切和修复。

Turn a paper figure into an editable SVG, then check it against the original and repair it. One command runs composition, crops, and repair.

仓库保存流程代码、提示词和实验清单。密钥、模型权重、运行结果及数据集图片不提交 Git。

The repository tracks pipeline code, prompts and experiment manifests. API keys, model weights, run outputs and dataset images are excluded from Git.

包名是 `figfox_plus`。仓库用短名 `figfox`。The package name is `figfox_plus`. The repository name is `figfox`.

## 流程

下面四步都在「运行」那一条 `chain` 命令里，按这个顺序做完。

1. **第一次构图。** 原图先交给本地 SAM 服务切出图块、图标和箭头，再由 GPT-5.5 写成 SVG。提示词在 `prompts/first_native.md`。
2. **1/2 Crop。** 每个底框向左右上下各扩出自身宽、高的一半，裁在画布里面。同一块区域的原图和当前渲染并排放在一起。实现是 `src/figfox_plus/pack.py` 里的 `half_crop`，由 `src/figfox_plus/native/pack.py` 写成成对图片。检查阶段不会重新裁这些图。
3. **最多两次请求检查并修复。** 第一次只列问题；检查记录完整且没有确认或待确认问题时停止，否则第二次为已经列出的问题写修复程序。类别是交叠、对齐、字体公式、规则立方体、箭头，以及和原图完全不符的小贴块。代码在 `src/figfox_plus/native/review_problem_first_v13/`。
4. **回执之后最多再请求一次。** 交叠、对齐、几何，或者已经检出但没落地的照片，才会打开这一次。已经落地的不再请求。这一次可以查看事先备好的全部 1/2 Crop，每一对第一张是原图、第二张是当前渲染，每条问题选定包含它的那一对再写程序。写完执行一次就停。

像素被改过，只说明程序执行了。这不等于图已经看过、可以接受。

```mermaid
flowchart TD
  svg[5.5 生成 SVG]
  look[整页看一次：原图对当前渲染]
  rerun[再跑一次 5.5]
  crop[1/2 Crop]
  find[第一次请求：只列问题]
  fix[第二次请求：写程序并执行]
  receipt[回执]
  extra[再开一次：只处理回执里没收口的必须项]
  stop[停止]
  svg --> look
  look -->|一整块物件一起漂了| rerun --> crop
  look -->|没有这种大错| crop
  crop --> find
  find -->|记录完整且无待处理问题| stop
  find -->|有问题或检查记录不完整| fix --> receipt
  receipt -->|交叠、对齐、几何或已检出的照片没收口| extra --> stop
  receipt -->|这些都已落地| stop
```

![流程](flow.svg)

图里「整页漂移就再跑一次 5.5」那一支还没有接进代码。回执这一支已经接上，实现在 `src/figfox_plus/native/review_problem_first_v13/followup.py`。

## 准备

需要 Python 3.12 或更新版本、Node 20 或更新版本，以及 Playwright 能启动的 Chromium。

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
npm ci
npx playwright install chromium --only-shell
```

密钥放在环境变量里，不要写进仓库：

- `OPENAI_API_KEY`：第一次构图
- `DEEPSEEK_API_KEY`：两次检查
- `PLUS_PLAYWRIGHT_MODULE`：可选，覆盖项目内 Playwright 模块
- `PLUS_CHROMIUM`：可选，覆盖 Playwright 自动定位的 Chromium 可执行文件

## SAM3

`chain` 会请求本机 `http://127.0.0.1:18080` 的 `POST /v1/segment/proposals`。权重不在这个仓库里，所以要先在外面把服务听起来。根路径返回 404 只说明端口有进程，不能代替 `/health`。

这条链路只发三类提示词：`picture`、`icon`、`arrow`。`adapters/raw_evidence.py` 里还有框、立方体等类别，`src/figfox_plus/sam.py` 不会把它们发给 SAM。

权重和 [DrawAI](https://github.com/Renaissance-Mind/DrawAI-dev) 用的是同一套 Meta SAM3：

- 检查点：ModelScope 或 Hugging Face 上 `facebook/sam3` 的 `sam3.pt`
- 词表：`bpe_simple_vocab_16e6.txt.gz`，来自 [facebookresearch/sam3](https://github.com/facebookresearch/sam3)

用 DrawAI 下载，并只启动 SAM3：

```bash
git clone https://github.com/Renaissance-Mind/DrawAI-dev
cd DrawAI-dev
uv run drawai setup local
uv run drawai server model sam3 --host 127.0.0.1
```

`setup local` 默认从 ModelScope 拉 `facebook/sam3`。走 Hugging Face 时要接受上游许可：

```bash
export HF_TOKEN=hf_...
uv run drawai setup local --source huggingface --accept-sam3-license
```

本机已经有权重时，指向那三个文件，不再下载：

```bash
uv run drawai setup local \
  --sam3-checkpoint /path/to/sam3.pt \
  --sam3-bpe /path/to/bpe_simple_vocab_16e6.txt.gz \
  --sam3-source /path/to/facebookresearch-sam3
```

听好之后：

```bash
curl http://127.0.0.1:18080/health
```

没有本地权重、改走 fal.ai 时，另设 `FAL_KEY`，再用本仓库的云适配器。它的默认端口是 8765，要改到 18080：

```bash
PORT=18080 python scripts/fal_sam3_adapter.py
```

这条还需要 `flask`、`fal-client`、`httpx`。

去背景用的 RMBG2 权重不在本文件夹里，`chain` 不依赖它。相关代码在 `runtime/rmbg_runner.py`。

## 运行

在本目录执行这一条。它按上面的顺序走完：GPT-5.5 写 SVG，生成 1/2 Crop，DeepSeek 第一次只列问题，必要时第二次写程序并在本机执行。交叠、对齐、几何，或已经检出但没落地的照片，才会再请求一次。

```bash
PYTHONPATH=src python -m figfox_plus chain \
  --image /path/to/figure.png \
  --id unet \
  --out /path/to/new-run \
  --rerun-authorization your-one-time-string
```

跑之前先满足这些条件：

- 上一节的 Python、Node、Playwright 和密钥已经就绪。SAM 服务在 `http://127.0.0.1:18080` 听着。
- `--image` 是原图 PNG，文件必须存在。
- `--id` 是短名字，只用字母、数字、`-` 和 `_`，例如 `unet`。
- `--out` 必须是一个还不存在的目录。结果写在这个目录里，不写回本文件夹。
- `--rerun-authorization` 是一次性字符串。同一张原图再次交给 GPT-5.5 时，换一个新的。

命令正常结束时，终端打印 `--out` 的路径，同目录有 `chain-timing.jsonl`。这表示这条链路跑完了。像素被改过，只说明程序执行了，不等于图已经看过、可以接受。

首轮成功渲染后，同目录即可找到 `final.svg`、`final.png` 和 `artifacts.json`。后续失败时保留最近的有效产物，是否仅有首轮结果及检查是否完成以状态记录为准。

`chain` 是这条已经接上的整链。`python -m figfox_plus run` 仍是旧入口，默认还会走另一套单次修复，不要拿它代替上面这条命令。

图里「整页漂移就再跑一次 5.5」那一支还没有接进这条命令。命令开头会调用一次 GPT-5.5，不会因为整页漂移再调用第二次。
