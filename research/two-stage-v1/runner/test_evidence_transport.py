import unittest,json
import live_api as api
class ExactEvidenceTests(unittest.TestCase):
 def test_repeated_large_measurements_are_shared_and_roundtrip_exact(self):
  shared={'coordinates':list(range(2000)),'judgment':'unknown'}
  documents=[{'rcd':[{'measurement':shared},{'measurement':shared}]},{'candidate':{'rcd':[{'measurement':shared},{'measurement':shared}]}}]
  encoded,table=api.exact_json_views(documents)
  def expand(value):
   if isinstance(value,dict):
    if list(value)==['$figfox_exact_json_ref']:return expand(table[value['$figfox_exact_json_ref']])
    return {k:expand(v) for k,v in value.items()}
   return [expand(v) for v in value] if isinstance(value,list) else value
  self.assertEqual([expand(x) for x in encoded],documents)
  self.assertLess(len(json.dumps([encoded,table])),len(json.dumps(documents))//2)
 def test_reserved_ref_collision_fails_closed(self):
  with self.assertRaises(api.AdmissionError):api.exact_json_views([{'$figfox_exact_json_ref':'source-value'}])

 def test_repeated_long_strings_are_exact_shared_values(self):
  text='measurement-path/'*2000
  views,table=api.exact_json_views([{'one':text,'two':text}])
  self.assertEqual(table[views[0]['one']['$figfox_exact_json_ref']],text)
  self.assertEqual(views[0]['one'],views[0]['two'])
 def test_json_field_aliases_expand_to_exact_original_keys(self):
  original=[{'long_repeated_measurement_key':i,'unchanged':i} for i in range(40)]
  views,keys=api.exact_json_key_views(original)
  def expand(v):
   if isinstance(v,dict):return {keys.get(k,k):expand(x) for k,x in v.items()}
   return [expand(x) for x in v] if isinstance(v,list) else v
  self.assertEqual(expand(views),original)
  self.assertLess(len(json.dumps([views,keys])),len(json.dumps(original)))
 def test_native_execution_traces_stay_closed_optional_not_mandatory(self):
  import tempfile
  from pathlib import Path
  with tempfile.TemporaryDirectory() as tmp:
   root=Path(tmp)/'round-1';root.mkdir();(root/'plan.json').write_text('{"operations":[]}');(root/'candidate.json').write_text('{"revision":"actual"}');trace=root/'native/program-0001/report.json';trace.parent.mkdir(parents=True);trace.write_text('{"internal_measurements":[1,2,3]}')
   messages,manifest,catalog=api.build_role_packet('Allowed current stage inputs: '+str(root))
   self.assertIn(str(root/'plan.json'),manifest['required_files']);self.assertIn(str(root/'candidate.json'),manifest['required_files'])
   self.assertNotIn(str(trace),manifest['required_files']);self.assertIn(str(trace),catalog)
   answer,_=api.read_evidence(catalog,{'action':'read','file':str(trace),'pointer':'/internal_measurements'})
   self.assertEqual(answer['value'],[1,2,3])
 def test_long_evidence_paths_use_lossless_prefix_aliases(self):
  prefix='/native/measurement/objects/'+'long-evidence-prefix/'*8
  original=[{'path':prefix+str(i)+'/geometry_bbox','sha':'different-'+str(i)} for i in range(100)]
  views,prefixes=api.exact_string_prefix_views(original)
  def expand(value):
   if isinstance(value,str):
    for key,prefix in prefixes.items():
     if value.startswith(key):return prefix+value[len(key):]
    return value
   if isinstance(value,dict):return {k:expand(v) for k,v in value.items()}
   return [expand(v) for v in value] if isinstance(value,list) else value
  self.assertEqual(expand(views),original)
  self.assertLess(len(json.dumps([views,prefixes])),len(json.dumps(original))//2)
 def test_pointer_index_delta_list_roundtrips_order_and_every_path(self):
  original=['/rcd/0/measurement/objects/node-'+str(i//4)+'/geometry/'+str(i%4) for i in range(1000)]
  encoded=api.exact_path_list_views(original)
  self.assertIn('$figfox_exact_path_deltas',encoded)
  previous='';decoded=[]
  for common,suffix in encoded['$figfox_exact_path_deltas']:
   previous=previous[:common]+suffix;decoded.append(previous)
  self.assertEqual(decoded,original)
  self.assertLess(len(json.dumps(encoded)),len(json.dumps(original))//2)
 def test_repeated_absolute_root_in_text_is_reversible(self):
  root='/Users/example/work/output/'+('long/'*30)
  original=[{'type':'text','text':'Allowed input: '+root+'candidate.json\nRequired '+root+'frame.png'}]
  encoded,notice=api.exact_text_root_views(original,root)
  self.assertTrue(notice)
  self.assertEqual(encoded[0]['text'].replace('~FIGFOX_ROOT~/',root),original[0]['text'])
 def test_pointer_trie_retains_every_path_in_original_order(self):
  original=['/rcd/'+str(i)+'/measurement/objects/actual-geometry-evidence/'+key for i in range(200) for key in ['bbox/left','bbox/top','bbox/right','bbox/bottom']]
  encoded=api.exact_path_trie_views(original)
  self.assertIn('$figfox_exact_path_trie',encoded)
  result=[]
  def walk(node,prefix):
   for segment,child in node.items():
    if segment=='\0':result.append('/'+'/'.join(prefix))
    else:walk(child,prefix+[segment])
  walk(encoded['$figfox_exact_path_trie'],[])
  self.assertEqual(result,original)
  self.assertLess(len(json.dumps(encoded)),len(json.dumps(original)))
 def test_root_alias_avoids_marker_already_present_in_authoritative_source(self):
  import re
  root='/Users/example/work/output/'+('long/'*30)
  original=[{'type':'text','text':'Source literal ~FIGFOX_ROOT~/ must stay literal. Evidence '+root+'current.svg'}]
  encoded,notice=api.exact_text_root_views(original,root)
  marker=re.search(r'replace literal (.*?) with ',notice['text']).group(1)
  self.assertNotEqual(marker,'~FIGFOX_ROOT~/')
  self.assertEqual(encoded[0]['text'].replace(marker,root),original[0]['text'])
 def test_large_xml_attribute_templates_reconstruct_exact_bytes(self):
  text='<svg>\n'+''.join('<path fill="rgb(12,34,56)" stroke="rgb(12,34,56)" stroke-width="1" opacity="1" d="M 1 2 L 3 4 Z" id="node-'+str(i)+'"/>' for i in range(2000))+'\n</svg>'
  view=api.exact_xml_view(text)
  restored=''
  for segment in view['segments']:
   if isinstance(segment,str):restored+=segment
   else:
    key,values=segment;parts=view['templates'][key]
    restored+=''.join(part+(values[i] if i<len(values) else '') for i,part in enumerate(parts))
  self.assertEqual(restored,text)
  self.assertLess(len(json.dumps(view)),len(text))
 def test_xml_value_atoms_preserve_attribute_strings_across_documents(self):
  xml='<svg>'+''.join('<path fill="rgb(12,34,56)" stroke="rgb(12,34,56)" d="M 10 20 L 30 40 Z"/>' for _ in range(500))+'</svg>'
  originals=[api.exact_xml_view(xml),api.exact_xml_view(xml)]
  encoded=api.exact_xml_atom_views(originals)
  import copy
  decoded=copy.deepcopy(encoded)
  for view in decoded:
   table=view.pop('attribute_value_atoms')
   for segment in view['segments']:
    if isinstance(segment,list):segment[1][:]=[table[v] if type(v)is int else v for v in segment[1]]
  self.assertEqual(decoded,originals)
 def test_xml_column_runs_keep_every_attribute_and_tag_order(self):
  xml='<svg>'+''.join('<path fill="red" stroke="red" opacity="1" d="M '+str(i)+' 0 L 3 4"/>' for i in range(1000))+'</svg>'
  original=api.exact_xml_view(xml)
  encoded=api.exact_xml_column_views([original])[0]
  segments=[]
  for segment in encoded['segments']:
   if isinstance(segment,str):segments.append(segment);continue
   key,run=segment;columns=[]
   for column in run['columns']:
    if isinstance(column,dict):column=[value for count,value in column['rle'] for _ in range(count)]
    columns.append(column)
   for i in range(run['rows']):segments.append([key,[column[i] for column in columns]])
  self.assertEqual(segments,original['segments'])
  self.assertLess(len(json.dumps(encoded)),len(json.dumps(original)))
 def test_verifier_rejects_detector_schema_without_rewriting_quality(self):
  with self.assertRaises(ValueError):api.validate_verifier_output({'issues':[],'programs':[]})
  report={'resolved_ids':[],'unresolved_ids':['still-broken'],'not_required':[],'new_required_findings':[],'new_uncertain_findings':[],'protected_regressions':['regression']}
  self.assertIsNone(api.validate_verifier_output(report))
  self.assertEqual(report['unresolved_ids'],['still-broken']);self.assertEqual(report['protected_regressions'],['regression'])
