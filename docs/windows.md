# Windows 运行说明

主入口仍是 `python -m figfox_plus chain`。主流程顺序、SAM 接口、模型和检查次数保留；稳定性规则及提示词补充见 [主流程稳定性说明](pipeline-reliability.md)。Python、Node 和 Chromium 在 Windows 上运行；模型生成的 Python 修复程序通过 WSL + bubblewrap 隔离执行。普通 TP/SP/BP 工具仍在 Windows 本地执行。

## 准备环境

在项目根目录的 PowerShell 中执行。使用 Python 3.12 或更新版本、Node 20 或更新版本；原始依赖中 numpy 2.5.3 要求 Python >= 3.12。

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
npm ci
npx playwright install chromium --only-shell
```

不必激活虚拟环境，下面的启动脚本优先使用 `.venv\Scripts\python.exe`，不存在时使用当前 `python`。

Windows 需有可启动的 WSL Linux 发行版。在 Ubuntu/Debian 中安装动态修复的隔离依赖：

```powershell
wsl --user root --exec apt-get install -y --no-install-recommends python3 bubblewrap libseccomp2
```

默认使用 WSL 默认发行版。需要选择其他发行版时，设置 `$env:FIGFOX_WSL_DISTRO = '你的发行版名称'`。原生 Linux 使用相同组件；macOS 继续使用原来的 sandbox-exec。

密钥放在项目根目录 `.env` 或 `.env.local`。环境变量优先，其次 `.env.local`，再其次 `.env`。不要提交密钥。原来已经存在的 `.env` 可以继续使用。

```text
OPENAI_API_KEY=你的密钥
DEEPSEEK_API_KEY=你的密钥
```

`PLUS_PLAYWRIGHT_MODULE` 和 `PLUS_CHROMIUM` 现在均为可选项；正常安装后不必填写机器专属路径。已有有效的显式配置继续生效。

SAM 服务仍需监听 `http://127.0.0.1:18080`。本机已有的 `local\sam-start.ps1` 可以继续使用；其他机器按 README 的 SAM3 说明配置。SAM 模型权重不属于本次依赖安装。

## 运行前检查

```powershell
. .\scripts\windows-env.ps1
& $FigFoxPython .\scripts\check-runtime.py --credentials --sandbox
```

检查会实际执行 Chromium 渲染、几何测量、公式渲染、中文图片路径读取、vtracer 和隔离 Python，并检查 SAM `/health`。密钥只检查存在性，不调用模型、不打印密钥。不检查 SAM 时可加 `--skip-sam`。

## 一条命令运行

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-chain.ps1 -Image "D:\figures\原图.png" -Id figure1 -Out "D:\figures\result-001"
```

`-Out` 必须尚不存在。脚本会先做运行前检查，再开始正式流程；没有传 `-Authorization` 时自动生成一次性字符串。支持带空格和中文的路径。建议使用这个正式脚本，不再依赖 `local/shims/fcntl.py`。

结果位置沿用上游结构：

- 初始 SVG 与预览：输出目录下 `native-*/stage-0/scene.svg`、`preview.png`。
- 两轮检查后的结果索引：`review/<Id>/result.json` 的 `images` 字段。
- 如果发生追加修复，最新结果索引：`review/<Id>-followup/execution/state.json` 的 `images` 字段；当前流程也会将主 `result.json.images` 和报告同步到已提交的跟进结果。统一导出见输出目录的 `final.svg`、`final.png` 与 `artifacts.json`。

执行成功仍不代表视觉质量已经通过人工确认。

需要后台运行时，在上述脚本后加 `-Background`。独立监控提供状态页、Windows 异常与完成通知、运行中的费用提示。首稿默认仅尝试本地恢复已有回复，失败不会自动追加模型请求，见 [后台实验说明](experiment-monitoring.md)。

官方 DeepSeek 检查入口默认直连，仅作用于当前 HTTP 请求。需要系统代理时，在运行前设置 `$env:FIGFOX_DS_HTTP_ROUTE = 'system'`；恢复直连设为 `'direct'`。路线写入 `http-transport.json`，不自动更换路线重试，也不修改本机代理。显式测试/恢复注入的传输记为 `injected`，具体路线见该任务的恢复记录。

## 离线回归

```powershell
python -m pip install pytest
python -m pytest tests -q
```

集成测试使用真实浏览器和本地修复执行器，SAM 与模型响应使用合成固定数据，不产生模型 API 调用。隔离组件不可用时会明确失败，不会把模型代码降级为无隔离执行。
