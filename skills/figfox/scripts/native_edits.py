"""Model contracts and deterministic SVG edits. No sample-specific answers."""
import base64,io,math,re
import xml.etree.ElementTree as E
from PIL import Image
N='http://www.w3.org/2000/svg';E.register_namespace('',N)
OPS={'set','text','remove','append_svg','replace_svg','source_crop','tp_transform','tp_align','tp_fit'}
def require(ok,message):
 if not ok:raise ValueError(message)
def nonempty(v):return isinstance(v,str) and bool(v.strip())
def index(root):return {n.get('id'):n for n in root.iter() if n.get('id')}
def validate_findings(value,width,height):
 require(isinstance(value,dict),'G1 object required');regions=value.get('regions',[]);issues=value.get('issues',[])
 require(isinstance(regions,list) and len(regions)==4 and {r.get('id') for r in regions}==set('ABCD'),'four region receipts required')
 for r in regions:require(r.get('status') in {'differences','no_confirmed_difference','uncertain'} and nonempty(r.get('evidence')),'region evidence/status missing')
 require(isinstance(issues,list),'issues array required');ids=[]
 for issue in issues:
  require(isinstance(issue,dict) and nonempty(issue.get('id')) and issue.get('region') in 'ABCD','finding identity invalid');ids.append(issue['id'])
  require(all(nonempty(issue.get(k)) for k in ['source_evidence','initial_evidence','repair']),'actual paired evidence and repair required')
  box=issue.get('bbox');require(isinstance(box,list) and len(box)==4 and all(isinstance(x,(int,float)) and not isinstance(x,bool) and math.isfinite(x) for x in box),'finite whole-initial box required')
  x,y,xx,yy=box;require(0<=x<xx<=width and 0<=y<yy<=height,'finding box outside whole initial')
 require(len(ids)==len(set(ids)),'duplicate finding IDs')
 for r in regions:
  related=any(i['region']==r['id'] for i in issues)
  require((r['status']=='differences')==related,'region finding status contradicts issues')
 return value

def validate_plan(value,findings,svg):
 require(isinstance(value,dict),'G2 object required');txs=value.get('transactions',[]);unresolved=value.get('unresolved',[])
 require(isinstance(txs,list) and isinstance(unresolved,list),'transactions/unresolved arrays required')
 actual=set(index(E.fromstring(svg)))|{'ROOT'};issueids={i['id'] for i in findings['issues']};covered=set();txids=[]
 for t in txs:
  require(nonempty(t.get('id')),'transaction id required');txids.append(t['id'])
  require(isinstance(t.get('issue_ids'),list) and bool(t['issue_ids']) and set(t['issue_ids'])<=issueids,'unbound issue in G2')
  require(isinstance(t.get('target_ids'),list) and bool(t['target_ids']) and set(t['target_ids'])<=actual,'G2 target IDs do not exist in initial')
  require(isinstance(t.get('depends_on'),list) and nonempty(t.get('instructions')) and isinstance(t.get('parameters'),dict),'concrete instructions/parameters/dependencies required');covered.update(t['issue_ids'])
 require(len(txids)==len(set(txids)),'duplicate transactions')
 seen=set()
 for t in txs:
  require(set(t['depends_on'])<=seen,'dependencies must precede transaction');seen.add(t['id'])
 unresolvedids=[]
 for u in unresolved:
  require(u.get('issue_id') in issueids and nonempty(u.get('reason')),'unresolved issue needs evidence');unresolvedids.append(u['issue_id'])
 require(len(unresolvedids)==len(set(unresolvedids)) and not(set(unresolvedids)&covered),'duplicate/conflicting disposition')
 require(covered|set(unresolvedids)==issueids,'G2 omitted issue disposition')
 return value

def validate_implementation(value,plan,svg):
 require(isinstance(value,dict) and isinstance(value.get('transactions'),list),'D1 transactions required')
 expected={t['id']:t for t in plan['transactions']};txs=value['transactions'];require([t.get('id') for t in txs]==list(expected),'D1 must cover all G2 transactions in order')
 root=E.fromstring(svg);actual=index(root)
 for t in txs:
  spec=expected[t['id']];allowed=set()
  for ident in spec['target_ids']:
   if ident=='ROOT':allowed.update(actual);allowed.add('ROOT')
   else:allowed.update(n.get('id') for n in actual[ident].iter() if n.get('id'))
  edits=t.get('edits');require(isinstance(edits,list) and bool(edits),'D1 returned no transaction edits')
  introduced=set()
  for op in edits:
   kind=op.get('op');require(kind in OPS,'unknown edit operation')
   targets=[op.get('id')] if kind in {'set','text','remove','replace_svg'} else [op.get('parent_id')]
   if kind.startswith('tp_'):targets=op.get('target_ids',[])+op.get('reference_ids',[]);require(bool(op.get('target_ids')),'TP selection required')
   if kind=='source_crop':targets+=op.get('remove_ids',[])
   require(all(x in allowed|introduced for x in targets),'D1 write outside G2 declared targets')
   if kind in {'append_svg','replace_svg'}:
    el=E.fromstring(op['svg']);introduced.update(n.get('id') for n in el.iter() if n.get('id'))
   elif kind=='source_crop':introduced.add(op['id'])
 return value

def safe_svg(root):
 for n in root.iter():
  require(n.tag.rsplit('}',1)[-1] not in {'script','foreignObject'},'active SVG forbidden')
  for key,val in n.attrib.items():
   require(not key.lower().startswith('on'),'event attribute forbidden')
   if key.rsplit('}',1)[-1]=='href':require(val.startswith(('#','data:image/png;base64,','data:image/jpeg;base64,')),'external href forbidden')
   for target in re.findall(r'url\((.*?)\)',val):require(target.strip(' \"\'').startswith('#'),'external CSS URL forbidden')
  if n.tag.rsplit('}',1)[-1]=='style':require(not re.search(r'@import|url\(\s*[\"\']?https?:',n.text or '',re.I),'external stylesheet forbidden')
 ids=[n.get('id') for n in root.iter() if n.get('id')];require(len(ids)==len(set(ids)),'duplicate final SVG IDs')
 refs=set(re.findall(r'url\(#([^)]*)\)',E.tostring(root,encoding='unicode')));require(refs<=set(ids),'unresolved SVG ID references: '+str(refs-set(ids)))

def apply_edits(svg,edits,source_image):
 root=E.fromstring(svg);initial_canvas={k:root.get(k) for k in ['width','height','viewBox']};journal=[];area=0
 def find(ident):
  if ident=='ROOT':return root
  require(ident in index(root),'missing current ID: '+str(ident));return index(root)[ident]
 def delete(n):
  require(n is not root and n.get('id')!='canvas_bg','root/background deletion forbidden');parents={ch:p for p in root.iter() for ch in p};parents[n].remove(n)
 for i,op in enumerate(edits):
  kind=op['op'];require(kind in OPS,'unknown operation')
  if kind.startswith('tp_'):
   from figfox_plus.native import tp_v2
   if kind=='tp_transform':receipt=tp_v2.transform(root,op['target_ids'],op['world_matrix'])
   elif kind=='tp_align':receipt=tp_v2.align(root,op['target_ids'],op['reference_ids'],op['mode'])
   else:receipt=tp_v2.fit(root,op['target_ids'],op['target_tp'],op.get('mode','contain'))
   journal.append({'index':i,'operation':kind,'executed':True,'measurement_receipt':receipt});continue
  if kind=='set':find(op['id']).attrib.update({k:str(v) for k,v in op['attributes'].items()})
  elif kind=='text':find(op['id']).text=op['text']
  elif kind=='remove':delete(find(op['id']))
  elif kind in {'append_svg','replace_svg'}:
   el=E.fromstring(op['svg'])
   if kind=='append_svg':find(op['parent_id']).append(el)
   else:
    old=find(op['id']);require(old is not root and old.get('id')!='canvas_bg','root/background replacement forbidden');parents={ch:p for p in root.iter() for ch in p};p=parents[old];pos=list(p).index(old);p.remove(old);p.insert(pos,el)
  elif kind=='source_crop':
   require(source_image is not None,'source image required');im=Image.open(source_image).convert('RGB');box=op['source_box'];l,t,rr,bb=box;x,y,w,h=op['target_box']
   require(0<=l<rr<=im.width and 0<=t<bb<=im.height and w>0 and h>0,'invalid local crop')
   a=(rr-l)*(bb-t);area+=a;require(a<im.width*im.height*.3 and area<im.width*im.height*.5,'broad reference raster replacement forbidden')
   parent=find(op['parent_id']);selected=[find(k) for k in op.get('remove_ids',[])];ss=set(selected);parents={ch:p for p in root.iter() for ch in p}
   for n in selected:
    ancestor=parents.get(n);covered=False
    while ancestor is not None:
     if ancestor in ss:covered=True;break
     ancestor=parents.get(ancestor)
    if not covered:delete(n)
   require(parent in set(root.iter()),'source crop parent removed by same operation')
   buf=io.BytesIO();im.crop(tuple(box)).save(buf,format='PNG')
   E.SubElement(parent,'{'+N+'}image',{'id':op['id'],'x':str(x),'y':str(y),'width':str(w),'height':str(h),'href':'data:image/png;base64,'+base64.b64encode(buf.getvalue()).decode()})
  journal.append({'index':i,'operation':kind,'executed':True})
 require({k:root.get(k) for k in initial_canvas}==initial_canvas,'initial canvas identity changed');safe_svg(root)
 return E.tostring(root,encoding='unicode'),journal
