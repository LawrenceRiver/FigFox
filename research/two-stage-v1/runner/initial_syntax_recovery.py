"""Zero-HTTP recovery of deterministic missing XML closing tags only."""
import re,json,subprocess,xml.etree.ElementTree as ET
from pathlib import Path
import run_ablation as r,live_api as api

def repair(text):
 match=re.search(r'<svg\b.*?</svg>',text,re.S)
 if not match:raise ValueError('complete SVG envelope required; truncation cannot be repaired')
 svg=match.group()
 try:root=ET.fromstring(svg)
 except ET.ParseError:root=None
 if root is not None:
  ids={node.get('id') for node in root.iter() if node.get('id')};operations=[]
  def clean_refs(found):
   values=found.group(2).split();missing=[value for value in values if value not in ids]
   if not missing:return found.group()
   operations.append({'operation':'remove nonexistent keep-only metadata references; all real keep protections unchanged','original_reference_value':found.group(2),'removed_nonexistent_ids':missing,'existing_ids_sha256':r.digest(sorted(ids)),'all_existing_keeps_retained':True})
   return 'data-plus-keeps='+found.group(1)+' '.join(value for value in values if value in ids)+found.group(1)
  fixed=re.sub(r'''data-plus-keeps=(["'])(.*?)\1''',clean_refs,svg)
  projected=ET.fromstring(fixed);owners={};duplicates=[];alias_nodes=set();alias_operations=[]
  for index,node in enumerate(projected.iter()):
   key='{http://www.w3.org/1999/xlink}href';value=node.get(key)
   if node.tag.rsplit('}',1)[-1]=='image' and value==node.get('href') and isinstance(value,str) and re.fullmatch(r'asset_sam_region_[0-9]+',value):
    del node.attrib[key];alias_nodes.add(index);alias_operations.append({'node_id':node.get('id'),'same_original_href_and_xlink_href':value})
  if alias_operations:operations.append({'operation':'remove byte-identical duplicate xlink asset alias; native SAM binding embeds the same unqualified href','aliases':alias_operations,'no_image_or_geometry_removed':True})
  original_targets={value for node in projected.iter() for value in node.get('data-plus-replaces','').split()}
  original_protected={value for node in projected.iter() if node.get('data-plus-replaces') for value in node.get('data-plus-keeps','').split()}
  for node in projected.iter():
   targets=node.get('data-plus-replaces','').split();retained=[]
   for target in targets:
    if target not in owners:owners[target]=node;retained.append(target);continue
    owner=owners[target];keep=list(dict.fromkeys(owner.get('data-plus-keeps','').split()+node.get('data-plus-keeps','').split()))
    if keep:owner.set('data-plus-keeps',' '.join(keep))
    duplicates.append({'target':target,'first_owner':owner.get('id'),'duplicate_owner':node.get('id'),'all_SAM_image_nodes_preserved':True,'existing_keep_protections_unioned':keep})
   if targets:
    if retained:node.set('data-plus-replaces',' '.join(retained))
    else:node.attrib.pop('data-plus-replaces',None)
  cancelled=[];by_id={node.get('id'):node for node in projected.iter() if node.get('id')}
  for node in projected.iter():
   targets=node.get('data-plus-replaces','').split();safe=[]
   for target in targets:
    protected_inside=[part.get('id') for part in by_id[target].iter() if part.get('id') in original_protected] if target in by_id else []
    if protected_inside:cancelled.append({'replacement_id':node.get('id'),'cancelled_target':target,'protected_objects':protected_inside,'reason':'explicit keep wins; do not delete a protected object or remove any SAM image'})
    else:safe.append(target)
   if targets:
    if safe:node.set('data-plus-replaces',' '.join(safe))
    else:node.attrib.pop('data-plus-replaces',None)
  if cancelled:
   active=[node for node in projected.iter() if node.get('data-plus-replaces')]
   if active and original_protected:active[0].set('data-plus-keeps',' '.join(sorted(original_protected)))
   operations.append({'operation':'cancel only model deletion requests that violate explicit protected-object constraints; preserve all actual image/geometry nodes','cancelled_deletions':cancelled,'no_visible_object_removed_by_projection':True})
  if duplicates or cancelled:
   new_targets={value for node in projected.iter() for value in node.get('data-plus-replaces','').split()};new_protected={value for node in projected.iter() if node.get('data-plus-replaces') for value in node.get('data-plus-keeps','').split()}
   if new_targets!=original_targets-{entry['cancelled_target'] for entry in cancelled} or (new_targets and new_protected!=original_protected):raise ValueError('SAM projection changed scope beyond explicit protected-delete cancellations')
   operations.append({'operation':'coalesce duplicate draft-deletion requests and explicitly cancel protected deletions; no undeclared deletion scope','duplicates':duplicates,'declared_targets':sorted(original_targets),'effective_targets':sorted(new_targets),'cancelled_targets':[entry['cancelled_target'] for entry in cancelled],'protected_objects':sorted(original_protected),'no_images_or_visible_nodes_deleted_by_projection':True})
   ET.register_namespace('','http://www.w3.org/2000/svg');ET.register_namespace('xlink','http://www.w3.org/1999/xlink');fixed=ET.tostring(projected,encoding='unicode')
  if alias_operations:
   ET.register_namespace('','http://www.w3.org/2000/svg');ET.register_namespace('xlink','http://www.w3.org/1999/xlink');fixed=ET.tostring(projected,encoding='unicode')
  if not operations:raise ValueError('valid SVG has no supported structural metadata repair')
  after=ET.fromstring(fixed)
  if len(list(root.iter()))!=len(list(after.iter())):raise ValueError('SVG node count changed')
  for index,(before_node,after_node) in enumerate(zip(root.iter(),after.iter())):
   allowed={'data-plus-keeps','data-plus-replaces'}|({'{http://www.w3.org/1999/xlink}href'} if index in alias_nodes else set())
   if before_node.tag!=after_node.tag or before_node.text!=after_node.text or before_node.tail!=after_node.tail or {k:v for k,v in before_node.attrib.items() if k not in allowed}!={k:v for k,v in after_node.attrib.items() if k not in allowed}:raise ValueError('visual content changed during keep-reference projection')
  return text[:match.start()]+fixed+text[match.end():],operations
 stack=[];chunks=[];last=0;operations=[]
 pattern=r'<!--.*?-->|<!\[CDATA\[.*?\]\]>|<\?.*?\?>|</?[A-Za-z_][^>]*>'
 for token in re.finditer(pattern,svg,re.S):
  tag=token.group();chunks.append(svg[last:token.start()]);last=token.end()
  if tag.startswith(('<!--','<![CDATA[','<?')):chunks.append(tag);continue
  name=re.match(r'</?([A-Za-z_][\w.:-]*)',tag).group(1)
  if tag.startswith('</'):
   if name not in stack:raise ValueError('foreign XML closing tag; no content removal allowed')
   while stack[-1]!=name:
    missing=stack.pop();chunks.append('</'+missing+'>');operations.append({'insert_before_offset':match.start()+token.start(),'inserted':'</'+missing+'>','reason':'close already-open descendant before explicit ancestor close'})
   stack.pop()
  elif not tag.rstrip().endswith('/>'):stack.append(name)
  chunks.append(tag)
 chunks.append(svg[last:])
 if stack or not operations or len(operations)>4:raise ValueError('not a bounded local missing-close error')
 fixed=''.join(chunks);ET.fromstring(fixed)
 return text[:match.start()]+fixed+text[match.end():],operations

def canonical_named_space(text):
 # HTML's named NBSP is unambiguous U+00A0, but is not a predefined XML entity.
 positions=[m.start() for m in re.finditer('&nbsp;',text)]
 return text.replace('&nbsp;','\u00a0'),([{'operation':'standard named NBSP character reference becomes identical Unicode U+00A0 for XML; no ordinary-space substitution or word/content edit','source_offsets':positions,'original_entity':'&nbsp;','unicode_codepoints':['U+00A0']}] if positions else [])

def compile_reply(text,native_parse):
 """Use actual frozen-parser IDs before interpreting any keep/delete declaration."""
 text,grammar=canonical_named_space(text)
 try:canonical,parser_proof=native_parse(text)
 except ValueError as error:
  if 'xml.etree.ElementTree.ParseError:' not in str(error):raise
  text,close_grammar=repair(text);grammar+=close_grammar;canonical,parser_proof=native_parse(text)
 try:fixed,metadata=repair(canonical)
 except ValueError as error:
  if str(error)!='valid SVG has no supported structural metadata repair' or not grammar:raise
  fixed,metadata=canonical,[]
 return fixed,grammar+[{'operation':'source-bound frozen native parser supplies stable generic IDs before metadata scope checks; no geometry/style/text edit','native_parser_proof':parser_proof}]+metadata

def recover(first_folder,config):
 first_folder=Path(first_folder);spec=r.read(first_folder/'spec.json');responses=list((first_folder/'api').glob('*-response.json'))
 if len(responses)!=1:raise ValueError('one preserved original provider response required')
 raw=r.read(responses[0])['raw'];text,tools,_=api.extract(raw,'responses')
 if tools:raise ValueError('cannot syntax-recover tool output')
 def native_parse(source_text):
  document=Path(config['native_source_root'])/'src/figfox_plus/native/document.py'
  code="import sys;sys.path.insert(0,sys.argv[1]);from figfox_plus.native.document import parse,serialize;sys.stdout.write(serialize(parse(sys.stdin.read())))"
  result=subprocess.run([config['native_python'],'-I','-B','-c',code,str(Path(config['native_source_root'])/'src')],input=source_text,text=True,capture_output=True,env=api.clean_env(),timeout=30)
  if result.returncode:raise ValueError('frozen native SVG parse rejected: '+result.stderr)
  return result.stdout,{'native_document_file':str(document),'native_document_sha256':r.sha(document),'input_text_sha256':__import__('hashlib').sha256(source_text.encode()).hexdigest(),'native_parsed_svg_sha256':__import__('hashlib').sha256(result.stdout.encode()).hexdigest(),'zero_http':True}
 fixed,operations=compile_reply(text,native_parse);out=first_folder.parent/'first-structural-forks'/__import__('hashlib').sha256(fixed.encode()).hexdigest()[:16]
 if out.exists():
  proof=r.read(out/'syntax-recovery.json')
  if proof['provider_response_sha256']!=r.sha(responses[0]) or not (out/'result.json').exists():raise ValueError('inspect preserved incomplete syntax fork')
  return r.read(out/'result.json')
 out.mkdir(parents=True);spec={**spec,'output_root':str(out)};r.write(out/'spec.json',spec);(out/'repaired-model-output.txt').write_text(fixed)
 request=r.read(next((first_folder/'api').glob('*-request.json')))['body'];oldparts=request['input'][0]['content'] if 'input' in request else request['messages'][0]['content'];oldtext=next(x['text'] for x in oldparts if x['type'] in ('input_text','text'));oldimages=[x for x in oldparts if x['type'] in ('input_image','image_url')]
 stderr=(out/'native-stderr.log').open('w');p=subprocess.Popen([config['native_python'],'-B',api.__file__,'--first-child',str(out/'spec.json')],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=stderr,text=True,env=api.clean_env());calls=0
 try:
  for line in p.stdout:
   if not line.startswith('LIVE_CALLBACK:'):continue
   calls+=1;payload=json.loads(line.split(':',1)[1]);actual=api.inventory(payload['images']);parts=[x['content'] for x in actual]
   if calls!=1 or payload['prompt'].replace(str(out),str(first_folder))!=oldtext:raise ValueError('native initial prompt changed outside explicit output path relocation')
   # Provider Responses uses input_image; compare encoded data, not local file names.
   def url(x):return x.get('image_url') if isinstance(x.get('image_url'),str) else x.get('image_url',{}).get('url')
   if [url(x) for x in parts]!=[url(x) for x in oldimages]:raise ValueError('initial evidence images changed')
   p.stdin.write(json.dumps({'text':fixed})+'\n');p.stdin.flush()
  if p.wait()!=0 or calls!=1:raise ValueError('native syntax-fork generation failed; original and fork preserved')
 except BaseException:p.kill();p.wait();raise
 finally:p.stdin.close();p.stdout.close();stderr.close()
 runtime_sha=r.sha(__file__);runtime_archive=first_folder.parents[2]/'source-snapshots'/runtime_sha/Path(__file__).name;runtime_archive.parent.mkdir(parents=True,exist_ok=True)
 if runtime_archive.exists():
  if r.sha(runtime_archive)!=runtime_sha:raise ValueError('recovery source archive changed')
 else:
  import tempfile,os
  with tempfile.NamedTemporaryFile(dir=runtime_archive.parent,delete=False) as stream:stream.write(Path(__file__).read_bytes());temp=stream.name
  os.replace(temp,runtime_archive)
 r.write(out/'syntax-recovery.json',{'format':'initial-structural-recovery-v2','original_folder':str(first_folder),'provider_response_file':str(responses[0]),'provider_response_sha256':r.sha(responses[0]),'repaired_model_output_sha256':r.sha(out/'repaired-model-output.txt'),'operations':operations,'all_original_visible_content_and_geometry_preserved':True,'recovery_runtime_sha256':runtime_sha,'recovery_source_archive':str(runtime_archive),'source_prompt_and_images_verified':True,'provider_calls_added':0,'native_pipeline_rerender_only':True})
 return r.read(out/'result.json')


def close_redundant_asset_aliases(first,config,saved):
 """Resolve only byte-proven duplicate SAM aliases by replaying native locally."""
 import base64,hashlib
 scene=Path(first['stage0_scene']);root=ET.parse(scene).getroot();aliases=[]
 for node in root.iter():
  value=node.get('{http://www.w3.org/1999/xlink}href');active=node.get('href','')
  if value and not value.startswith(('#','data:')):
   if not re.fullmatch(r'asset_sam_region_[0-9]+',value) or not active.startswith('data:image/png;base64,'):raise ValueError('unclosed image alias is not an exact embedded SAM asset')
   aliases.append((node.get('id'),value,active))
 if not aliases:return first
 catalog=r.read(first['sam_neutral']);assets={x['id']:x for x in catalog['assets']}
 for node,ident,data in aliases:
  if ident not in assets or r.sha(assets[ident]['path'])!=assets[ident]['sha256'] or hashlib.sha256(base64.b64decode(data.split(',',1)[1],validate=True)).hexdigest()!=assets[ident]['sha256']:raise ValueError('duplicate alias image bytes do not match actual SAM catalog')
 folder=scene.parents[2];original_receipt=folder/'result.json';fixed=recover(folder,config);new_scene=Path(fixed['stage0_scene'])
 # Renderer output must be identical; no visual edit is authorized by this migration.
 before_png=scene.parent/'preview.png';after_png=new_scene.parent/'preview.png'
 if not before_png.exists() or not after_png.exists() or r.sha(before_png)!=r.sha(after_png):raise ValueError('inactive alias removal changed native rendered pixels')
 proof={'format':'duplicate-sam-alias-initial-migration-v1','original_first_receipt':str(original_receipt),'original_first_receipt_sha256':r.sha(original_receipt),'effective_first_receipt':str(new_scene.parents[2]/'result.json'),'effective_first_receipt_sha256':r.sha(new_scene.parents[2]/'result.json'),'original_svg_sha256':r.sha(scene),'effective_svg_sha256':r.sha(new_scene),'identical_native_png_sha256':r.sha(before_png),'source_image_sha256':r.sha(first['original']),'duplicate_aliases':[(node,ident) for node,ident,_ in aliases],'zero_http':True,'original_artifacts_unchanged':True}
 history=Path(saved).parent/'first-reference-migrations';history.mkdir(exist_ok=True)
 archive=history/(r.sha(saved)+'-original-result.json')
 if not archive.exists():r.write(archive,r.read(saved))
 r.write(history/(proof['effective_svg_sha256']+'.json'),proof);r.write(saved,fixed)
 return fixed
