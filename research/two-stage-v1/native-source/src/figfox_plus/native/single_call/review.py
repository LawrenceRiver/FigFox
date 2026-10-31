"""Display saved predictions without loading evaluation labels or mutating inputs."""
import html
import json
import os
from pathlib import Path


def write_prediction_review(task_dir):
    folder=Path(task_dir)
    plan=json.loads((folder/'response-plan.json').read_text())
    manifest=json.loads((folder/'input-manifest.json').read_text())
    esc=lambda v:html.escape(str(v),quote=True)
    rel=lambda p:esc(os.path.relpath(p,folder))
    sections=[]
    for image_id,info in manifest['images'].items():
        bounds=json.loads((Path(info['folder'])/'baseline/bounds.json').read_text())
        c=bounds['canvas'];view=f"{c['x']} {c['y']} {c['width']} {c['height']}"
        image=f'<image href="{rel(info["current_png"])}" x="{c["x"]}" y="{c["y"]}" width="{c["width"]}" height="{c["height"]}"/>'
        cards=[]
        for issue in plan['issues']:
            if issue['image_id']!=image_id:continue
            boxes=[];missing=[]
            for oid in issue['target_ids']:
                b=bounds['objects'].get(oid,{}).get('geometry_bbox')
                if b is None:missing.append(oid);continue
                boxes.append(f'<rect x="{b["left"]}" y="{b["top"]}" width="{max(1,b["right"]-b["left"])}" height="{max(1,b["bottom"]-b["top"])}" fill="none" stroke="#cf3030" stroke-width="2"/>')
            cards.append(f'<details><summary>{esc(issue["id"])} · {esc(issue["category"])} · {esc(issue["decision"])}：{esc(issue["description"])}</summary><p>先按描述定位。红框只表示模型选择对象的现图范围，不证明范围内有问题。</p><svg viewBox="{view}">{image}{"".join(boxes)}</svg><p>未画框的对象：{esc(", ".join(missing) or "无")}</p><pre>{esc(json.dumps(issue,ensure_ascii=False,indent=2))}</pre></details>')
        sections.append(f'<section><h2>{esc(image_id)} · {len(cards)} 条原始候选</h2><div class="pair"><figure><figcaption>原图</figcaption><img src="{rel(info["original"])}"></figure><figure><figcaption>首轮当前图（未修复）</figcaption><img src="{rel(info["current_png"])}"></figure></div>{"".join(cards)}</section>')
    error=json.loads((folder/'run-error.json').read_text()) if (folder/'run-error.json').exists() else None
    page='''<!doctype html><meta charset="utf-8"><title>三图候选结果</title><style>
body{font:16px system-ui;margin:30px auto;max-width:1500px;padding:0 20px;color:#172332}section{margin:30px 0}.pair{display:grid;grid-template-columns:1fr 1fr;gap:16px}figure{margin:0}img,svg{width:100%}details{margin:12px 0;padding:12px;border:1px solid #ccc}summary{cursor:pointer;line-height:1.6}pre{white-space:pre-wrap;overflow-wrap:anywhere}figcaption{padding:8px} @media(max-width:800px){.pair{grid-template-columns:1fr}}</style>
<h1>三图候选结果 · 待人工验收</h1><p>一次请求。这里只展示模型实际报告，尚未执行修复；模型的 confirmed 不等于验收通过。</p>
<p><a href="api/live.html">API 返回记录</a> · <a href="response-plan.json">完整原始 JSON</a></p>'''
    if error:page+='<p>计划校验：'+esc(error['error'])+'</p>'
    (folder/'index.html').write_text(page+''.join(sections),encoding='utf-8')
    return folder/'index.html'
