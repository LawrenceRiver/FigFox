from pathlib import Path
import tempfile,json,sys,copy
from unittest.mock import patch
import xml.etree.ElementTree as ET
import insertion_guard as guard,flow
sys.path.insert(0,str(Path('source/src').resolve()))
from figfox_plus.native.review_problem_first_v13 import programs as native

def run(before,raw,plans,guarded):
 with tempfile.TemporaryDirectory() as d:
  root=Path(d);svg=root/'input.svg';svg.write_text(before)
  for p in plans:p.update(phase='preconstructor',base_revision=guard.digest(before),depends_on=[],relations=[])
  images={'case':{'svg':str(svg),'png':'unused','original':'unused','revision':guard.digest(before)}};lowered,_=flow.native_issue_bindings(raw,svg)
  def checkpoint(tree,folder,index):
   folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);out=folder/f'{index}.svg';out.write_text(ET.tostring(tree,encoding='unicode'));return {'svg':str(out),'png':'synthetic','revision':guard.digest(out.read_text())},{}
  with patch.object(native,'write_checkpoint',checkpoint),patch.object(native,'measure_tight',lambda *a,**kw:{}):
   if guarded:
    with guard.transactions(native,plans,raw,images,root/'guard.jsonl') as check:
     result=native.execute_programs(plans,lowered,images,root/'native',capabilities={'version':'capabilities-v1','sam':False,'code_methods':True});check.verify(result)
   else:result=native.execute_programs(plans,lowered,images,root/'native',capabilities={'version':'capabilities-v1','sam':False,'code_methods':True})
  return [{'id':r['program_id'],'status':r['status'],'error':r.get('error'),'proof':r.get('insertion_common_guard',{}).get('status')} for r in result['rcd']]

def p(id,ids,targets,source):return {'id':id,'image_id':'case','route':'generated_python','issue_ids':ids,'target_ids':targets,'source_code':source}
before='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><g id="frame"/><g id="editable"><linearGradient id="paint"><stop id="stop" offset="0" stop-color="red"/></linearGradient></g><rect id="protected" width="10" height="10" fill="url(#paint)"/></svg>'
issues=[{'id':'missing','image_id':'case','category':'A','target_ids':[],'neighbor_ids':[],'container_id':'frame'},{'id':'existing','image_id':'case','category':'A','target_ids':['editable'],'neighbor_ids':[]}]
source="""import xml.etree.ElementTree as ET
r=ET.parse(INPUT_SVG).getroot()
next(n for n in r.iter() if n.get('id')=='stop').set('stop-color','blue')
ET.SubElement(next(n for n in r.iter() if n.get('id')=='frame'),'{http://www.w3.org/2000/svg}circle',{'id':'new','r':'2'})
ET.ElementTree(r).write(OUTPUT_SVG,encoding='unicode')
"""
resource=run(before,issues,[p('resource',['missing','existing'],['frame','editable'],source)],True)
before2='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect id="a" width="1"/><rect id="b" width="1"/></svg>'
issues2=[{'id':x,'image_id':'case','category':'A','target_ids':[x],'neighbor_ids':[]} for x in ('a','b')]
same='import xml.etree.ElementTree as ET\nr=ET.parse(INPUT_SVG).getroot()\nET.ElementTree(r).write(OUTPUT_SVG,encoding="unicode")'
plans=[p('pa',['a'],['a'],same),p('pb',['b'],['b'],same)]
results={'resource_global_side_effect_guarded':resource,'duplicate_source_unguarded':run(before2,issues2,copy.deepcopy(plans),False),'duplicate_source_guarded':run(before2,issues2,copy.deepcopy(plans),True)}
print(json.dumps(results,indent=2));Path('review-proof.json').write_text(json.dumps(results,indent=2)+'\n')
