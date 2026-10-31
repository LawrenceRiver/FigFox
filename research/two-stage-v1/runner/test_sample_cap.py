"""Hard sample caps must prevent HTTP, including across conditions and resume."""
import json,tempfile,unittest,uuid
from pathlib import Path
from decimal import Decimal
import budget
class SampleCapTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.ledger=self.root/'ledger.json';self.ledger.write_text(json.dumps({'cap_peak_usd':1,'requests':{}}))
  self.c={'ledger_path':str(self.ledger),'expected_cap_usd':1,'sample_cap_usd':0.0003,'providers':{'p':{'input_usd_per_million':1,'output_usd_per_million':2,'cache_usd_per_million':.1,'max_input_tokens':1000,'max_output_tokens':100,'context_tokens':2000,'price_provenance':'synthetic rates'}}}
  self.rows=[{'sample_id':'a','cell':str(i),'provider':'p'} for i in range(4)];self.run=str(uuid.uuid4());self.folder=self.root/'run';self.body={'messages':[{'role':'user','content':'hi'}],'max_tokens':100}
 def tearDown(self):self.tmp.cleanup()
 def test_only_sample_envelope_reserved(self):
  lease=budget.reserve_block(self.c,self.run,self.rows,self.folder)
  self.assertEqual(budget.inspect_budget(self.ledger,1)['total_exposure_upper_usd'],Decimal('.0003'))
  lease.close();self.assertEqual(budget.inspect_budget(self.ledger,1)['total_exposure_upper_usd'],0)
 def test_cross_cell_cap_blocks_before_http_and_is_not_raised_on_resume(self):
  lease=budget.reserve_block(self.c,self.run,self.rows,self.folder);calls=[]
  def send(rid):calls.append(rid);return {'usage':{'prompt_tokens':2,'completion_tokens':80}}
  lease.send('p','a/0/first/TURN0',self.body,send)
  resumed=budget.reserve_block(self.c,self.run,self.rows,self.folder)
  with self.assertRaises(budget.SampleBudgetExceeded):resumed.send('p','a/1/first/TURN0',self.body,send)
  self.assertEqual(len(calls),1)
  resumed.close();self.assertEqual(budget.inspect_budget(self.ledger,1)['known_cost_usd'],Decimal('.000162'))
 def test_unresolved_attempt_keeps_reservation_and_never_retries(self):
  lease=budget.reserve_block(self.c,self.run,self.rows,self.folder)
  def fail(rid):raise RuntimeError('uncertain transport')
  with self.assertRaises(RuntimeError):lease.send('p','a/0/first/TURN0',self.body,fail)
  lease.close();s=budget.inspect_budget(self.ledger,1);self.assertTrue(s['blocked']);self.assertGreater(s['unknown_reserved_upper_usd'],0)
  with self.assertRaises(budget.UnknownAttempt):lease.send('p','a/0/first/TURN0',self.body,lambda _:self.fail('must not resend'))
 def test_closed_envelope_cannot_be_reopened(self):
  lease=budget.reserve_block(self.c,self.run,self.rows,self.folder);lease.close()
  resumed=budget.reserve_block(self.c,self.run,self.rows,self.folder)
  with self.assertRaises(budget.BudgetError):resumed.send('p','a/0/first/TURN0',self.body,lambda _:self.fail('released slot sent'))
  self.assertEqual(budget.inspect_budget(self.ledger,1)['total_exposure_upper_usd'],0)
 def test_recovery_keeps_prior_cost_inside_same_sample_cap(self):
  lease=budget.reserve_block(self.c,self.run,self.rows,self.folder)
  lease.send('p','a/0/first/TURN0',self.body,lambda _: {'usage':{'prompt_tokens':2,'completion_tokens':80}});lease.close()
  recovered=budget.reserve_recovery(self.c,self.run,self.rows,self.root/'recovery','repair1')
  with self.assertRaises(budget.SampleBudgetExceeded):recovered.send('p','a/0/repair1/first/TURN0',self.body,lambda _:self.fail('sample cap reset'))
  self.assertEqual(budget.inspect_budget(self.ledger,1)['total_exposure_upper_usd'],Decimal('.0003'))
  recovered.close();self.assertEqual(budget.inspect_budget(self.ledger,1)['known_cost_usd'],Decimal('.000162'))
if __name__=='__main__':unittest.main()
