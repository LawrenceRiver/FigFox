"""Independent local monitor: no models, no paid retries, no monetary kill switch."""
import argparse
import html
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time

from .state import PLUS_ROOT, write_json, replace_file
from .usage_cost import cost_snapshot, read_record


def process_alive(pid):
    if not isinstance(pid, int) or pid <= 0:
        return False
    if os.name == 'nt':
        import ctypes
        from ctypes import wintypes
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.OpenProcess.restype = wintypes.HANDLE
        handle = kernel.OpenProcess(0x1000, False, pid)
        if not handle:
            return ctypes.get_last_error() == 5  # access denied is not evidence of death
        try:
            code = wintypes.DWORD()
            if not kernel.GetExitCodeProcess(wintypes.HANDLE(handle), ctypes.byref(code)):
                return True
            return code.value == 259
        finally:
            kernel.CloseHandle(wintypes.HANDLE(handle))
    try:
        os.kill(pid, 0)
        return True
    except PermissionError:
        return True
    except ProcessLookupError:
        return False


def detached_options(*, breakaway=False):
    # Only the launcher's controller leaves its caller's job. Its own workers
    # do not request a second breakaway, which Windows can refuse with error 5.
    return {'creationflags': subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP |
            (subprocess.CREATE_BREAKAWAY_FROM_JOB if breakaway else 0)} if os.name == 'nt' else {'start_new_session': True}


def start_monitor(root, *, mode='chain'):
    root = Path(root).resolve()
    try:
        previous = read_record(root/'monitor-launch.json', {}) or {}
        if previous.get('pid') and process_alive(previous['pid']):
            return previous
        environment = os.environ.copy()
        environment.update(PYTHONPATH=str(PLUS_ROOT/'src'), PYTHONUTF8='1', PYTHONIOENCODING='utf-8')
        with (root/'monitor-console.log').open('ab') as log:
            child = subprocess.Popen([sys.executable, '-u', '-m', 'figfox_plus.monitor', '--root', str(root), '--mode', mode],
                cwd=PLUS_ROOT, env=environment, stdout=log, stderr=subprocess.STDOUT,
                stdin=subprocess.DEVNULL, **detached_options())
        result = {'pid': child.pid, 'started_at': time.time(), 'mode': mode, 'status': 'started'}
    except (OSError, ValueError) as exc:
        result = {'status': 'unavailable', 'error': str(exc), 'started_at': time.time()}
    write_json(root/'monitor-launch.json', result)
    return result


def atomic_text(path, value):
    path = Path(path)
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix='.' + path.name)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(value)
        replace_file(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


STAGES = {'preparing': '准备输入', 'gpt55_start': '首稿生成与渲染', 'gpt55_reused': '恢复已保存首稿',
          'first_recovery_start': '恢复首稿结构', 'first_recovery_done': '首稿恢复完成',
          'gpt55_done': '首稿已出图', 'review_start': '检查与修复', 'review_done': '修复完成',
          'chain_failed': '流程发生异常', 'artifacts_checked': '结果已保存'}
TERMINAL_STATUSES = ('completed', 'completed_with_issues', 'failed')
STATUS_LABELS = {'running': '正在运行', 'completed': '流程完成',
                 'completed_with_issues': '已出图，仍有待处理问题', 'failed': '需要查看异常'}


class Monitor:
    def __init__(self, root, *, notify=None, alive=process_alive):
        self.root = Path(root).resolve()
        self.alive = alive
        if notify is None:
            from .notifications import notify_windows
            notify = notify_windows
        self.notify = notify
        self.record = read_record(self.root/'monitor-state.json', {}) or {}
        self.record.setdefault('seen', [])
        self.record.setdefault('alerts', [])
        self.record.setdefault('stall_episodes', {})
        self.cost_cache = {}
        self.stale_requests = set(self.record.get('stale_requests', []))
        if not (self.root/'status.html').exists():
            atomic_text(self.root/'status.html','<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="3"><title>FigFox</title><h1>FigFox</h1><p>正在读取运行状态。</p>')

    def alert(self, key, title, message, *, result=None):
        if key in self.record['seen']:
            return
        event = {'key': key, 'at': time.time(), 'title': title, 'message': message,
                 'automatic_retry': False, 'generation_stopped_by_target': False}
        self.record['seen'].append(key)
        self.record['alerts'].append(event)
        # Save deduplication before invoking the OS; crashes cannot flood notifications.
        write_json(self.root/'monitor-state.json', self.record)
        try:
            with (self.root/'monitor-events.jsonl').open('a', encoding='utf-8') as handle:
                handle.write(json.dumps(event, ensure_ascii=False)+'\n')
        except OSError as exc:
            event['event_log_error'] = str(exc)
        try:
            event['notification'] = self.notify(title, message, self.root/'status.html', result=result)
        except Exception as exc:
            event['notification'] = {'status': 'failed', 'error': type(exc).__name__}
        write_json(self.root/'monitor-state.json', self.record)

    def poll(self, *, now=None):
        now = time.time() if now is None else now
        runtime = read_record(self.root/'runtime-status.json', {}) or {}
        if not runtime:
            return False
        status = runtime.get('status', 'running')
        original_name = Path(runtime.get('image', '')).name
        # A batch copies inputs to original.png; show the source filename in alerts.
        case = read_record(self.root.parent/'case.json', {}) or {}
        name = Path(case.get('original', original_name)).name
        artifacts = read_record(self.root/'artifacts.json', {}) or {}
        # Older runs ended with "completed" even when the review was unresolved.
        # Interpret their committed artifact record without rewriting experiment history.
        review_status = runtime.get('review_status', artifacts.get('review_status'))
        if status == 'completed' and (review_status not in (None, 'visual_review_pending') or runtime.get('followup_status') == 'failed'):
            status = 'completed_with_issues'
        if status == 'running' and not self.alive(runtime.get('worker_pid')):
            from .native.artifacts import publish_latest
            artifacts = publish_latest(self.root, runtime['image_id'], error={'type': 'WorkerStopped', 'message': 'worker exited without terminal status'})
            status = 'failed'
            self.alert('worker_stopped', name+' · 生成进程已退出',
                       '已检查并保留最后可用的 SVG / PNG。没有自动重复付费。',
                       result=self.root/'final.png' if artifacts.get('artifact_status')=='available' else None)
        cost = cost_snapshot(self.root, cache=self.cost_cache, worker_running=status=='running')
        target = runtime.get('cost_target_usd', 1)
        cost_text = f"已知费用 ${cost['estimated_usd']:.4f}"
        if cost['active_requests']:
            cost_text += f"；{cost['active_requests']} 个请求进行中，费用待结算"
        if cost['unknown_cost_requests']:
            cost_text += f"；{cost['unknown_cost_requests']} 次请求用量缺失，总费用未确定"
        result = self.root/'final.png' if artifacts.get('artifact_status')=='available' else None
        if cost['estimated_usd'] > target:
            self.alert('cost_target', name+' · 超过费用提示目标', cost_text+f'。目标 ${target:g}；正常生成继续。', result=result)
        request = None
        request_path = runtime.get('current_request')
        if request_path and Path(request_path).resolve().is_relative_to(self.root):
            request = read_record(Path(request_path)/'progress.json')
        if status == 'running':
            if now-runtime.get('heartbeat_at', now) > 30:
                self.alert('heartbeat_missing', name+' · 运行心跳异常', '生成进程仍存在，但运行状态长时间未更新。请查看详情；未自动追加请求。', result=result)
            if request and request.get('status') in ('sending','receiving','interrupting'):
                age = now-(request.get('last_meaningful_at') or request['started_at'])
                key = str(request_path)
                if age >= request.get('warning_seconds', 300):
                    if key not in self.stale_requests:
                        previous = max(self.record['stall_episodes'].get(key, 0), int(key+':resumed' in self.record['seen']))
                        self.record['stall_episodes'][key] = previous+1
                        self.stale_requests.add(key)
                    episode = self.record['stall_episodes'][key]
                    suffix = '' if episode == 1 else f':{episode}'
                    self.record['stale_requests'] = sorted(self.stale_requests)
                    hidden = request.get('progress_visibility')=='hidden_reasoning_possible'
                    title = 'GPT 进度暂不可见' if hidden else '模型输出疑似停滞'
                    message = ('尚未收到可见内容，可能仍在内部推理。' if hidden else '长时间没有收到新增推理、正文或工具参数。')
                    self.alert(key+':stale'+suffix, name+' · '+title,
                        message+cost_text+'。已有输出已保留；不会因费用目标停止或自动重复请求。', result=result)
                elif key in self.stale_requests:
                    episode = self.record['stall_episodes'].get(key, 1)
                    suffix = '' if episode == 1 else f':{episode}'
                    self.stale_requests.remove(key)
                    self.record['stale_requests'] = sorted(self.stale_requests)
                    self.alert(key+':resumed'+suffix, name+' · 输出已恢复', '已重新收到新增内容，继续当前请求。', result=result)
            else:
                anchor = max(runtime.get('stage_at', now), (request or {}).get('finished_at', 0))
                image_id = runtime.get('image_id')
                if isinstance(image_id, str) and image_id:
                    for relative in (f'review/{image_id}/phase-2/execution/state.json',
                                     f'review/{image_id}-followup/execution/state.json'):
                        path = self.root/relative
                        if path.resolve().is_relative_to(self.root):
                            try:
                                anchor = max(anchor, path.stat().st_mtime)
                            except OSError:
                                pass  # A missing optional checkpoint is not evidence of progress.
                if now-anchor > 300:
                    self.alert('local:'+runtime.get('stage',''), name+' · 本地处理耗时较长',
                        '当前阶段长时间没有完成。监控仍在运行，请查看详情。没有自动追加模型请求。', result=result)
        elif status in TERMINAL_STATUSES:
            title = ('出图完成，仍有待处理问题' if status=='completed_with_issues' and result else
                     '流程完成' if status=='completed' and result else
                     '流程未完成，已保留可用图' if result else '流程未完成，暂无可用图')
            self.alert('terminal', name+' · '+title, cost_text+'。'+
                ('SVG / PNG 已保存，视觉效果仍需验收。' if result else '原始回复与错误记录已保存，没有自动重复付费。'), result=result)
        self.record.update(monitor_pid=os.getpid(), heartbeat_at=now, status=status,
                           runtime=runtime, request=request, costs=cost, artifacts=artifacts)
        write_json(self.root/'live-costs.json', cost)
        write_json(self.root/'monitor-state.json', self.record)
        self.render(name, status, runtime, request, cost_text, result)
        return status in TERMINAL_STATUSES

    def render(self, name, status, runtime, request, cost_text, result):
        esc = html.escape
        def link(path, text):
            return '<a href="'+esc(Path(path).resolve().as_uri(), quote=True)+'">'+esc(text)+'</a>'
        elapsed = max(0, time.time()-runtime.get('started_at', time.time()))
        phase = STAGES.get(runtime.get('stage'), runtime.get('stage',''))
        progress = ''
        if request:
            last = request.get('last_meaningful_at')
            note = f"距新增内容 {max(0,time.time()-last):.0f} 秒" if last else '尚无可见内容；GPT 可能在内部推理'
            model = 'GPT' if request['model'].startswith('gpt') else 'DeepSeek'
            request_status = {'sending':'正在发送','receiving':'正在接收','interrupting':'正在结束异常读取','completed':'已返回','failed':'请求中断'}.get(request['status'],request['status'])
            progress = '<p>'+esc(f"{model} · {request_status} · {note}")+'</p><p>'+esc(
                f"推理 {request.get('reasoning_characters',0):,} 字符 · 正文 {request.get('content_characters',0):,} 字符 · 工具参数 {request.get('tool_argument_characters',0):,} 字符")+'</p>'
        alerts = ''.join('<li><strong>'+esc(a['title'])+'</strong><p>'+esc(a['message'])+'</p></li>' for a in reversed(self.record['alerts'][-12:]))
        output = (link(self.root/'final.svg','打开 SVG')+' '+link(result,'打开 PNG')+
                  '<p><img src="'+esc(result.resolve().as_uri(),quote=True)+'"></p>') if result else '<p>尚无已验证的 SVG / PNG。</p>'
        rows=[]
        for call in self.record.get('costs',{}).get('calls',[]):
            model='GPT' if call.get('model','').startswith('gpt') else 'DeepSeek'
            phase='首稿生成' if model=='GPT' else '首稿恢复' if 'first-recovery' in call.get('request','') else '检查与修复'
            price=(call.get('cost') or {}).get('estimated_usd')
            text=f'${price:.4f}' if price is not None else '待结算' if call.get('active') else '未确定'
            state='进行中' if call.get('active') else '用量已报告' if call.get('usage') and price is not None else '用量缺失' if price is None else '发送前拒绝'
            rows.append('<tr><td>'+esc(phase)+'</td><td>'+model+'</td><td>'+text+'</td><td>'+esc(state)+'</td></tr>')
        notifications = ''
        receipts = [(a.get('notification') or {}).get('status') for a in self.record['alerts']]
        if receipts and receipts[-1] in ('failed','disabled_by_windows','disabled_by_configuration'):
            notifications='<p>系统通知未送出或已关闭；本页仍保存全部异常与完成记录。</p>'
        body = '<!doctype html><html lang="zh-CN"><meta charset="utf-8">'+(
            '<meta http-equiv="refresh" content="5">' if status=='running' else '')+'<title>FigFox · '+esc(name)+'</title>'+(
            '<style>body{font:16px system-ui;color:#20312d;background:#f5f7f6;max-width:1040px;margin:36px auto;padding:0 24px}section{background:white;border:1px solid #d9e2dd;border-radius:12px;padding:22px;margin:20px 0}h1{font-size:28px}h2{font-size:20px}p{line-height:1.7}a{display:inline-block;color:#196746;margin-right:16px}img{max-width:100%;height:auto}li{margin:20px 0}small{color:#50685d}table{width:100%;border-collapse:collapse}td,th{text-align:left;padding:12px;border-bottom:1px solid #d9e2dd}</style>')+(
            '<h1>FigFox · '+esc(name)+'</h1><section><h2>'+esc(STATUS_LABELS.get(status,status))+'</h2><p>'+esc(phase+f' · 已运行 {elapsed/60:.1f} 分钟')+'</p>'+progress+'<p>'+esc(cost_text)+'</p><small>'+esc(
            f"每图费用提示目标 ${runtime.get('cost_target_usd',1):g}，超出目标继续正常生成。运行心跳与内容进展分别监控。")+'</small></section><section><h2>当前结果</h2>'+output+
            '<p>出图表示文件可解析且已渲染，视觉效果仍需验收。</p></section><section><h2>请求费用</h2><table><tr><th>阶段</th><th>模型</th><th>已知费用</th><th>状态</th></tr>'+''.join(rows)+
            '</table><p>费用按服务商报告的用量估算；进行中的请求和缺失用量不计为零。</p></section><section><h2>通知与运行记录</h2>'+notifications+link(self.root/'monitor-events.jsonl','查看通知记录')+link(self.root/'live-costs.json','导出费用明细')+
            '<ul>'+alerts+'</ul></section></html>')
        atomic_text(self.root/'status.html', body)


def monitor_job(root):
    config = read_record(root/'job.json')
    children = {}
    parent = Monitor(root)
    while True:
        state = read_record(root/'job-status.json', {}) or {}
        output = Path(config['out'])
        cases = [(output, {'original': config['images'][0]})] if config.get('chain') else [
            (path.parent/'run', read_record(path, {}) or {}) for path in sorted(output.glob('*/case.json'))]
        for case_root, manifest in cases:
            if not (case_root/'runtime-status.json').is_file():
                continue
            key = str(case_root)
            entry = children.setdefault(key, {'monitor': Monitor(case_root), 'done': False, 'manifest': manifest})
            if not entry['done']:
                entry['done'] = entry['monitor'].poll()
        controller_dead = state.get('controller_pid') and not process_alive(state['controller_pid'])
        if controller_dead and state.get('worker_pid') and process_alive(state['worker_pid']):
            parent.alert('controller_stopped', 'FigFox · 启动器异常退出', '生成进程仍在运行，后台监控继续跟踪。未重复付费。')
        if not children and not controller_dead and time.time()-state.get('started_at',time.time()) > 300:
            parent.alert('startup_slow', 'FigFox · 准备阶段耗时较长', '尚未开始出图，请查看本地运行记录。没有自动追加模型请求。')
        finished = state.get('status') in ('completed','failed') or (
            controller_dead and not process_alive(state.get('worker_pid')))
        cards = []
        total = 0
        for entry in children.values():
            record = entry['monitor'].record
            total += record.get('costs', {}).get('estimated_usd', 0)
            cards.append('<li><a href="'+html.escape((entry['monitor'].root/'status.html').as_uri(),quote=True)+'">'+
                html.escape(Path(entry['manifest'].get('original','')).name)+' · '+html.escape(STATUS_LABELS.get(record.get('status'), '正在运行'))+'</a></li>')
        atomic_text(root/'status.html', '<!doctype html><meta charset="utf-8">'+('' if finished else '<meta http-equiv="refresh" content="5">')+
            '<title>FigFox 后台实验</title><style>body{font:18px system-ui;max-width:900px;margin:40px auto;line-height:1.8}li{margin:18px 0}</style><h1>FigFox 后台实验</h1><p>'+('已结束' if finished else '正在运行')+
            f' · 已知累计费用 ${total:.4f}</p><p>费用以每图为单位提示；进行中的请求与缺失用量见各图详情。</p><p><a href="'+html.escape((root/'console.log').as_uri(),quote=True)+'">查看运行记录</a></p><ul>'+''.join(cards)+'</ul>')
        write_json(root/'monitor-health.json', {'monitor_pid': os.getpid(), 'heartbeat_at': time.time(), 'finished': finished})
        if finished:
            parent.alert('job_terminal', 'FigFox · 后台实验已结束', f'已知累计费用 ${total:.4f}。请查看各图结果与未完成事项。')
            return
        time.sleep(5)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', required=True, type=Path)
    parser.add_argument('--mode', choices=('chain','job'), default='chain')
    args = parser.parse_args()
    root = args.root.resolve()
    while True:
        try:
            if args.mode == 'job':
                monitor_job(root)
            else:
                monitor = Monitor(root)
                while not monitor.poll():
                    time.sleep(5)
            return
        except OSError as exc:
            try:
                print(f'Monitor I/O error; retrying local monitoring: {exc}', file=sys.stderr, flush=True)
            except OSError:
                pass
            time.sleep(5)


if __name__ == '__main__':
    main()
