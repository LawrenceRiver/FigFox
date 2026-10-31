import copy,json,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
try:
 from figfox_score.measurements import measure_local_image, compare_chart
except ImportError:
 measure_local_image=compare_chart=None
from figfox_score.engine import evaluate,validate_input
ROOT=Path(__file__).resolve().parents[1]

def image_case():
 return dict(unit_id='photo',asset_id='native-1',identity_evidence=dict(source='human',verified=True,refs=['synthetic known identity']),reference_file='reference.png',candidate_file='candidate.png',reference_region=[2,3,8,8],candidate_region=[12,13,8,8],transform=dict(scale=1,translation=[10,10],allow_translation=True,allow_uniform_scale=True))
def chart_case():
 data=dict(axes=dict(x=dict(scale='linear',unit='s'),y=dict(scale='linear',unit='m')),series=[dict(id='s1',semantic_id='distance',legend_key='Distance',points=[dict(id='p0',x=0,y=1),dict(id='p1',x=1,y=2)])])
 return dict(unit_id='chart',evidence=dict(source='human',verified=True,refs=['synthetic data attestation']),reference=copy.deepcopy(data),candidate=copy.deepcopy(data),series_matches=[dict(ref='s1',candidate='s1',point_matches=[dict(ref='p0',candidate='p0'),dict(ref='p1',candidate='p1')])],tolerances=dict(x_abs=0,y_abs=0.01))
class MeasurementTests(unittest.TestCase):
 def setUp(self):self.assertIsNotNone(measure_local_image,'measurement module missing')
 def test_disabled(self):self.assertEqual(measure_local_image(image_case(),Path('.'),False)['state'],'disabled')
 def test_missing_dependency(self):
  with patch('figfox_score.measurements.load_image_module',side_effect=ImportError):
   self.assertEqual(measure_local_image(image_case(),Path('.'),True)['reason'],'optional_dependency_Pillow_missing')
 def test_png_translation_and_change(self):
  try:from PIL import Image
  except ImportError:self.skipTest('optional Pillow absent')
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);r=Image.new('RGB',(30,30),'white');tile=Image.new('RGB',(8,8),(20,80,130));r.paste(tile,(2,3));r.save(p/'reference.png');c=Image.new('RGB',(40,40),'black');c.paste(tile,(12,13));c.save(p/'candidate.png')
   a=image_case();out=measure_local_image(a,p,True);self.assertEqual(out['mse'],0);self.assertEqual(out['mae'],0)
   a['candidate_file']='reference.png';a['candidate_region']=[2,3,8,8];a['transform']['translation']=[0,0];self.assertEqual(measure_local_image(a,p,True)['mse'],out['mse'])
   c.putpixel((14,15),(255,0,0));c.save(p/'candidate.png');self.assertGreater(measure_local_image(image_case(),p,True)['mse'],0)
 def test_invalid_regions(self):
  a=image_case();a['reference_region']=[-1,3,8,8]
  with self.assertRaises(ValueError):measure_local_image(a,Path('.'),True)
 def test_nonuniform_rejected(self):
  a=image_case();a['candidate_region'][3]=9
  with self.assertRaises(ValueError):measure_local_image(a,Path('.'),True)
 def test_out_of_bounds(self):
  try:from PIL import Image
  except ImportError:self.skipTest('optional Pillow absent')
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);Image.new('RGB',(4,4)).save(p/'reference.png');Image.new('RGB',(40,40)).save(p/'candidate.png')
   with self.assertRaises(ValueError):measure_local_image(image_case(),p,True)
 def test_uniform_scale(self):
  try:from PIL import Image
  except ImportError:self.skipTest('optional Pillow absent')
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);Image.new('RGB',(30,30),(20,80,130)).save(p/'reference.png');Image.new('RGB',(60,60),(20,80,130)).save(p/'candidate.png')
   a=image_case();a['candidate_region']=[4,6,16,16];a['transform'].update(scale=2,translation=[0,0]);self.assertEqual(measure_local_image(a,p,True)['mse'],0)
 def test_jpeg_supported(self):
  try:from PIL import Image
  except ImportError:self.skipTest('optional Pillow absent')
  with tempfile.TemporaryDirectory() as tmp:
   p=Path(tmp);Image.new('RGB',(30,30),(20,80,130)).save(p/'same.jpg')
   a=image_case();a.update(reference_file='same.jpg',candidate_file='same.jpg',candidate_region=[2,3,8,8]);a['transform']['translation']=[0,0]
   self.assertEqual(measure_local_image(a,p,True)['mae'],0)
 def test_nonfinite_tolerance_rejected(self):
  a=chart_case();a['tolerances']['y_abs']=float('nan')
  with self.assertRaises(ValueError):compare_chart(a)
 def test_unmapped_points_unknown(self):
  a=chart_case();a['series_matches'][0]['point_matches'].pop();self.assertEqual(compare_chart(a)['data_status'],'unknown')
 def test_duplicate_mapping_rejected(self):
  a=chart_case();a['series_matches'].append(copy.deepcopy(a['series_matches'][0]))
  with self.assertRaises(ValueError):compare_chart(a)
 def test_identity_unverified_image(self):
  a=image_case();a['identity_evidence']['verified']=False;self.assertEqual(measure_local_image(a,Path('.'),True)['reason'],'asset_identity_not_verified')
 def test_transform_permission(self):
  a=image_case();a['transform']['allow_translation']=False
  with self.assertRaises(ValueError):measure_local_image(a,Path('.'),True)
 def test_hidden_search_parameter_rejected(self):
  d=json.loads((ROOT/'examples/input.json').read_text());d['applicability']['D17']=dict(state='applicable',reason='native material',units=[dict(id='photo',ref_ids=[],critical=False)]);a=image_case();a['search_best_roi']=True;d['local_images']=dict(enabled=True,comparisons=[a])
  with self.assertRaises(ValueError):validate_input(d)
 def test_explicit_tolerance_boundary(self):
  a=chart_case();a['candidate']['series'][0]['points'][0]['y']=1.01;self.assertEqual(compare_chart(a)['data_status'],'pass')
 def test_chart_equal(self):self.assertEqual(compare_chart(chart_case())['data_status'],'pass')
 def test_chart_value(self):
  a=chart_case();a['candidate']['series'][0]['points'][1]['y']=2.1;self.assertEqual(compare_chart(a)['data_status'],'fail')
 def test_chart_scale_and_unit(self):
  for key,value in [('scale','log10'),('unit','mm')]:
   a=chart_case();a['candidate']['axes']['y'][key]=value;self.assertEqual(compare_chart(a)['data_status'],'fail')
 def test_chart_series_identity(self):
  a=chart_case();a['candidate']['series'][0]['semantic_id']='other';self.assertEqual(compare_chart(a)['data_status'],'fail')
 def test_chart_legend(self):
  a=chart_case();a['candidate']['series'][0]['legend_key']='Other';self.assertEqual(compare_chart(a)['data_status'],'fail')
 def test_chart_missing_data(self):
  a=chart_case();a['candidate']=None;self.assertEqual(compare_chart(a)['data_status'],'unknown')
 def test_chart_unverified(self):
  a=chart_case();a['evidence']['verified']=False;self.assertEqual(compare_chart(a)['data_status'],'unknown')
 def test_chart_does_not_pass_visual(self):
  d=json.loads((ROOT/'examples/input.json').read_text());d['applicability']['D18']=dict(state='applicable',reason='synthetic chart',units=[dict(id='chart',ref_ids=[],critical=True)]);d['chart_checks']=[chart_case()]
  self.assertEqual(next(x for x in evaluate(d,ROOT/'examples')['items'] if x['item_id']=='D18')['status'],'unknown')
 def test_chart_error_integrated(self):
  d=json.loads((ROOT/'examples/input.json').read_text());d['applicability']['D18']=dict(state='applicable',reason='synthetic chart',units=[dict(id='chart',ref_ids=[],critical=True)]);a=chart_case();a['candidate']['axes']['y']['unit']='mm';d['chart_checks']=[a]
  self.assertEqual(evaluate(d,ROOT/'examples')['usability'],'unusable')
if __name__=='__main__':unittest.main()
