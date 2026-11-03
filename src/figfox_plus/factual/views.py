"""Lossless wire views and explicit navigation-only schema binding; no visual decisions."""
import copy,hashlib,re,xml.etree.ElementTree as E
PREFIX='figfox-inline-asset:sha256:'
def project_assets(svg):
 aliases={};proof=[];view=svg
 for n in E.fromstring(svg).iter():
  for key,value in n.attrib.items():
   if not value.startswith('data:image/'):continue
   digest=hashlib.sha256(value.encode()).hexdigest();alias=PREFIX+digest
   if value not in svg:raise ValueError('XML image encoding cannot be losslessly projected')
   aliases[alias]=value;view=view.replace(value,alias);proof.append({'element_id':n.get('id'),'attribute':key,'original_URI_sha256':digest,'original_URI_bytes':len(value.encode()),'alias':alias})
 if restore_string(view,aliases)!=svg:raise ValueError('asset wire projection not reversible')
 return view,aliases,proof

def restore_string(value,aliases):
 for alias,original in aliases.items():value=value.replace(alias,original)
 return value

def restore_plan(plan,aliases):
 result=copy.deepcopy(plan)
 for tx in result.get('transactions',[]):
  for op in tx.get('parameters',{}).get('operations',[]):
   if isinstance(op.get('svg'),str):op['svg']=restore_string(op['svg'],aliases)
   for key,value in list(op.get('attributes',{}).items()):
    if isinstance(value,str):op['attributes'][key]=restore_string(value,aliases)
 return result

def bind_global_navigation(plan,width,height):
 result=copy.deepcopy(plan);proof=[]
 for issue in result.get('additional_issues',[]):
  if issue.get('region') in {'A','B','C','D'}:continue
  original=issue.get('region');box=issue.get('bbox')
  if original=='Whole' and box==[0,0,width,height]:regions=['A','B','C','D'];primary='D'
  elif isinstance(original,str) and re.fullmatch(r'[ABCD](?:[ /,|+&-]+[ABCD])+',original):
   if not isinstance(box,list) or len(box)!=4:raise ValueError('explicit paired footprint required')
   left,top,right,bottom=box
   if not 0<=left<right<=width or not 0<=top<bottom<=height:raise ValueError('cross-region footprint outside canvas')
   regions=[]
   for name,(l,t,r,b) in [('A',(0,0,width/2,height/2)),('B',(width/2,0,width,height/2)),('C',(0,height/2,width/2,height)),('D',(width/2,height/2,width,height))]:
    if max(left,l)<min(right,r) and max(top,t)<min(bottom,b):regions.append(name)
   declared=set(re.findall('[ABCD]',original))
   if set(regions)!=declared:raise ValueError('composite label conflicts with explicit geometry; cannot infer localization')
   x=(left+right)/2;y=(top+bottom)/2;primary=('A' if x<width/2 else 'B') if y<height/2 else ('C' if x<width/2 else 'D')
  else:raise ValueError('unsupported region requires factual localization; no inference allowed')
  proof.append({'issue_id':issue.get('id'),'original_region':original,'primary_navigation_region':primary,'actual_affected_regions':regions,'original_full_footprint_unchanged':True,'all_visual_facts_and_operations_unchanged':True});issue['region']=primary

 return result,proof

def bind_requested_unknowns(report,width,height):
 result=copy.deepcopy(report);proof=[];facts=result.get('fact_inventory',[]);ids={f['id'] for f in facts}
 for req in result.get('detail_requests',[]):
  ident=req.get('fact_id')
  if ident in ids:continue
  if not isinstance(ident,str) or not ident.strip() or not isinstance(req.get('reason'),str) or not req['reason'].strip():raise ValueError('orphan crop request has no explicit identity/reason')
  box=req.get('initial_box');source=req.get('source_box')
  if not isinstance(box,list) or len(box)!=4 or not isinstance(source,list) or len(source)!=4:raise ValueError('original paired crop boxes required')
  x=(box[0]+box[2])/2;y=(box[1]+box[3])/2;region=('A' if x<width/2 else 'B') if y<height/2 else ('C' if x<width/2 else 'D')
  slot={'id':ident,'region':region,'kind':'layout','source_reading':None,'initial_reading':None,'source_box':copy.deepcopy(source),'initial_box':copy.deepcopy(box),'certainty':'uncertain','source_basis':'Host-created unknown bookkeeping slot for this ORIGINAL G1 close-up request; no source value was supplied or inferred. Original model reason: '+req['reason'],'host_unknown_slot_not_model_observation':True}
  facts.append(slot);ids.add(ident);proof.append({'original_request_fact_id':ident,'original_reason':req['reason'],'original_paired_boxes_unchanged':True,'source_and_initial_readings':None,'certainty':'uncertain','host_unknown_slot_not_observed_fact':True})
 result['fact_inventory']=facts
 return result,proof

def normalize_score_case(value):
 result=copy.deepcopy(value);proof=[];known={'pass':'pass','fail':'fail','unknown':'unknown','na':'NA'}
 for item in result.get('items',[]):
  status=item.get('status')
  if not isinstance(status,str):continue
  canonical=known.get(status.lower())
  if canonical is not None and canonical!=status:
   item['provider_original_status']=status;item['status']=canonical;proof.append({'id':item.get('id'),'original':status,'canonical':canonical,'case_only':True,'evidence_unchanged':True})
 return result,proof

def deduplicate_index(payload):
 result=copy.deepcopy(payload);svg=result['initial_svg'];actual={}
 for n in E.fromstring(svg).iter():
  ident=n.get('id')
  if not ident:continue
  tag=n.tag.rsplit('}',1)[-1];text=''.join(n.itertext()) if tag in {'text','tspan'} else None
  actual[ident]=[tag]+([text] if text is not None else [])
 if result.get('object_index')!=actual:raise ValueError('redundant index contains information not exactly recoverable from original SVG')
 del result['object_index'];result['object_index_encoding']='Redundant object index deduplicated: every exact existing ID, tag and text is present in initial_svg. No semantic, coordinate, geometry or image evidence removed.'
 return result,{'entries':len(actual),'all_entries_exactly_recoverable':True,'full_SVG_unchanged':True,'all_other_payload_fields_unchanged_except_encoding_explanation':True}
