import json, subprocess, sys, tempfile, unittest
from pathlib import Path
from figfox_score.engine import strict_json, check, REGISTRY, validate_response
ROOT=Path(__file__).resolve().parents[1]
TITLES=['文字、数字与单位','公式含义与数学结构','对象完整与身份正确','数量与重复结构','连接拓扑与方向','走线清晰与无歧义','容器与内容归属','相对布局、对齐与对称','几何构造与内部结构','可见性与可读性','颜色、强调与视觉层级','尺度与同类样式协调','内容可编辑','分组与拆分合理','位图使用合理','文件与编辑操作可靠','局部图像保真','数据图表忠实性']
class ContractTests(unittest.TestCase):
 def test_fixed_registry(self):
  self.assertEqual([r['id'] for r in REGISTRY],[f'D{i:02}' for i in range(1,19)])
  self.assertEqual([r['title'] for r in REGISTRY],TITLES)
 def test_prompt_registry_consistency(self):
  for r in REGISTRY:
   text=(ROOT/f'prompts/{r["id"]}.md').read_text()
   for field in ['title','target','unit','evidence','allowed','boundary','division','counterexample']:
    self.assertIn(r[field],text)
 def test_cli_end_to_end(self):
  with tempfile.TemporaryDirectory() as tmp:
   def run(cmd,out,extra=()):
    p=Path(tmp,out)
    subprocess.run([sys.executable,'-m','figfox_score',cmd,'examples/input.json','--out',str(p),*extra],cwd=ROOT,check=True,capture_output=True,text=True)
    return strict_json(p)
   result=run('evaluate','rules.json');check(result,strict_json(ROOT/'schemas/result.schema.json'))
   self.assertEqual(result['usability'],'pending_verification')
   request=run('prepare','request.json');self.assertEqual(len(request['items']),18)
   response=run('mock','mock.json');validate_response(response,strict_json(ROOT/'examples/input.json'))
   merged=run('import-response','merged.json',('--response',str(Path(tmp,'mock.json'))))
   self.assertEqual(merged['coverage'],result['coverage'])
   self.assertEqual(merged['usability'],result['usability'])
 def test_cli_rejects_invalid_response(self):
  with tempfile.TemporaryDirectory() as tmp:
   bad=Path(tmp,'bad.json');bad.write_text('{}');out=Path(tmp,'out.json')
   p=subprocess.run([sys.executable,'-m','figfox_score','import-response','examples/input.json','--response',str(bad),'--out',str(out)],cwd=ROOT,capture_output=True,text=True)
   self.assertEqual(p.returncode,2);self.assertFalse(out.exists())
 def test_demo_results_contract(self):
  for name in ['rules','merged','critical']:
   result=strict_json(ROOT/f'examples/results/{name}.json');check(result,strict_json(ROOT/'schemas/result.schema.json'))
   self.assertTrue(result['synthetic']);self.assertEqual([i['item_id'] for i in result['items']],[r['id'] for r in REGISTRY])
if __name__=='__main__':unittest.main()
