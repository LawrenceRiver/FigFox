import unittest,tempfile,json
from pathlib import Path
import bounded_trace as trace
class TraceTests(unittest.TestCase):
 def test_names_and_usage_count_reasoning_once(self):
  self.assertEqual(trace.name(1,'sample-0076','B43'),'第001张图-sample-0076-B43')
  with self.assertRaises(ValueError):trace.name(1,'sample-0076','B44')
  pc={'input_usd_per_million':.3,'cache_usd_per_million':.006,'output_usd_per_million':1.2}
  stats=trace.usage({'usage':{'prompt_tokens':10000,'completion_tokens':1000,'prompt_cache_hit_tokens':2000,'completion_tokens_details':{'reasoning_tokens':900}}},pc)
  self.assertEqual(stats['input_tokens'],10000);self.assertEqual(stats['output_tokens'],1000)
  self.assertAlmostEqual(stats['estimated_usd'],.003612)
 def test_receipt_does_not_replay_unknown_or_changed_input(self):
  with tempfile.TemporaryDirectory() as tmp:
   path=Path(tmp)/'stage.json';path.write_text(json.dumps({'status':'request_started','body_sha256':'a'}))
   with self.assertRaises(ValueError):trace.cached(path,'a')
   path.write_text(json.dumps({'status':'completed','body_sha256':'a','response_file':'missing','response_sha256':'x'}))
   with self.assertRaises(ValueError):trace.cached(path,'b')
 def test_semantic_projection_keeps_proposals_not_empty_catalog_dumps(self):
  import two_stage_runner as runner
  document={'format':'test','revision':'real','evidence_hashes':{'x':'h'},'proposals':[{'id':'P1','evidence':'keep this exact record'}],'artifacts':{'large_internal_index':'unneeded'},'config':{'implementation_dump':'unneeded'}}
  view=runner.semantic_view(document)
  self.assertEqual(view['proposals'],document['proposals']);self.assertEqual(view['evidence_hashes'],document['evidence_hashes'])
  self.assertNotIn('artifacts',view);self.assertNotIn('config',view)
 def test_trailing_closing_brace_is_grammar_only_not_a_second_report(self):
  value,audit=trace.parse_model_object('{"unresolved_ids":["still-broken"]}}')
  self.assertEqual(value,{'unresolved_ids':['still-broken']});self.assertTrue(audit)
  for text in ['{"x":1}{"x":2}','{"x":1,"x":2}','{"x":NaN}']:
   with self.assertRaises(ValueError):trace.parse_model_object(text)

class RecoveryNamingTest(unittest.TestCase):
 def test_recovery_has_distinct_visible_stage_identity(self):
  import bounded_trace
  self.assertEqual(bounded_trace.name(3,'sample-0001','B13-R1'),'第003张图-sample-0001-B13-R1')
  with self.assertRaises(ValueError):bounded_trace.name(3,'sample-0001','B13-R0')
 def test_review_planner_system_schema_requires_wrapper_not_plain_plan(self):
  import two_stage_runner as runner
  message=runner.output_contract({'snapshot':{'revision':'r','evidence_hashes':{}}},'review_planner')['content']
  self.assertTrue(message.startswith('Return EXACTLY one top-level object with keys proposal_reviews, new_semantic_issues, plan.'))
  self.assertNotIn('Return one planner JSON object',message)

 def test_missing_final_outer_delimiter_only_is_grammar_not_new_content(self):
  value,audit=trace.parse_model_object('{"plan":{"programs":[],"unresolved_ids":["actual"]}')
  self.assertEqual(value,{'plan':{'programs':[],'unresolved_ids':['actual']}});self.assertEqual(audit['characters'],'}')
  for raw in ['{"text":"unfinished','{"x":','{"x":1,','{"x":[1,']:
   with self.assertRaises(ValueError):trace.parse_model_object(raw)
 def test_written_key_missing_only_opening_quote_preserves_value(self):
  value,audit=trace.parse_model_object('{"issues":[{"id":"actual",image_id_placeholder_removed":null}]}')
  self.assertEqual(value,{'issues':[{'id':'actual','image_id_placeholder_removed':None}]});self.assertEqual(audit['insertions'][0]['existing_key'],'image_id_placeholder_removed')

 def test_identical_duplicates_coalesce_but_conflicts_and_types_do_not(self):
  value,audit=trace.parse_model_object('{"source_sha256":"actual","source_sha256":"actual","unresolved_ids":["real"]}')
  self.assertEqual(value['unresolved_ids'],['real']);self.assertTrue(audit['duplicates'])
  for raw in ['{"x":1,"x":true}','{"x":1,"x":1.0}','{"x":"a","x":"b"}']:
   with self.assertRaises(ValueError):trace.parse_model_object(raw)
 def test_missing_object_close_before_existing_array_end_preserves_all_values(self):
  raw='{"unresolved_reasons":[{"issue_id":"real","reason":"actual model explanation"],"programs":[]}'
  value,audit=trace.parse_model_object(raw);self.assertEqual(value,{'unresolved_reasons':[{'issue_id':'real','reason':'actual model explanation'}],'programs':[]});self.assertEqual(audit['insertions'][0]['characters'],'}')

 def test_control_marker_recovery_requires_actual_invalid_reply(self):
  raw=lambda content:{'choices':[{'message':{'content':content}}]}
  self.assertTrue(trace.verify_malformed_control_reply(raw('{"reason":"unfinished<｜end▁of▁thinking｜>{"programs":[]}')))
  for content in ['{"programs":[]}','{"reason":"literal <｜end▁of▁thinking｜> value","programs":[]}']:
   with self.assertRaises(ValueError):trace.verify_malformed_control_reply(raw(content))

 def test_missing_array_close_before_explicit_native_field_preserves_program(self):
  raw='{"programs":[{"source_code":"actual code"},"unresolved_reasons":[{"issue_id":"u","reason":"still unclear"}]}'
  value,audit=trace.parse_model_object(raw)
  self.assertEqual(value['programs'],[{'source_code':'actual code'}]);self.assertEqual(value['unresolved_reasons'][0]['reason'],'still unclear');self.assertEqual(audit['insertions'][0]['characters'],']')

 def test_python_unicode_escape_remains_literal_code_after_json_syntax_repair(self):
  raw=r'''{"source_code":"s='\U0001F300'","unresolved_ids":["u"]}'''
  value,ops=trace.parse_model_object(raw)
  self.assertEqual(value['source_code'],r"s='\U0001F300'");self.assertEqual(value['unresolved_ids'],['u']);self.assertEqual(ops['insertions'][0]['characters'],'\\')
  valid,_=trace.parse_model_object(r'{"source_code":"line1\nline2"}')
  self.assertEqual(valid['source_code'],'line1\nline2')

 def test_premature_root_close_retains_all_later_quality_fields(self):
  raw='{"resolved_ids":[],"unresolved_ids":["old"]},"new_required_findings":[],"new_uncertain_findings":[{"id":"real-new-unknown"}],"protected_regressions":[]}'
  value,ops=trace.parse_model_object(raw)
  self.assertEqual(value['unresolved_ids'],['old']);self.assertEqual(value['new_uncertain_findings'],[{'id':'real-new-unknown'}]);self.assertEqual(ops['deletions'][0]['characters'],'}')
  with self.assertRaises(ValueError):trace.parse_model_object('{"resolved_ids":[]},{"resolved_ids":["different"]}')

 def test_mandatory_verifier_correction_cannot_retry_a_valid_report(self):
  value={key:[] for key in ['resolved_ids','unresolved_ids','not_required','new_required_findings','new_uncertain_findings']};raw=lambda x:{'choices':[{'message':{'content':json.dumps(x)}}]}
  self.assertEqual(trace.verify_invalid_verifier_reply(raw(value),['protected_regressions']),value)
  with self.assertRaises(ValueError):trace.verify_invalid_verifier_reply(raw({**value,'protected_regressions':[]}),['protected_regressions'])
  with self.assertRaises(ValueError):trace.verify_invalid_verifier_reply(raw(value),['different-field'])

 def test_missing_machine_hash_quote_does_not_rewrite_hash_or_quality_text(self):
  raw='{"evidence_hashes":{"sam_catalog":"'+'a'*64+'},"unresolved_ids":["real"]}'
  value,ops=trace.parse_model_object(raw);self.assertEqual(value['evidence_hashes']['sam_catalog'],'a'*64);self.assertEqual(value['unresolved_ids'],['real']);self.assertEqual(ops['insertions'][0]['characters'],'"')
  literal={'current_evidence':'"sam_catalog":"'+'a'*64+'}'};value,none=trace.parse_model_object(json.dumps(literal));self.assertEqual(value,literal);self.assertIsNone(none)
