import unittest,tempfile,json,uuid
from pathlib import Path
from decimal import Decimal
import budget
class ConditionCaps(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.path=self.root/'ledger.json';self.path.write_text(json.dumps({'cap_peak_usd':1,'requests':{}}));self.run=str(uuid.uuid4())
  self.c={'ledger_path':str(self.path),'expected_cap_usd':1,'sample_cap_usd':1,'condition_caps_usd':{'C':.0003},'providers':{'p':{'input_usd_per_million':1,'output_usd_per_million':2,'cache_usd_per_million':.1,'max_input_tokens':1000,'max_output_tokens':100,'context_tokens':2000,'price_provenance':'test'}}};self.body={'messages':[{'role':'user','content':'hi'}],'max_tokens':100}
 def tearDown(self):self.tmp.cleanup()
 def test_condition_limit_shared_across_images_and_retries(self):
  a=budget.reserve_block(self.c,self.run,[{'sample_id':'a','cell':'C','provider':'p'}],self.root/'a');self.assertEqual(budget.inspect_budget(self.path,1)['total_exposure_upper_usd'],0)
  a.send('p','a/C/first/TURN0',self.body,lambda _:{'usage':{'prompt_tokens':2,'completion_tokens':80}});a.close()
  b=budget.reserve_block(self.c,self.run,[{'sample_id':'b','cell':'C','provider':'p'}],self.root/'b')
  with self.assertRaises(budget.ConditionBudgetExceeded):b.send('p','b/C/first/TURN0',self.body,lambda _:self.fail('group cap bypassed'))
  self.assertEqual(budget.inspect_budget(self.path,1)['known_cost_usd'],Decimal('.000162'))
 def test_live_other_request_can_proceed_but_expired_unknown_blocks(self):
  self.c['condition_caps_usd']['C']=.01
  a=budget.reserve_block(self.c,self.run,[{'sample_id':'a','cell':'C','provider':'p'}],self.root/'a');b=budget.reserve_block(self.c,self.run,[{'sample_id':'b','cell':'C','provider':'p'}],self.root/'b')
  def nested(rid):
   b.send('p','b/C/first/TURN0',self.body,lambda _:{'usage':{'prompt_tokens':2,'completion_tokens':1}})
   return {'usage':{'prompt_tokens':2,'completion_tokens':1}}
  a.send('p','a/C/first/TURN0',self.body,nested)
  self.assertEqual(budget.inspect_budget(self.path,1)['known_cost_usd'],Decimal('.000008'))
if __name__=='__main__':unittest.main()
