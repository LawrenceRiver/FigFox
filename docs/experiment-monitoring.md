# 后台运行、异常通知与状态页

正式 `chain` 命令默认启动独立本地监控。监控不调用模型，不追加付费重试；每图 1 USD 是费用提示目标。

## 启动

在项目根目录启动一张或多张自己的 PNG：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start-experiment.ps1 -Images "D:\figures\复杂图.png" -Out "D:\figures\test-001"
```

返回后台任务编号、状态页和输出目录。生成由后台工作进程执行，监控独立运行。单图和批量入口也支持 `-Background`：

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\run-chain.ps1 -Image "D:\figures\图.png" -Id figure -Out "D:\figures\out" -Background
powershell -ExecutionPolicy Bypass -File .\scripts\run-batch.ps1 -InputDir "D:\figures" -Out "D:\figures\batch-out" -Background
```

输出目录必须尚不存在。保持机器开机；关闭聊天或启动终端后，后台进程继续运行。Windows 通知显示在当前登录桌面会话。

## 有效进展与通知

- 工作进程每 5 秒更新心跳，独立监控每 5 秒读取。生成线程阻塞不阻塞监控。
- 新增推理、正文和工具参数算进展。连接保活、重复元数据、空白不算。
- DeepSeek 5 分钟无进展时提示，20 分钟无进展时中断当前异常读取并保存片段。持续正常输出可以运行更久。
- GPT 首个可见内容之前可能仍在内部推理：15 分钟提示“进度暂不可见”，60 分钟无可见内容保护；开始可见输出后沿用 20 分钟无进展保护。
- 本地修复提交记录也算处理进展。单纯心跳不会掩盖本地停滞。

正常运行保持安静；停滞、心跳异常、超费用目标、恢复输出和流程结束会提示，同一事件去重。一个请求恢复后再次停滞会产生新的告警。监控遇到暂时文件错误会重试本地读取，不重启生成，也不调用模型。

Windows 右下角卡片提供“查看详情”和有产物时的“打开当前结果”，并进入系统通知中心。通知设置关闭或提交失败会记录在状态页。通知回执 `submitted` 表示系统已接收，不表示用户已经看到。

可调节的有限正数环境参数：`FIGFOX_DS_WARN_SECONDS`、`FIGFOX_GPT_WARN_SECONDS`、`FIGFOX_STREAM_IDLE_SECONDS`、`FIGFOX_GPT_HIDDEN_IDLE_SECONDS`。`--no-monitor` 或 `FIGFOX_START_MONITOR=0` 禁止独立监控；`FIGFOX_NOTIFICATIONS=0` 仅关闭系统通知。

## 产物与结束状态

每个有效阶段保留 SVG 和实际可解码的 PNG。后续检查或执行失败、工作进程异常退出时，继续发布已有最后有效检查点。

首稿默认只尝试本地恢复已返回内容；无法恢复时报告失败，不自动新增模型请求。正常上限仍为一次 GPT、最多两次 DeepSeek 发现/修复及原有最多一次条件跟进。

检查覆盖不完整、已确认问题未落实、程序被拒绝或跟进失败时，状态为 `completed_with_issues`，提示“出图完成，仍有待处理问题”。文件可用、流程完成与视觉验收相互独立。

超过费用目标继续生成；进行中请求和缺失用量不计为零。所有价格均是报告用量估算，不是供应商账单。

## 记录位置

后台任务位于 `runs/jobs/<任务编号>/`：`job.json`、`console.log`、`status.html`。每图输出中的 `status.html` 显示进展、逐请求费用、当前图和通知；`runtime-status.json`、`progress.json`、`live-costs.json`、`monitor-events.jsonl` 保留机器记录。

Windows 通知仅注册当前用户的 FigFox 应用标识、开始菜单入口和 `figfox-run-926` 链接协议。一次性非提升权限的交互用户任务提交通知后自行删除。按钮只打开登记的本地状态页或 PNG，不执行模型命令。

历史请求和费用记录不改写。旧实验缺失的服务商用量不能从新监控反向补出。完整能力和故障边界见 [主流程稳定性说明](pipeline-reliability.md)。
