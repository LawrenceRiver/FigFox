import unittest,copy
import joint_detector_adapter as adapter
class JointAdapterTests(unittest.TestCase):
 def test_empty_defaults_and_role_routing_keep_all_quality_judgments(self):
  finding={'id':'a','category':'A','decision':'confirmed','description':'actual model finding'}
  main={'issues':[finding],'programs':[],'revision':'r','evidence_hashes':{},'examined_regions':['F'],'unresolved_regions':[]}
  semantic={**main,'issues':[]};semantic.pop('programs');original={'main':main,'semantic':semantic};before=copy.deepcopy(original)
  result,audit=adapter.normalize(original,{'proposals':[]})
  self.assertEqual(original,before);self.assertEqual(result['main']['issues'],[]);self.assertEqual(result['semantic']['issues'],[finding]);self.assertEqual(result['semantic']['programs'],[]);self.assertEqual(result['semantic']['proposal_reviews'],[])
  self.assertEqual(result['semantic']['issues'][0]['decision'],'confirmed');self.assertTrue(audit)
 def test_nonempty_proposals_cannot_invent_missing_reviews(self):
  report={'main':{'issues':[],'programs':[]},'semantic':{'issues':[],'programs':[]}}
  with self.assertRaises(ValueError):adapter.normalize(report,{'proposals':[{'id':'P1'}]})
 def test_unambiguous_native_id_spelling_only_preserves_quality(self):
  row={'id':'finding','category':'F','decision':'uncertain','target_ids':['plus_node74'],'neighbor_ids':[],'description':'same actual model concern'}
  reports={'main':{'issues':[row],'programs':[]},'semantic':{'issues':[],'programs':[]}}
  result,audit=adapter.normalize(reports,None,{'plus_node_74'})
  self.assertEqual(result['main']['issues'][0]['target_ids'],['plus_node_74']);self.assertEqual(result['main']['issues'][0]['decision'],'uncertain');self.assertEqual(row['target_ids'],['plus_node74'])
  with self.assertRaises(ValueError):adapter.normalize(reports,None,{'a-different-object'})
 def test_actual_supplement_can_add_reviews_but_not_erase_old_findings(self):
  finding={'id':'x','decision':'confirmed','category':'A'}
  original={'issues':[finding],'revision':'r','programs':[]}
  supplemental={**original,'proposal_reviews':[{'proposal_id':'P','decision':'qualified'}]}
  self.assertIsNone(adapter.validate_supplement(original,supplemental))
  with self.assertRaises(ValueError):adapter.validate_supplement(original,{**supplemental,'issues':[]})
 def test_explicit_no_finding_review_maps_only_to_native_enum(self):
  review={'proposal_id':'p','decision':'no_finding','issue_ids':[],'source_evidence':'source clear','current_evidence':'current clear','necessity_reason':'no defect observed'}
  reports={'main':{'issues':[],'programs':[]},'semantic':{'issues':[],'programs':[],'proposal_reviews':[review]}}
  result,audit=adapter.normalize(reports,{'proposals':[{'id':'p'}]})
  self.assertEqual(result['semantic']['proposal_reviews'][0]['decision'],'qualified');self.assertEqual(review['decision'],'no_finding');self.assertTrue(audit)
  reports['semantic']['proposal_reviews'][0]['issue_ids']=['a-real-finding']
  with self.assertRaises(ValueError):adapter.normalize(reports,{'proposals':[{'id':'p'}]})
 def test_review_alias_reject_preserves_actual_no_finding_evidence(self):
  review={'proposal_id':'p','decision':'reject','issue_ids':[],'source_evidence':'same intended overlap','current_evidence':'source-consistent overlap','necessity_reason':'no repair justified'}
  reports={'main':{'issues':[],'programs':[]},'semantic':{'issues':[],'programs':[],'proposal_reviews':[review]}}
  result,_=adapter.normalize(reports,{'proposals':[{'id':'p'}]})
  self.assertEqual(result['semantic']['proposal_reviews'][0]['decision'],'qualified');self.assertEqual(review['decision'],'reject')
 def test_confirmed_joint_main_link_routes_same_finding_to_semantic(self):
  finding={'id':'m','category':'F','decision':'confirmed','description':'actual source finding','target_ids':['shape']}
  review={'proposal_id':'p','decision':'confirmed','issue_ids':['main:m'],'source_evidence':'source','current_evidence':'current','necessity_reason':'already captured by actual main finding'}
  reports={'main':{'issues':[finding],'programs':[]},'semantic':{'issues':[],'programs':[],'proposal_reviews':[review]}}
  result,_=adapter.normalize(reports,{'proposals':[{'id':'p'}]})
  self.assertEqual(result['main']['issues'],[]);self.assertEqual(result['semantic']['issues'],[finding]);self.assertEqual(result['semantic']['proposal_reviews'][0]['issue_ids'],['m']);self.assertEqual(result['semantic']['proposal_reviews'][0]['decision'],'required');self.assertEqual(review['decision'],'confirmed')
 def test_explicit_readonly_spelling_alias_never_grants_target_authority(self):
  finding={'id':'x','category':'A','decision':'confirmed','target_ids':['web'],'neighbor_ids':['currupted_projector_right'],'description':'actual model observation'}
  reports={'main':{'issues':[],'programs':[]},'semantic':{'issues':[finding],'programs':[]}}
  aliases={'currupted_projector_right':'corrupted_projector_right'}
  result,_=adapter.normalize(reports,None,{'web','corrupted_projector_right'},readonly_aliases=aliases)
  self.assertEqual(result['semantic']['issues'][0]['target_ids'],['web']);self.assertEqual(result['semantic']['issues'][0]['neighbor_ids'],['corrupted_projector_right']);self.assertEqual(finding['neighbor_ids'],['currupted_projector_right'])
  reports['semantic']['issues'][0]['target_ids']=['currupted_projector_right']
  with self.assertRaises(ValueError):adapter.normalize(reports,None,{'web','corrupted_projector_right'},readonly_aliases=aliases)

 def test_actual_top_level_review_wrapper_is_moved_without_new_judgments(self):
  value={'main':{'issues':[],'programs':[]},'semantic':{'issues':[],'programs':[]},'proposal_reviews':[]}
  result,audit=adapter.normalize(value,{'proposals':[]});self.assertEqual(result['semantic']['proposal_reviews'],[]);self.assertNotIn('proposal_reviews',value['semantic']);self.assertTrue(audit)
  value['semantic']['proposal_reviews']=[{'different':'actual report'}]
  with self.assertRaises(ValueError):adapter.normalize(value,{'proposals':[]})

 def test_nonexistent_readonly_neighbor_never_becomes_edit_authority(self):
  issue={'id':'real','category':'E','decision':'confirmed','target_ids':['actual'],'neighbor_ids':['ghost'],'description':'actual visual finding'};original={'main':{'issues':[issue],'programs':[]},'semantic':{'issues':[],'programs':[]}}
  result,audit=adapter.normalize(original,None,{'actual'});self.assertEqual(result['main']['issues'][0]['target_ids'],['actual']);self.assertEqual(result['main']['issues'][0]['neighbor_ids'],[]);self.assertEqual(issue['neighbor_ids'],['ghost']);self.assertEqual(result['main']['issues'][0]['decision'],'confirmed');self.assertTrue(audit)
  original['main']['issues'][0]['target_ids']=['ghost']
  with self.assertRaises(ValueError):adapter.normalize(original,None,{'actual'})
 def test_invalid_unresolved_confidence_can_only_remain_uncertain(self):
  issue={'id':'real','category':'S4','decision':'unresolved','description':'actual model finding'};report={'main':{'issues':[],'programs':[]},'semantic':{'issues':[issue],'programs':[]}}
  result,audit=adapter.normalize(report,None);self.assertEqual(result['semantic']['issues'][0]['decision'],'uncertain');self.assertEqual(issue['decision'],'unresolved');self.assertEqual(result['semantic']['issues'][0]['description'],issue['description']);self.assertTrue(audit)
 def test_invalid_target_subset_withheld_not_fuzzily_replaced_or_hidden(self):
  issue={'id':'real','category':'D','decision':'confirmed','target_ids':['actual','ghost'],'neighbor_ids':[],'description':'actual model finding'};value={'main':{'issues':[issue],'programs':[]},'semantic':{'issues':[],'programs':[]}}
  out,audit=adapter.normalize(value,None,{'actual'});finding=out['main']['issues'][0];self.assertEqual(finding['target_ids'],['actual']);self.assertEqual(finding['unresolved_target_references'],['ghost']);self.assertEqual(issue['target_ids'],['actual','ghost']);self.assertEqual(finding['decision'],'confirmed');self.assertTrue(audit)

 def test_raw_review_link_can_use_only_unique_exact_existing_joint_main_issue(self):
  finding={'id':'F-02','category':'F','decision':'confirmed','description':'actual model finding'};review={'proposal_id':'p','decision':'required','issue_ids':['F-02'],'source_evidence':'actual source','current_evidence':'actual current','necessity_reason':'actual necessity'};original={'main':{'issues':[finding],'programs':[]},'semantic':{'issues':[],'programs':[],'proposal_reviews':[review]}}
  result,audit=adapter.normalize(original,{'proposals':[{'id':'p'}]});self.assertEqual(result['main']['issues'],[]);self.assertEqual(result['semantic']['issues'],[finding]);self.assertEqual(result['semantic']['proposal_reviews'][0],review);self.assertEqual(original['main']['issues'],[finding]);self.assertTrue(audit)

class MissingReviewCorrectionTest(__import__('unittest').TestCase):
 def test_only_actual_missing_reviews_are_appended(self):
  import joint_detector_adapter as a
  prior={'proposal_reviews':[{'proposal_id':'P1','decision':'uncertain'}],'new_semantic_issues':[]}
  correction={'proposal_reviews':[{'proposal_id':'P2','decision':'qualified'}],'new_semantic_issues':[],'plan':{}}
  value=a.combine_missing_reviews(prior,correction,['P2'])
  self.assertEqual(value['proposal_reviews'],prior['proposal_reviews']+correction['proposal_reviews']);self.assertEqual(len(prior['proposal_reviews']),1)
  with self.assertRaises(ValueError):a.combine_missing_reviews(prior,correction,['P3'])

 def test_typo_uncertain_never_certifies_confirmation(self):
  import joint_detector_adapter as a
  source={'main':{'issues':[{'id':'real','category':'D','decision':'unecertain'}],'programs':[]},'semantic':{'issues':[],'programs':[]}}
  value,audit=a.normalize(source,None)
  self.assertEqual(value['main']['issues'][0]['decision'],'uncertain');self.assertEqual(source['main']['issues'][0]['decision'],'unecertain');self.assertTrue(audit)

 def test_null_reviews_only_empty_for_proven_empty_catalog(self):
  import joint_detector_adapter as a
  source={'main':{'issues':[],'programs':[]},'semantic':{'issues':[],'programs':[],'proposal_reviews':None}}
  value,_=a.normalize(source,{'proposals':[]});self.assertEqual(value['semantic']['proposal_reviews'],[])
  with self.assertRaises(ValueError):a.normalize(source,{'proposals':[{'id':'P'}]})

 def test_disabled_empty_review_wrapper_is_closed_not_generic_dict_cast(self):
  import joint_detector_adapter as a
  source={'main':{'issues':[],'programs':[]},'semantic':{'issues':[],'programs':[],'proposal_reviews':{'mode':'disabled_by_assignment','proposal_reviews':[]}}}
  value,_=a.normalize(source,{'proposals':[]});self.assertEqual(value['semantic']['proposal_reviews'],[])
  with self.assertRaises(ValueError):a.normalize(source,{'proposals':[{'id':'actual'}]})
  for wrapper in ({},{'mode':'disabled_by_assignment'}):
   source['semantic']['proposal_reviews']=wrapper;value,_=a.normalize(source,{'proposals':[]});self.assertEqual(value['semantic']['proposal_reviews'],[])
  source['semantic']['proposal_reviews']={'mode':'disabled_by_assignment','evidence':'nonempty actual report'}
  with self.assertRaises(ValueError):a.normalize(source,{'proposals':[]})

 def test_qualified_issue_is_not_promoted_or_silently_dropped(self):
  import joint_detector_adapter as a
  source={'main':{'issues':[],'programs':[]},'semantic':{'issues':[{'id':'actual','category':'B','decision':'qualified','current_evidence':'legible as measured'}],'programs':[]}}
  value,_=a.normalize(source,None)
  self.assertEqual(value['semantic']['issues'][0]['decision'],'uncertain');self.assertEqual(value['semantic']['issues'][0]['current_evidence'],'legible as measured');self.assertEqual(source['semantic']['issues'][0]['decision'],'qualified')

class ActualModelLocalizationTest(unittest.TestCase):
 def test_only_new_actual_second_stage_bindings_can_localize_unbound_finding(self):
  original={'main':{'issues':[{'id':'m','category':'D','decision':'confirmed','target_ids':['missing'],'neighbor_ids':['face'],'description':'actual defect','original_evidence':'actual source evidence','current_evidence':'actual visual evidence'}]},'semantic':{'issues':[]}}
  binding={'role':'main','issue_id':'m','target_ids':['arrow-real'],'neighbor_ids':['face'],'container_id':'panel','evidence':'actual second model identifies the path into this face'}
  value,ops=adapter.apply_actual_model_bindings(original,[binding],{'arrow-real','face','panel'})
  self.assertEqual(value['main']['issues'][0]['target_ids'],['arrow-real']);self.assertEqual(value['main']['issues'][0]['decision'],'confirmed');self.assertEqual(original['main']['issues'][0]['target_ids'],['missing']);self.assertTrue(ops)
  for bad in [{**binding,'decision':'qualified'},{**binding,'target_ids':['invented']},{**binding,'issue_id':'other'}]:
   with self.assertRaises(ValueError):adapter.apply_actual_model_bindings(original,[bad],{'arrow-real','face','panel'})
  with self.assertRaises(ValueError):adapter.apply_actual_model_bindings(original,[],{'arrow-real','face','panel'})

class EmptyDetectorProgramWrapperTest(unittest.TestCase):
 def test_only_empty_non_executable_wrapper_is_omitted(self):
  raw={'main':{'issues':[],'programs':[]},'semantic':{'issues':[],'programs':[]},'programs':[]}
  value,ops=adapter.normalize(raw,None);self.assertEqual(set(value),{'main','semantic'});self.assertIn('programs',raw);self.assertTrue(ops)
  with self.assertRaises(ValueError):adapter.normalize({**raw,'programs':[{'id':'actual-program'}]},None)

class ExactReviewRolePrefixTest(unittest.TestCase):
 def test_wrong_role_prefix_can_only_bind_one_exact_reported_id(self):
  issue={'id':'actual-main-id','category':'F','decision':'confirmed','description':'actual model defect'}
  review={'proposal_id':'P','decision':'required','issue_ids':['semantic:actual-main-id'],'source_evidence':'source','current_evidence':'current','necessity_reason':'actual necessity'}
  raw={'main':{'issues':[issue],'programs':[]},'semantic':{'issues':[],'programs':[],'proposal_reviews':[review]}}
  value,ops=adapter.normalize(raw,{'proposals':[{'id':'P'}]});self.assertEqual(value['semantic']['issues'],[issue]);self.assertEqual(value['semantic']['proposal_reviews'][0]['issue_ids'],['actual-main-id']);self.assertEqual(raw['semantic']['proposal_reviews'][0]['issue_ids'],['semantic:actual-main-id']);self.assertTrue(ops)
  raw['semantic']['proposal_reviews'][0]['issue_ids']=['semantic:guessed-id']
  with self.assertRaises(ValueError):adapter.normalize(raw,{'proposals':[{'id':'P'}]})

class LiteralColonSourceIDTest(unittest.TestCase):
 def test_actual_semantic_raw_id_with_colon_is_not_stripped(self):
  finding={'id':'semantic:new-uncertain','category':'F','decision':'uncertain'};review={'proposal_id':'p','decision':'uncertain','issue_ids':['semantic:new-uncertain'],'source_evidence':'source','current_evidence':'current','necessity_reason':'unknown'}
  raw={'main':{'issues':[],'programs':[]},'semantic':{'issues':[finding],'programs':[],'proposal_reviews':[review]}}
  value,ops=adapter.normalize(raw,{'proposals':[{'id':'p'}]});self.assertEqual(value['semantic']['proposal_reviews'][0]['issue_ids'],['semantic:new-uncertain']);self.assertEqual(value['semantic']['issues'],[finding]);self.assertTrue(ops)

class DuplicateAttentionFootprintTest(unittest.TestCase):
 def test_only_exact_duplicate_attention_scope_reuses_real_existing_uncertainty(self):
  issue={'id':'u','category':'F','decision':'uncertain','target_ids':['fit','formula']};review=lambda ident,links:{'proposal_id':ident,'decision':'uncertain','issue_ids':links,'source_evidence':'actual source','current_evidence':'actual current','necessity_reason':'actual ambiguity'}
  raw={'main':{'issues':[],'programs':[]},'semantic':{'issues':[issue],'programs':[],'proposal_reviews':[review('p1',['u']),review('p2',[])]}}
  p={'target_ids':['fit','formula'],'bbox':[1,2,3,4],'evidence':{'revision':'R','evidence_hashes':{'current_svg':'H'}}};catalog={'proposals':[{'id':'p1',**p},{'id':'p2',**copy.deepcopy(p)}]}
  value,ops=adapter.normalize(raw,catalog);self.assertEqual(value['semantic']['proposal_reviews'][1]['issue_ids'],['u']);self.assertEqual(raw['semantic']['proposal_reviews'][1]['issue_ids'],[]);self.assertEqual(value['semantic']['issues'],[issue]);self.assertTrue(ops)
  catalog['proposals'][1]['bbox']=[2,2,3,4];value,_=adapter.normalize(raw,catalog);self.assertEqual(value['semantic']['proposal_reviews'][1]['issue_ids'],[])

class ActualCombinedEvidenceSlotTest(unittest.TestCase):
 def test_missing_fields_quote_real_model_narratives_not_host_visual_facts(self):
  raw={'main':{'issues':[{'id':'m','decision':'confirmed','category':'B','description':'Current glyph is displaced compared with reference, which has a tight pair.'}]},'semantic':{'issues':[]}}
  binding={'role':'main','issue_id':'m','target_ids':['real'],'neighbor_ids':[],'evidence':'Current SVG real contains the displayed glyph; the reference pair is tight.'}
  value,ops=adapter.apply_actual_model_bindings(raw,[binding],{'real'});finding=value['main']['issues'][0]
  self.assertEqual(finding['original_evidence'],raw['main']['issues'][0]['description']);self.assertEqual(finding['current_evidence'],binding['evidence']);self.assertEqual(finding['decision'],'confirmed');self.assertNotIn('original_evidence',raw['main']['issues'][0]);self.assertTrue(ops)
  raw['main']['issues'][0]['description']='generic complaint with no observed view'
  with self.assertRaises(ValueError):adapter.apply_actual_model_bindings(raw,[binding],{'real'})

class DuplicateReviewWrapperTest(unittest.TestCase):
 def test_same_judgments_preserve_both_actual_evidence_texts(self):
  r={'proposal_id':'p','decision':'qualified','issue_ids':[],'source_evidence':'original source','current_evidence':'original current','necessity_reason':'original reason'}
  other={**r,'source_evidence':'second source'}
  x={'main':{'issues':[]},'semantic':{'issues':[],'proposal_reviews':[r]},'proposal_reviews':[other]};before=copy.deepcopy(x)
  result,audit=adapter.normalize(x,None)
  self.assertIn('original source',result['semantic']['proposal_reviews'][0]['source_evidence']);self.assertIn('second source',result['semantic']['proposal_reviews'][0]['source_evidence']);self.assertEqual(x,before)
  x['proposal_reviews'][0]['decision']='uncertain'
  with self.assertRaises(ValueError):adapter.normalize(x,None)

class EmptySemanticExtraTest(unittest.TestCase):
 def test_only_literal_empty_unrequested_extra_is_omittable(self):
  x={'main':{'issues':[]},'semantic':{'issues':[]},'semantic_extra':{}}
  result,audit=adapter.normalize(x,None);self.assertTrue(audit);self.assertEqual(x['semantic_extra'],{})
  x['semantic_extra']={'issues':[{'id':'real'}]}
  with self.assertRaises(ValueError):adapter.normalize(x,None)

class DisabledReviewNoteTest(unittest.TestCase):
 def test_proven_empty_disabled_review_wrapper_retains_note_in_audit(self):
  wrapper={'mode':'disabled_by_assignment','reviewed':[],'note':'observer-assignment disabled; no proposals supplied'}
  x={'main':{'issues':[]},'semantic':{'issues':[],'proposal_reviews':wrapper}}
  result,audit=adapter.normalize(x,{'proposals':[]});self.assertEqual(result['semantic']['proposal_reviews'],[]);self.assertTrue(any(op.get('original_model_wrapper')==wrapper for op in audit))
  with self.assertRaises(ValueError):adapter.normalize(x,{'proposals':[{'id':'p'}]})
  x['semantic']['proposal_reviews']['reviewed']=[{'id':'real'}]
  with self.assertRaises(ValueError):adapter.normalize(x,{'proposals':[]})
