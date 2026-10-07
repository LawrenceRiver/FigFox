"""Explicit-input review report. Execution receipts are never visual acceptance.

Only supplied PNG assets are read. No directory discovery, result-file lookup,
private acceptance import or unverified geometric overlay is performed.
"""
import html
import json
from pathlib import Path
import shutil
from PIL import Image


def _esc(value):
    if isinstance(value,(dict,list)):value=json.dumps(value,ensure_ascii=False,indent=2)
    return html.escape(str(value if value is not None else ''),quote=True)


def _path(value):
    if isinstance(value,dict):value=value.get('path')
    return Path(value) if isinstance(value,(str,Path)) else None


def _picture(value, destination, name, label):
    path=_path(value)
    if path is None:return '<figure><figcaption>'+_esc(label)+'</figcaption><p>尚未提供'+_esc(label)+'</p></figure>'
    try:
        with Image.open(path) as image:
            if image.format!='PNG':raise ValueError('report accepts PNG assets only')
            # Re-encode pixels; never embed supplied markup or image metadata.
            image.convert('RGBA').save(destination/name,format='PNG')
    except (OSError,SyntaxError) as error:
        raise ValueError('invalid report PNG asset') from error
    url='report-assets/'+name
    return '<figure><figcaption>'+_esc(label)+'</figcaption><a href="'+url+'"><img src="'+url+'" alt="'+_esc(label)+'"></a></figure>'


def _records(value):
    if isinstance(value,list):return [x for x in value if isinstance(x,dict)]
    if isinstance(value,dict):return [x for x in value.values() if isinstance(x,dict)]
    return []


def _receipt(record):
    status=record.get('status','unknown')
    changed=status in ('executed_changed','changed','changed_unverified') or record.get('changed') is True
    display='changed_unverified：代码已改变，视觉待核验' if changed else _esc(status)
    if status=='deferred_source_geometry':display='deferred_source_geometry：原图立体证据不足，未执行，保留当前对象'
    fields={key:record[key] for key in ('step_id','operation','tool','method','actual_parameters','parameters','error','rollback','rolled_back','before_revision','after_revision','source_geometry_checks','source_geometry_check','original_preserved','automatic_followup_allowed') if key in record}
    return '<div class="receipt"><strong>'+display+'</strong><pre>'+_esc(fields)+'</pre></div>'


def write_report(task_dir, inputs, issues, rcd, coverage=None, *, output_images=None, candidates=None):
    """Write index.html from explicit inputs, issues, receipts and output images.

    output_images is {image_id: PNG path/asset or {png: path/asset}}. No external
    visual confirmation is accepted here; changed operations stay unverified.
    """
    root=Path(task_dir);root.mkdir(parents=True,exist_ok=True)
    assets=root/'report-assets';assets.mkdir(exist_ok=True)
    images=inputs.get('images',{})
    if not isinstance(images,dict):raise ValueError('inputs.images must be an image map')
    issue_rows=_records(issues);receipts=_records(rcd);output_images=output_images or {}
    parts=['<!doctype html><html lang="zh"><meta charset="utf-8"><title>检出与实际执行复核</title>',
        '<style>body{font:16px system-ui;margin:24px;color:#20252b}h1{font-size:26px}.images{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px}figure{margin:0;border:1px solid #bbc3cb;padding:10px}img{width:100%;height:auto}figcaption{font-weight:bold;margin-bottom:8px}.issue{border:1px solid #cbd1d6;border-left:5px solid #b47713;margin:14px 0;padding:14px}.receipt{background:#f5f6f7;padding:8px;margin-top:8px}pre{white-space:pre-wrap;overflow-wrap:anywhere}.notice{padding:14px;background:#fff1ce}@media(max-width:850px){.images{grid-template-columns:1fr}}</style>',
        '<h1>检出问题与实际执行复核</h1><p class="notice">代码执行成功不等于视觉修复通过。所有改动默认 changed_unverified，未做人工视觉确认，不标绿。三轮覆盖记录只能证明提交了记录，不能证明判断正确。</p>']
    if isinstance(coverage,dict):
        summary={key:coverage[key] for key in ('expected','submitted','missing','complete','expected_count','completed_count','missing_count') if key in coverage and isinstance(coverage[key],(bool,int,float))}
        if summary:parts.append('<h2>检查覆盖</h2><pre>'+_esc(summary)+'</pre>')
    displayed=set()
    for number,(image_id,info) in enumerate(images.items()):
        parts.append('<section><h2>'+_esc(image_id)+'</h2><div class="images">')
        output=output_images.get(image_id)
        if isinstance(output,dict) and 'png' in output:output=output['png']
        for side,value,label in [('original',info.get('original_png'),'原图'),('current',info.get('current_png',info.get('png')),'初始现图'),('final',output,'最终图')]:
            parts.append(_picture(value,assets,f'{number:03d}-{side}.png',label))
        parts.append('</div>')
        for candidate_number, candidate in enumerate(candidates or []):
            proposed = candidate.get('images', {}).get(image_id)
            if not proposed:
                continue
            name = f'{number:03d}-candidate-{candidate_number:03d}'
            parts.append('<details><summary>查看待确认候选（保留当前结果，未自动采用）</summary>'
                         '<p class="notice">这是基于当时现图生成的独立候选，可能包含其他同期修复。'
                         '可渲染不代表更准确，也不代表已通过视觉验收。</p>')
            parts.append(_picture(proposed.get('png'), assets, name + '.png', '候选图：视觉待确认'))
            svg = _path(proposed.get('svg'))
            if svg is not None and svg.is_file():
                shutil.copyfile(svg, assets / (name + '.svg'))
                parts.append('<p><a href="report-assets/' + name + '.svg">下载候选 SVG</a></p>')
            parts.append('<pre>' + _esc({key:candidate[key] for key in
                ('step','object_id','program_ids','base_revisions','status','automatically_adopted','visual_acceptance')
                if key in candidate}) + '</pre></details>')
        relevant=[issue for issue in issue_rows if issue.get('image_id')==image_id]
        if not relevant:parts.append('<p>没有提交检出问题；这不代表图片无问题。</p>')
        for issue in relevant:
            identity=issue.get('issue_id',issue.get('id','未命名问题'))
            parts.append('<article class="issue"><h3>'+_esc(identity)+' · '+_esc(issue.get('category',issue.get('type','')) )+'</h3>')
            for key,label in [('semantic_location','语义定位'),('location','定位描述'),('description','问题描述'),('original_evidence','原图证据'),('current_evidence','现图证据'),('decision','检出判断'),('source_review','原图复核'),('status','检出状态')]:
                if key in issue:parts.append('<p><b>'+label+'：</b>'+_esc(issue[key])+'</p>')
            matches=[]
            for index,record in enumerate(receipts):
                ids=record.get('issue_ids',[])
                if not isinstance(ids,list):ids=[]
                if (record.get('issue_id')==identity or identity in ids) and record.get('image_id',image_id)==image_id:
                    matches.append(record);displayed.add(index)
            parts.extend(_receipt(record) for record in matches)
            if not matches:parts.append('<p>未执行／没有关联的实际 RCD。</p>')
            parts.append('</article>')
        parts.append('</section>')
    unbound=[record for index,record in enumerate(receipts) if index not in displayed]
    if unbound:
        parts.append('<h2>尚未关联到问题的执行记录</h2>')
        parts.extend(_receipt(record) for record in unbound)
    orphan=[issue for issue in issue_rows if issue.get('image_id') not in images]
    if orphan:
        parts.append('<h2>未关联图片的问题</h2>')
        for issue in orphan:parts.append('<pre>'+_esc({k:issue[k] for k in ('issue_id','id','image_id','category','description','semantic_location') if k in issue})+'</pre>')
    parts.append('</html>')
    path=root/'index.html';path.write_text('\n'.join(parts),encoding='utf-8');return path
