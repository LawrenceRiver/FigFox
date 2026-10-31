import unittest
from planner_packet_transport import encode,decode
class PacketTransportTests(unittest.TestCase):
 def test_exact_float_null_missing_nested_and_list_order(self):
  document={'objects':{str(i):{'geometry_bbox':{'left':1.23456789012345,'right':5,'top':0,'bottom':3},'world':[1,0,0,1,0,0],'flag':True,'text':None,'effects':[]} for i in range(8)},'other':[None,False,0,{},[]]}
  view=encode(document);self.assertEqual(decode(view),document)
 def test_reserved_markers_fail_closed(self):
  with self.assertRaises(ValueError):encode({'$pt':[1,2]})
 def test_repeated_prose_lines_preserve_every_character(self):
  from planner_packet_transport import encode_lines,decode_lines
  line='A complete native safety and quality requirement must remain unchanged.\n'
  document={'instructions':line+'unique suffix','cards':[line,line.rstrip('\n')],'natural_marker':'~PL0~'}
  self.assertEqual(decode_lines(encode_lines(document)),document)
 def test_composed_planner_wire_roundtrip_all_fields(self):
  import json,re
  import two_stage_runner as runner
  from planner_packet_transport import decode_lines
  prefix='/Users/example/Desktop/figfox-debug/output/a-long-controlled-experiment/sample-0001/S0C1/cell/'
  line='All actual source, native capability, crop completeness and acceptance guards must remain unchanged.\n'
  document={'native_execution_evidence':{'source_files':{'svg':{'path':prefix+'runs/run1/checkpoint/current.svg'}}},'rows':[{'repeated_instructions':line,'absolute_path':prefix+'inputs/original.png','measurement':[1.23456789012345,False,None]} for _ in range(12)]}
  wire=runner.planner_wire(document)
  if wire.startswith('LOSSLESS ABSOLUTE-PATH ALIAS:'):
   notice,wire=wire.split('\n',1);match=re.search(r'replace literal (.*?) with (.*?) before interpreting',notice);self.assertIsNotNone(match);wire=wire.replace(match[1],match[2])
  value=json.loads(wire)
  if value.get('format')=='lossless-planner-packet-v2':
   def keys(v):
    if isinstance(v,dict):return {value['key_aliases'].get(k,k):keys(x) for k,x in v.items()}
    return [keys(x) for x in v] if isinstance(v,list) else v
   packet,shared=keys(value['packet']),keys(value['shared_values'])
   def expand(v):
    if isinstance(v,dict):
     if set(v)=={'$r'}:return expand(shared[v['$r']])
     return {k:expand(x) for k,x in v.items()}
    return [expand(x) for x in v] if isinstance(v,list) else v
   packet=expand(packet);aliases=value['absolute_path_aliases']
  elif value.get('format')=='lossless-path-prefix-packet-v1':packet=value['packet'];aliases=value['absolute_path_aliases']
  else:packet=value;aliases={}
  def paths(v):
   if isinstance(v,str):
    for marker,prefix in aliases.items():
     if v.startswith(marker):return prefix+v[len(marker):]
    return v
   if isinstance(v,dict):return {k:paths(x) for k,x in v.items()}
   return [paths(x) for x in v] if isinstance(v,list) else v
  packet=paths(packet)
  if packet.get('format')=='lossless-field-templates-v1':packet=decode(packet)
  if packet.get('format')=='lossless-line-aliases-v1':packet=decode_lines(packet)
  self.assertEqual(packet,document)
 def test_shared_native_instruction_blocks_roundtrip_exactly(self):
  from planner_packet_transport import encode_shared_lines,decode_shared_lines
  shared='Shared quality rules.\nNever invent a pass.\n\n```json\n{"actual":true}\n```\n'
  planner='Planner header\n'+shared+'Planner footer\n'
  semantic='Semantic header\n'+shared+'Semantic-specific duties without final newline'
  view=encode_shared_lines(semantic,planner)
  self.assertEqual(decode_shared_lines(view,planner),semantic)
  self.assertIn('Semantic-specific duties',str(view))
 def test_short_reference_table_reconstructs_nested_shared_values(self):
  from planner_packet_transport import compact_refs,expand_refs
  key='$figfox_exact_json_ref'
  shared={'a':{'nested':{key:'b'}},'b':[1.234567890123,False,None]}
  original={'first':{key:'a'},'second':{key:'b'}}
  packet,table=compact_refs(original,shared)
  self.assertEqual(expand_refs(packet,table),{'first':{'nested':shared['b']},'second':shared['b']})
 def test_public_decoder_recovers_actual_controller_body(self):
  import two_stage_runner as runner
  from planner_packet_transport import decode_wire
  document={'format':'example-original','rows':[{'long_attribute_field':'Repeated original evidence and native immutable data.','number':1.23456789012} for _ in range(20)]}
  self.assertEqual(decode_wire(runner.planner_wire(document)),document)
