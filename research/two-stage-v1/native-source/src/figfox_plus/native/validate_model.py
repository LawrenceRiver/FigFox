"""A real API chooses a reference region and constructor. No handwritten answers."""
import json
from pathlib import Path
from .document import measure,serialize
from .tools import sp_element
from ..state import PLUS_ROOT,new_run,write_json
from ..providers import call_deepseek
from ..pipeline import parse_json
from ..sp.catalog import manual
from ..assets import crop_asset
import xml.etree.ElementTree as ET

def sp_probe(original):
    run=new_run(PLUS_ROOT/'runs','native-sp-model-proof')
    prompt='''根据这张原图，自行选择一个清晰的单个几何体（不是复杂多物体组合），根据SP说明书描述正向组成、反推步骤，并选择真实构造器及参数。你必须自己从图中判断source_crop；宿主没有给任何坐标答案。只输出JSON：{name,description,forward_composition:[...],inverse_steps:[...],source_crop:[x,y,w,h],kind:"geometry",data:{实际SP构造参数}}。data使用以局部对象为中心的坐标即可，宿主只按最终实际边界生成展示视口，不改几何。不要编写原始SVG，不要用asset。对照参考确保面朝向、网格/数量、比例、颜色与轮廓符合。\n'''+manual()
    raw=call_deepseek(prompt,[Path(original)],run/'deepseek-1','native SP understanding probe')
    reply=parse_json(raw);write_json(run/'model-plan.json',reply)
    g=sp_element(reply['kind'],reply['data'],'probe');root=ET.Element('svg',{'xmlns':'http://www.w3.org/2000/svg','width':'800','height':'800','viewBox':'0 0 800 800'});g.set('id','probe');root.append(g)
    b=measure(root)['objects']['probe']['paint_bbox'];w=b['right']-b['left'];h=b['bottom']-b['top']
    if min(w,h)<=0:raise ValueError('empty model geometry')
    pad=max(w,h)*.05;root.set('viewBox',f'{b["left"]-pad} {b["top"]-pad} {w+2*pad} {h+2*pad}');root.set('width',str(round(w+2*pad)));root.set('height',str(round(h+2*pad)))
    (run/'scene.svg').write_text(serialize(root));measure(root,run/'preview.png')
    asset=crop_asset(original,reply['source_crop'],run/'reference');write_json(run/'proof.json',{'source':'saved DeepSeek model-plan.json','crop':asset,'manual_numeric_answers':False,'viewport_only':'generic measured bounds','compiled':True,'visual_passed':False})
    return run

def sp_retry(previous,original):
    previous=Path(previous);run=new_run(PLUS_ROOT/'runs','native-sp-model-retry')
    old=json.loads((previous/'model-plan.json').read_text());proof=json.loads((previous/'proof.json').read_text())
    prompt='''上轮真实SP测试没有通过视觉验收。你选的原图crop切到了对象，也包含邻近连线；构造步骤声称有网格，但你选择的cuboid只会生成平面，实际没有网格。请看完整原图、你选的crop和实际SP输出，自行重新定位所选单个几何的完整区域，并按能力选择构造器。这里没有给任何修正坐标、数量或尺寸，全部由你判断。只输出与上轮相同JSON格式的完整修正，source_crop只能从完整原图坐标推断。保留正向组成和反推步骤。\n'''+json.dumps(old,ensure_ascii=False)+'\n'+manual()
    raw=call_deepseek(prompt,[Path(original),Path(proof['crop']['path']),previous/'preview.png'],run/'deepseek-1','native SP understanding correction')
    reply=parse_json(raw);write_json(run/'model-plan.json',reply)
    g=sp_element(reply['kind'],reply['data'],'probe');root=ET.Element('svg',{'xmlns':'http://www.w3.org/2000/svg','width':'800','height':'800','viewBox':'0 0 800 800'});g.set('id','probe');root.append(g)
    b=measure(root)['objects']['probe']['paint_bbox'];w=b['right']-b['left'];h=b['bottom']-b['top'];pad=max(w,h)*.05
    root.set('viewBox',f'{b["left"]-pad} {b["top"]-pad} {w+2*pad} {h+2*pad}');root.set('width',str(round(w+2*pad)));root.set('height',str(round(h+2*pad)))
    (run/'scene.svg').write_text(serialize(root));measure(root,run/'preview.png');asset=crop_asset(original,reply['source_crop'],run/'reference')
    write_json(run/'proof.json',{'source':'saved DeepSeek model-plan.json','crop':asset,'previous':str(previous),'manual_numeric_answers':False,'compiled':True,'visual_passed':False});return run
