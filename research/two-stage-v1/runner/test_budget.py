import copy
import fcntl
import json
from pathlib import Path
import tempfile
import threading
import unittest
import uuid
from budget import *

class FinanceTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        self.path=self.root/'accounting.json'; self.path.write_text(json.dumps({'cap_peak_usd':15,'requests':{},'extra':{'keep':[1,'x']}}))
        self.config={'ledger_path':str(self.path),'expected_cap_usd':15,'lock_timeout':.1,'providers':{'p':{'input_usd_per_million':1,'output_usd_per_million':2,'cache_usd_per_million':.1,'max_input_tokens':1000,'max_output_tokens':100,'context_tokens':2000,'price_provenance':'test rates only'}}}
        self.rows=[{'sample_id':'a','cell':str(i),'provider':'p'} for i in range(4)]
        self.body={'messages':[{'role':'user','content':'hello'}],'max_tokens':100}
        self.run=str(uuid.uuid4()); self.dir=self.root/'run'
    def tearDown(self): self.tmp.cleanup()
    def reserve(self): return reserve_block(self.config,self.run,self.rows,self.dir)
    def test_whole_block_and_release(self):
        l=self.reserve(); d=json.loads(self.path.read_text()); self.assertEqual(len(d['requests']),148)
        self.assertEqual(plan_budget_summary(self.config,self.rows)['slot_count'],148)
        self.assertEqual(plan_budget_summary(self.config,self.rows)['max_reserved_usd'],Decimal('.1776'))
        self.assertEqual(d['extra'],{'keep':[1,'x']}); self.assertTrue(all(r['status']=='reserved' for r in d['requests'].values()))
        self.assertEqual(inspect_budget(self.path,15)['charged_usd'],Decimal('.1776'))
        l.close(); self.assertEqual(inspect_budget(self.path,15)['charged_usd'],0)
    def test_cache_exact_and_idempotent(self):
        l=self.reserve(); calls=[]
        def send(rid): calls.append(rid); return {'usage':{'prompt_tokens':10,'completion_tokens':5},'choices':[]}
        for _ in range(2): l.send('p','a/0/first/TURN0',self.body,send)
        self.assertEqual(len(calls),1)
        changed={**self.body,'messages':[{'role':'user','content':'different'}]}
        with self.assertRaises(BudgetError): l.send('p','a/0/first/TURN0',changed,send)
        l.close(); self.assertEqual(inspect_budget(self.path,15)['charged_usd'],Decimal('.00002'))
    def test_crash_unknown_never_resend(self):
        l=self.reserve()
        def fail(rid): raise RuntimeError('transport crash')
        with self.assertRaises(RuntimeError): l.send('p','a/0/first/TURN0',self.body,fail)
        l.close(); self.assertTrue(inspect_budget(self.path,15)['blocked'])
        with self.assertRaises(UnknownAttempt): l.send('p','a/0/first/TURN0',self.body,lambda _:self.fail('resent'))
        self.assertEqual(inspect_budget(self.path,15)['charged_usd'],Decimal('.0012'))
    def test_provider_fractional_fields_remain_json_serializable_on_replay(self):
        lease=self.reserve();calls=[]
        response={'usage':{'input_tokens':10,'output_tokens':5},'temperature':0.7,'top_p':0.95,'output':[]}
        def send(rid):calls.append(rid);return response
        for _ in range(2):
            returned=lease.send('p','a/0/first/TURN0',self.body,send)
            self.assertEqual(json.loads(json.dumps(returned)),response)
        self.assertEqual(len(calls),1)
        self.assertEqual(inspect_budget(self.path,15)['known_cost_usd'],Decimal('.00002'))
    def test_raw_crash_recovery(self):
        l=self.reserve(); original=l._cost
        l._cost=lambda *a: (_ for _ in ()).throw(RuntimeError('crash after raw'))
        with self.assertRaises(RuntimeError): l.send('p','a/0/first/TURN0',self.body,lambda _:{'usage':{'prompt_tokens':2,'completion_tokens':1}})
        l._cost=original
        l.send('p','a/0/first/TURN0',self.body,lambda _:self.fail('resent'))
        self.assertFalse(inspect_budget(self.path,15)['blocked'])
    def test_missing_usage_and_overrun(self):
        l=self.reserve()
        with self.assertRaises(UnknownAttempt): l.send('p','a/0/first/TURN0',self.body,lambda _: {})
        self.assertTrue(inspect_budget(self.path,15)['blocked'])
    def test_overrun_recorded(self):
        l=self.reserve()
        with self.assertRaises(OverflowCostError): l.send('p','a/0/first/TURN0',self.body,lambda _:{'usage':{'prompt_tokens':100000,'completion_tokens':1}})
        self.assertTrue(inspect_budget(self.path,15)['blocked'])
        self.assertEqual(json.loads(self.path.read_text())['requests'][l.slots[0]['request_id']]['cost_usd'],.100002)
    def test_cap_malformed_unknown(self):
        with self.assertRaises(BudgetError): inspect_budget(self.path,16)
        d=json.loads(self.path.read_text()); d['requests']['old']={'status':'bounded_unknown','reserve_usd':1,'upper_bound_usd':2,'extra':True}; self.path.write_text(json.dumps(d))
        self.assertEqual(inspect_budget(self.path,15)['charged_usd'],2)
        d['requests']['old']['status']='unknown_cost'; self.path.write_text(json.dumps(d))
        with self.assertRaises(BudgetError): self.reserve()
        d['requests']['old']['reserve_usd']=float('nan'); self.path.write_text(json.dumps(d))
        with self.assertRaises(BudgetError): inspect_budget(self.path,15)
    def test_known_expense_distinct_from_unknown_upper(self):
        d=json.loads(self.path.read_text()); d['requests']={
            'paid':{'status':'finished','cost_usd':7.300775448,'reserve_usd':8},
            'lost':{'status':'unknown_cost','cost_usd':None,'reserve_usd':1,'upper_bound_usd':2.3482368}}
        self.path.write_text(json.dumps(d)); before=self.path.read_bytes(); summary=inspect_budget(self.path,15)
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(summary['known_cost_usd'],Decimal('7.300775448'))
        self.assertEqual(summary['unknown_reserved_upper_usd'],Decimal('2.3482368'))
        self.assertEqual(summary['total_exposure_upper_usd'],Decimal('9.649012248'))
        self.assertEqual(summary['available_usd'],Decimal('5.350987752'))
        self.assertEqual(summary['status_counts'],{'finished':1,'unknown_cost':1})
        self.assertEqual(summary['blocked_reasons'],{'unknown_cost_request_requires_receipt_reconciliation':1})
        self.assertEqual(summary['charged_usd_semantics'],'legacy_exposure_alias_not_actual_expense')
    def test_shortage_atomic(self):
        self.config['providers']['p']['input_usd_per_million']=1000
        with self.assertRaisesRegex(BudgetError,'required_first_block'): self.reserve()
        self.assertEqual(json.loads(self.path.read_text())['requests'],{})
    def test_lock_aliases(self):
        for name in ('accounting.lock','accounting.json.lock'):
            with (self.root/name).open('a') as f:
                fcntl.flock(f,fcntl.LOCK_EX)
                with self.assertRaisesRegex(BudgetError,'lock timeout'): self.reserve()
    def test_concurrent_reservation(self):
        barrier=threading.Barrier(2); errors=[]
        def work():
            try: barrier.wait(); self.reserve()
            except Exception as e: errors.append(e)
        ts=[threading.Thread(target=work) for _ in range(2)]
        for t in ts:t.start()
        for t in ts:t.join()
        self.assertEqual(errors,[]); self.assertEqual(len(json.loads(self.path.read_text())['requests']),148)
    def test_retire_cell_and_readonly_inspect(self):
        l=self.reserve(); self.assertEqual(l.inspect_attempts(),[])
        def fail(_): raise RuntimeError('crash')
        with self.assertRaises(RuntimeError): l.send('p','a/0/first/TURN0',self.body,fail)
        before=self.path.read_bytes(); pending=l.inspect_attempts()
        self.assertEqual(self.path.read_bytes(),before)
        self.assertEqual(len(pending),1); self.assertFalse(pending[0]['raw_response_valid'])
        l.retire_cell('a','0'); l.retire_cell('a','0')
        rows=json.loads(self.path.read_text())['requests'].values()
        self.assertEqual(sum(r.get('formal_state')=='planned' for r in rows),111)
        self.assertEqual(sum(r.get('formal_state')=='released' for r in rows),36)
        self.assertEqual(len(l.inspect_attempts()),1)
    def test_installed_official_tokenizer_when_available(self):
        root=Path(__file__).resolve().parent; python=root/'.tokenizer-venv/bin/python'; model=root/'tokenizer-data/tokenizer.json'
        if not python.exists() or not model.exists(): self.skipTest('private pinned tokenizer not installed')
        provider={'text_tokenizer':{'python':str(python),'tokenizer_json':str(model),'sha256':'89085f12ef79460ac5f66d1119325ddfc694b4ab209d80bbd81d35f081dc9614','safety_margin_tokens':4096,'source_url':'https://cdn.deepseek.com/api-docs/deepseek_v4_tokenizer.zip'}}
        baseline=estimate_input_tokens({'messages':[]},provider)
        body={'messages':[{'role':'user','content':'你好 <|special|> '*1000},{'role':'assistant','content':'retained history'}],'tools':[{'name':'工具','schema':{'description':'完整工具'}}]}
        count=estimate_input_tokens(body,provider)
        self.assertGreater(count,baseline); self.assertGreater(count,4096)
        self.assertLess(count,len(json.dumps(body).encode())+4096)
    def test_pinned_tokenizer_margin_full_history_and_failure(self):
        import hashlib, subprocess, sys
        from unittest.mock import patch
        model=self.root/'tokenizer.json'; model.write_text('{}')
        provider=copy.deepcopy(self.config['providers']['p'])
        provider['text_tokenizer']={'python':sys.executable,'tokenizer_json':str(model),'sha256':hashlib.sha256(model.read_bytes()).hexdigest(),'safety_margin_tokens':4096,'source_url':'https://cdn.deepseek.com/api-docs/deepseek_v4_tokenizer.zip'}
        body={'messages':[{'role':'user','content':'你好 <|special|>'*100},{'role':'assistant','content':'history retained'}],'tools':[{'description':'工具说明','parameters':{'full':'schema'}}],'max_tokens':100}
        def worker(*args,**kw):
            self.assertEqual(kw['env'],{}); self.assertIn('-I',args[0]); self.assertIn('history retained',kw['input']); self.assertIn('full',kw['input']); self.assertIn('special',kw['input'])
            return subprocess.CompletedProcess(args[0],0,'123\n','')
        with patch('budget.subprocess.run',side_effect=worker): self.assertEqual(estimate_input_tokens(body,provider),4219)
        provider['text_tokenizer']['sha256']='0'*64
        with self.assertRaisesRegex(BudgetError,'SHA256 mismatch'): estimate_input_tokens(body,provider)
        provider['text_tokenizer']['sha256']=hashlib.sha256(model.read_bytes()).hexdigest()
        with patch('budget.subprocess.run',return_value=subprocess.CompletedProcess([],1,'','private error')):
            with self.assertRaisesRegex(BudgetError,'invalid token count'): estimate_input_tokens(body,provider)
        provider['text_tokenizer']['safety_margin_tokens']=4095
        with self.assertRaises(BudgetError): estimate_input_tokens(body,provider)
    def test_responses_png_context(self):
        import base64, struct, zlib
        def chunk(kind,data):
            return struct.pack('>I',len(data))+kind+data+struct.pack('>I',zlib.crc32(kind+data)&0xffffffff)
        # Real RGB PNG with deliberately uncompressed image bytes, much larger
        # than its pixel token budget: base64 must not become text tokens.
        width=32; height=32
        raw=b'\x89PNG\r\n\x1a\n'+chunk(b'IHDR',struct.pack('>IIBBBBB',width,height,8,2,0,0,0))+chunk(b'IDAT',zlib.compress((b'\0'+bytes(range(96)))*height,0))+chunk(b'IEND',b'')
        url='data:image/png;base64,'+base64.b64encode(raw).decode()
        p=self.config['providers']['p']; p['image_token_bound']={'tile_size':512,'tokens_per_tile':100,'base_tokens':100}
        body={'input':[{'role':'user','content':[{'type':'input_text','text':'hello'},{'type':'input_image','image_url':url}]}],'max_output_tokens':100}
        l=self.reserve(); l.check_context('p',body)
        self.assertLess(estimate_input_tokens(body,p),1000)
        self.assertGreater(len(json.dumps(body)),1000)
        bad=copy.deepcopy(body); bad['input'][0]['content'][1]['image_url']=url[:-8]
        with self.assertRaises(BudgetError): l.check_context('p',bad)
        p['context_window']=2001
        with self.assertRaises(BudgetError): l.check_context('p',body)
    def test_positive_sam_fee_fails_preflight(self):
        self.config['sam_fee_usd']=.01
        with self.assertRaisesRegex(BudgetError,'SAM fee unsupported'): self.reserve()
        self.assertEqual(json.loads(self.path.read_text())['requests'],{})
        self.config['sam_fee_usd']=0
        self.assertEqual(len(plan_block(self.config,self.rows)),148)
    def test_context_complete_and_images(self):
        l=self.reserve()
        with self.assertRaises(BudgetError): l.check_context('p',{**self.body,'tools':[{'description':'x'*2000}]})
        with self.assertRaises(BudgetError): l.check_context('p',{**self.body,'max_tokens':99})
        with self.assertRaises(BudgetError): l.check_context('p',{**self.body,'messages':[{'content':[{'type':'image_url','image_url':'x'}]}]})

if __name__=='__main__': unittest.main()
