"""Offline review of actual saved outputs, with no inferred success labels."""
import html
import json
import os
from pathlib import Path


def write_report(task_dir, manifest, result):
    folder=Path(task_dir);cards=[]
    def esc(value):return html.escape(str(value))
    def src(path):return esc(os.path.relpath(path,folder))
    for image_id,output in result['images'].items():
        inputs=manifest['images'][image_id]
        figures=''.join('<figure><figcaption>'+label+'</figcaption><img src="'+src(path)+'"></figure>'
                        for label,path in [('原图',inputs['original']),('修改前',inputs['current_png']),('当前实际输出',output['png'])])
        records=[r for r in result['rcd'] if r['image_id']==image_id]
        rows=''.join('<tr><td>'+esc(r['operation_id'])+'</td><td>'+esc(r['executor']+' / '+r['module'])+
                     '</td><td>'+esc(r['execution_status'])+'</td><td><pre>'+esc(json.dumps(r['actual_parameters'],ensure_ascii=False,indent=2))+
                     '</pre></td></tr>' for r in records)
        cards.append('<section><h2>'+esc(image_id)+'</h2><div class="images">'+figures+'</div><p><a href="'+src(output['svg'])+
                     '">当前 SVG</a></p><table><thead><tr><th>动作</th><th>执行模块</th><th>实际状态</th><th>实际参数</th></tr></thead><tbody>'+rows+'</tbody></table></section>')
    page='''<!doctype html><meta charset="utf-8"><title>本地修复待检修记录</title>
<style>body{font:15px system-ui;max-width:1500px;margin:32px auto;padding:0 24px;color:#18232d;background:#f6f7f9}
section{background:white;padding:24px;margin:24px 0;border-radius:12px}.images{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
figure{margin:0}img{width:100%;border:1px solid #ccd3da}figcaption{margin:8px 0}table{border-collapse:collapse;width:100%}td,th{text-align:left;border-bottom:1px solid #ddd;padding:10px;vertical-align:top}pre{white-space:pre-wrap;overflow-wrap:anywhere;margin:0}
@media(max-width:800px){.images{grid-template-columns:1fr}}</style>
<h1>本地修复待检修记录</h1><p>这里展示实际保存的修改前后图和 RCD。执行成功、TP 不报警均不等于视觉验收通过。</p>
<p><a href="rcd.jsonl">完整 RCD</a> · <a href="result.json">结果与未解决项</a></p>'''+''.join(cards)
    (folder/'index.html').write_text(page,encoding='utf-8')
