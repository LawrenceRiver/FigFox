import unittest
from initial_syntax_recovery import repair
class SyntaxTest(unittest.TestCase):
 def test_only_missing_close_is_inserted_no_visual_content_added(self):
  raw='prefix <svg><text id="x"><tspan dy="-7">actual text</text></svg> suffix';fixed,ops=repair(raw)
  self.assertEqual(fixed,'prefix <svg><text id="x"><tspan dy="-7">actual text</tspan></text></svg> suffix');self.assertEqual(len(ops),1)
  for invalid in ['<svg><text>truncated','<svg></foreign></svg>','<svg><text>x</text></svg>']:
   with self.assertRaises(ValueError):repair(invalid)

 def test_nonexistent_keep_only_reference_removal_cannot_change_real_keeps(self):
  raw='<svg><g id="replacement" data-plus-keeps="real missing" data-plus-replaces="draft"/><rect id="draft" x="4"/><text id="real">keep me</text></svg>'
  fixed,ops=repair(raw)
  self.assertEqual(fixed,raw.replace('real missing','real'));self.assertEqual(ops[0]['removed_nonexistent_ids'],['missing']);self.assertIn('keep me',fixed);self.assertIn('data-plus-replaces="draft"',fixed)

 def test_duplicate_sam_deletion_coalesces_only_deletion_not_assets_or_keeps(self):
  import xml.etree.ElementTree as E
  raw='<svg><g id="draft"><rect id="old"/></g><g id="s1" data-plus-replaces="draft" data-plus-keeps="text"><image id="i1"/></g><g id="s2" data-plus-replaces="draft" data-plus-keeps="arrow"><image id="i2"/></g><text id="text">visible</text><path id="arrow"/></svg>'
  fixed,ops=repair(raw);nodes={x.get('id'):x for x in E.fromstring(fixed).iter() if x.get('id')}
  self.assertEqual(nodes['s1'].get('data-plus-replaces'),'draft');self.assertIsNone(nodes['s2'].get('data-plus-replaces'));self.assertEqual(set(nodes['s1'].get('data-plus-keeps').split()),{'text','arrow'});self.assertEqual({x for x in nodes if x.startswith('i')},{'i1','i2'});self.assertEqual(nodes['text'].text,'visible');self.assertTrue(ops)
 def test_protected_object_can_never_be_deleted_by_conflicting_sam_request(self):
  import xml.etree.ElementTree as E
  raw='<svg><g id="draft"><rect id="kept"/></g><path id="safe"/><g id="s1" data-plus-replaces="draft"><image id="i1"/></g><g id="s2" data-plus-replaces="safe" data-plus-keeps="kept"><image id="i2"/></g></svg>'
  fixed,ops=repair(raw);nodes={x.get('id'):x for x in E.fromstring(fixed).iter() if x.get('id')};self.assertIsNone(nodes['s1'].get('data-plus-replaces'));self.assertEqual(nodes['s2'].get('data-plus-replaces'),'safe');self.assertIn('kept',nodes);self.assertIn('draft',nodes);self.assertIn('i1',nodes);self.assertIn('i2',nodes);self.assertTrue(any('cancel' in x['operation'] for x in ops))
 def test_scope_checks_use_native_assigned_ids_not_only_raw_model_ids(self):
  from initial_syntax_recovery import compile_reply
  import xml.etree.ElementTree as E
  raw='<svg><g id="draft"><rect/></g><g id="r1" data-plus-replaces="draft" data-plus-keeps="plus_node_0"><image id="img"/></g></svg>'
  canonical=raw.replace('<rect/>','<rect id="plus_node_0"/>')
  fixed,ops=compile_reply(raw,lambda text:(canonical,{'frozen_native_fixture':'adds stable generic ID only'}));nodes={x.get('id'):x for x in E.fromstring(fixed).iter() if x.get('id')};self.assertIn('plus_node_0',nodes);self.assertIsNone(nodes['r1'].get('data-plus-replaces'));self.assertIn('plus_node_0',nodes['r1'].get('data-plus-keeps'));self.assertTrue(ops)

class DuplicateAssetAliasTest(__import__('unittest').TestCase):
 def test_only_byte_identical_sam_alias_is_removed_and_geometry_stays(self):
  import initial_syntax_recovery as m,xml.etree.ElementTree as E
  raw='<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"><image id="i" href="asset_sam_region_000041" xlink:href="asset_sam_region_000041" x="42" width="120"/></svg>'
  value,ops=m.repair(raw);node=list(E.fromstring(value))[0]
  self.assertEqual(node.get('href'),'asset_sam_region_000041');self.assertEqual(node.get('x'),'42');self.assertNotIn('{http://www.w3.org/1999/xlink}href',node.attrib);self.assertTrue(ops)
  with self.assertRaises(ValueError):m.repair(raw.replace('xlink:href="asset_sam_region_000041"','xlink:href="asset_sam_region_000042"'))

class NamedSpaceXMLTest(__import__('unittest').TestCase):
 def test_nbsp_keeps_exact_nonbreaking_character_not_ascii_space(self):
  import initial_syntax_recovery as m,xml.etree.ElementTree as E
  raw='<svg><text id="t">Phase 1&nbsp; training &amp; validation</text></svg>'
  def parse(text):return E.tostring(E.fromstring(text),encoding='unicode'),{'native_fixture':True}
  value,ops=m.compile_reply(raw,parse)
  self.assertEqual(E.fromstring(value)[0].text,'Phase 1\u00a0 training & validation');self.assertIn('&nbsp;',raw);self.assertTrue(ops)
  fixed,none=m.canonical_named_space('&amp;nbsp; &unknown;');self.assertEqual(fixed,'&amp;nbsp; &unknown;');self.assertEqual(none,[])
