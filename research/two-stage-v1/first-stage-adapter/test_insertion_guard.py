import hashlib
import json
from pathlib import Path
import tempfile
import unittest
import xml.etree.ElementTree as ET
import insertion_guard as guard
import flow

BEFORE='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><g id="frame"><rect id="keep" width="4"/><g><path d="M0 0"/>anon</g></g><g id="other"/></svg>'
ISSUES=[{'id':'missing','target_ids':[],'container_id':'frame'}]
def program(code='pass',route='generated_python'):
    return {'id':'insert','image_id':'case','route':route,'issue_ids':['missing'],'target_ids':['frame'],'source_code':code}
def add(before=BEFORE):
    root=ET.fromstring(before);ET.SubElement(root.find('.//*[@id="frame"]'),'{http://www.w3.org/2000/svg}circle',{'id':'new','r':'2'});return ET.tostring(root,encoding='unicode')
class ProofTests(unittest.TestCase):
    def test_insert_both_policies_and_preserve_anonymous(self):
        for code in (False,True):
            self.assertEqual(guard.prove(BEFORE,add(),['frame'],[])['inserted_root_ids'],['new'])
    def test_generated_precheck_defers_to_mandatory_transaction(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'input.svg';path.write_text(BEFORE)
            receipt=flow.insertion_scope_guard(program(),ISSUES,path,set())
            self.assertEqual(receipt['proof_required'],'transactional_xml_before_checkpoint')
    def test_adversarial_xml(self):
        variants=[]
        for action in ('attr','delete','reorder','anonymous','anchor','reparent','outside','duplicate','style','borrow'):
            root=ET.fromstring(BEFORE);frame=root.find('.//*[@id="frame"]');keep=root.find('.//*[@id="keep"]');other=root.find('.//*[@id="other"]')
            if action=='attr':keep.set('width','77')
            if action=='delete':frame.remove(keep)
            if action=='reorder':frame.remove(keep);frame.append(keep)
            if action=='anonymous':frame[1][0].set('d','M9 9')
            if action=='anchor':frame.set('transform','translate(3)')
            if action=='reparent':frame.remove(keep);other.append(keep)
            if action=='outside':ET.SubElement(other,'circle',{'id':'new'})
            if action=='duplicate':ET.SubElement(frame,'circle',{'id':'keep'})
            if action=='style':ET.SubElement(frame,'style',{'id':'new'}).text='rect{display:none}'
            if action=='borrow':ET.SubElement(ET.SubElement(frame,'g',{'id':'new'}),'rect',{'id':'keep'})
            variants.append((action,ET.tostring(root,encoding='unicode')))
        for action,value in variants:
            with self.subTest(action=action),self.assertRaises(ValueError):guard.prove(BEFORE,value,['frame'],[])
    def test_explicit_existing_permission_only(self):
        root=ET.fromstring(add());root.find('.//*[@id="keep"]').set('width','77')
        guard.prove(BEFORE,ET.tostring(root,encoding='unicode'),['frame'],['keep'])
        with self.assertRaises(ValueError):guard.prove(BEFORE,ET.tostring(root,encoding='unicode'),['frame'],[])
    def test_prolog_global_constructs_fail_closed(self):
        for prefix in ('<!DOCTYPE svg>','<?xml-stylesheet href="x.css"?>','<!--global-->'):
            with self.subTest(prefix=prefix),self.assertRaises(ValueError):guard.prove(prefix+BEFORE,add(),['frame'],[])
    def test_missing_receipt_and_finally_restore(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);svg=root/'a.svg';svg.write_text(BEFORE)
            def sandbox(*args,**kwargs):return {}
            def checkpoint(*args,**kwargs):return {}
            native=SimpleNamespace(run_code=sandbox,write_checkpoint=checkpoint)
            p=program();images={'case':{'svg':str(svg)}}
            with self.assertRaisesRegex(ValueError,'missing postguard receipt'):
                with guard.transactions(native,[p],ISSUES,images,root/'proof.jsonl') as check:
                    check.verify({'rcd':[{'program_id':p['id'],'status':'changed_unverified'}]})
            self.assertIs(native.run_code,sandbox);self.assertIs(native.write_checkpoint,checkpoint)
    def test_failed_sandbox_has_common_guard_receipt(self):
        from types import SimpleNamespace
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);svg=root/'a.svg';svg.write_text(BEFORE)
            def failed(*args,**kwargs):return {'status':'failed','error':'synthetic sandbox failure'}
            native=SimpleNamespace(run_code=failed,write_checkpoint=lambda *a:None)
            with guard.transactions(native,[program()],ISSUES,{'case':{'svg':str(svg)}},root/'proof.jsonl'):
                native.run_code('pass',svg,root/'trial')
            rows=[json.loads(x) for x in (root/'proof.jsonl').read_text().splitlines()]
            self.assertEqual(rows[-1]['status'],'failed');self.assertEqual(rows[-1]['before_sha256'],guard.digest(BEFORE));self.assertIsNone(rows[-1]['output_sha256'])
    def test_exact_root_and_descendant_anchor_rules(self):
        root=ET.fromstring(BEFORE);root.set('id','root')
        with self.assertRaises(ValueError):guard.prove(ET.tostring(root,encoding='unicode'),ET.tostring(root,encoding='unicode'),['root'],[])
        root=ET.fromstring(BEFORE);ET.SubElement(root.find('.//*[@id="frame"]')[1],'circle',{'id':'new'})
        with self.assertRaises(ValueError):guard.prove(BEFORE,ET.tostring(root,encoding='unicode'),['frame'],[])
        root=ET.fromstring(add());root.find('.//*[@id="keep"]').tail='changed'
        with self.assertRaises(ValueError):guard.prove(BEFORE,ET.tostring(root,encoding='unicode'),['frame'],[])
    def test_flow_execute_mandatory_context_and_module_binding(self):
        import ast
        tree=ast.parse((Path(__file__).parent/'flow.py').read_text())
        execute=next(n for n in ast.walk(tree) if isinstance(n,ast.FunctionDef) and n.name=='execute')
        contexts=[n for n in ast.walk(execute) if isinstance(n,ast.With) and any(isinstance(x.context_expr,ast.Call) and isinstance(x.context_expr.func,ast.Attribute) and x.context_expr.func.attr=='transactions' for x in n.items)]
        self.assertEqual(len(contexts),1)
        self.assertTrue(any(isinstance(n,ast.Call) and isinstance(n.func,ast.Attribute) and n.func.attr=='verify' for n in ast.walk(contexts[0])))
        with tempfile.TemporaryDirectory() as d:
            self.assertIn('../insertion_guard.py',flow.prompt_hashes(Path(d)))
    def test_missing_anchor_or_duplicate_source_fails(self):
        with tempfile.TemporaryDirectory() as d:
            svg=Path(d)/'a.svg';svg.write_text(BEFORE)
            with self.assertRaises(ValueError):guard.bind([program(),{**program(),'id':'other'}],ISSUES,svg)
            with self.assertRaises(ValueError):guard.bind([program()],[{**ISSUES[0],'container_id':'absent'}],svg)

if __name__=='__main__':unittest.main()

class NativeTransactionTests(unittest.TestCase):
    def test_real_sandbox_and_native_transaction_common_guard(self):
        import sys
        from unittest.mock import patch
        sys.path.insert(0,str(Path(__file__).parent/'source/src'))
        from figfox_plus.native.review_problem_first_v13 import programs as native
        for code_methods in (False,True):
            for malicious in (False,'change','remove'):
                with self.subTest(code_methods=code_methods,malicious=malicious),tempfile.TemporaryDirectory() as d:
                    root=Path(d);svg=root/'input.svg';svg.write_text(BEFORE)
                    source="import xml.etree.ElementTree as ET\nr=ET.parse(INPUT_SVG).getroot()\nf=r.find('.//*[@id=\"frame\"]')\nET.SubElement(f,'{http://www.w3.org/2000/svg}circle',{'id':'new','r':'2'})\n"
                    if malicious=='change':source+="r.find('.//*[@id=\"keep\"]').set('width','77')\n"
                    if malicious=='remove':source+="f.remove(r.find('.//*[@id=\"keep\"]'))\n"
                    source+="ET.ElementTree(r).write(OUTPUT_SVG,encoding='unicode')\n"
                    p={**program(source),'phase':'preconstructor','base_revision':guard.digest(BEFORE),'depends_on':[],'relations':[]}
                    raw=[{**ISSUES[0],'image_id':'case','category':'A','neighbor_ids':[],'description':'missing unit'}]
                    lowered,_=flow.native_issue_bindings(raw,svg)
                    images={'case':{'svg':str(svg),'png':str(root/'input.png'),'original':str(root/'original.png'),'revision':guard.digest(BEFORE)}}
                    policy={'version':'capabilities-v1','sam':False,'code_methods':code_methods}
                    # Measurement is isolated: this test exercises actual native validation,
                    # sandbox and transaction/rollback; it makes no rendering assertion.
                    def checkpoint(tree,folder,index):
                        folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);out=folder/f'{index}.svg';out.write_text(ET.tostring(tree,encoding='unicode'))
                        return {'svg':str(out),'png':str(root/'synthetic.png'),'revision':guard.digest(out.read_text())},{}
                    def measure(*args,**kwargs):return {}
                    old_run=native.run_code
                    with patch.object(native,'write_checkpoint',checkpoint),patch.object(native,'measure_tight',measure):
                        with guard.transactions(native,[p],raw,images,root/'guard.jsonl') as check:
                            result=native.execute_programs([p],lowered,images,root/'native',capabilities=policy);check.verify(result)
                    self.assertIs(native.run_code,old_run)
                    row=result['rcd'][0]
                    self.assertEqual(row['status'],'failed' if malicious else 'changed_unverified',row)
                    self.assertEqual(svg.read_text(),BEFORE)
                    if malicious:
                        self.assertEqual(result['images']['case']['svg'],str(svg));self.assertTrue(row['rolled_back'])
                        self.assertIn('insertion guard:',row['error'])
                    else:self.assertEqual(row['insertion_common_guard']['status'],'passed')
                    receipts=[json.loads(x) for x in (root/'guard.jsonl').read_text().splitlines()]
                    self.assertTrue(any(x.get('stage')=='sandbox-output' and x.get('status')==('failed' if malicious else 'passed') for x in receipts))

    def test_native_module_insertion_uses_same_checkpoint_proof(self):
        import sys
        from unittest.mock import patch
        sys.path.insert(0,str(Path(__file__).parent/'source/src'))
        from figfox_plus.native.review_problem_first_v13 import programs as native
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);svg=root/'input.svg';svg.write_text(BEFORE)
            p={k:v for k,v in program(route='module_program').items() if k!='source_code'}
            p.update(phase='preconstructor',base_revision=guard.digest(BEFORE),depends_on=[],relations=[],args={'operations':[{'method':'bp_add','target_ids':['frame'],'args':{'parent_id':'frame','svg':'<circle id="new" r="2"/>'}}]})
            raw=[{**ISSUES[0],'image_id':'case','category':'A','neighbor_ids':[],'description':'missing unit'}]
            lowered,_=flow.native_issue_bindings(raw,svg)
            images={'case':{'svg':str(svg),'png':str(root/'input.png'),'original':str(root/'original.png'),'revision':guard.digest(BEFORE)}}
            def checkpoint(tree,folder,index):
                folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);out=folder/'trial.svg';out.write_text(ET.tostring(tree,encoding='unicode'))
                return {'svg':str(out),'png':'synthetic','revision':guard.digest(out.read_text())},{}
            flow.insertion_scope_guard(p,raw,svg,native.MUTATIONS)
            def module_insert(tree,*args,**kwargs):
                ET.SubElement(tree.find('.//*[@id="frame"]'),'{http://www.w3.org/2000/svg}circle',{'id':'new','r':'2'})
                return {},{},[]
            # Operation raster measurement is outside this transaction-proof test.
            with patch.object(native,'write_checkpoint',checkpoint),patch.object(native,'_perform',module_insert):
                with guard.transactions(native,[p],raw,images,root/'guard.jsonl') as check:
                    result=native.execute_programs([p],lowered,images,root/'native',capabilities={'version':'capabilities-v1','sam':False,'code_methods':True});check.verify(result)
            self.assertEqual(result['rcd'][0]['status'],'changed_unverified',result['rcd'])
            self.assertEqual(result['rcd'][0]['insertion_common_guard']['stage'],'before-checkpoint')

class ReviewRegressionTests(unittest.TestCase):
    def run_native(self,before,raw,plans,code_methods=True):
        import sys
        from unittest.mock import patch
        sys.path.insert(0,str(Path(__file__).parent/'source/src'))
        from figfox_plus.native.review_problem_first_v13 import programs as native
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);svg=root/'input.svg';svg.write_text(before)
            for p in plans:p.update(phase='preconstructor',base_revision=guard.digest(before),depends_on=[],relations=[])
            images={'case':{'svg':str(svg),'png':'unused','original':'unused','revision':guard.digest(before)}}
            lowered,_=flow.native_issue_bindings(raw,svg)
            def checkpoint(tree,folder,index):
                folder=Path(folder);folder.mkdir(parents=True,exist_ok=True);out=folder/f'{index}.svg';out.write_text(ET.tostring(tree,encoding='unicode'))
                return {'svg':str(out),'png':'synthetic','revision':guard.digest(out.read_text())},{}
            def measure(*a,**kw):return {}
            with patch.object(native,'write_checkpoint',checkpoint),patch.object(native,'measure_tight',measure):
                with guard.transactions(native,plans,raw,images,root/'proof.jsonl') as check:
                    result=native.execute_programs(plans,lowered,images,root/'native',capabilities={'version':'capabilities-v1','sam':False,'code_methods':code_methods});check.verify(result)
            self.assertEqual(svg.read_text(),before)
            return result
    def test_native_resource_outside_defs_cannot_change_protected_paint(self):
        before='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><g id="frame"/><g id="editable"><linearGradient id="paint"><stop id="stop" offset="0" stop-color="red"/></linearGradient></g><rect id="protected" width="10" height="10" fill="url(#paint)"/></svg>'
        raw=[{'id':'missing','image_id':'case','category':'A','target_ids':[],'neighbor_ids':[],'container_id':'frame'},{'id':'existing','image_id':'case','category':'A','target_ids':['editable'],'neighbor_ids':[]}]
        source="import xml.etree.ElementTree as ET\nr=ET.parse(INPUT_SVG).getroot()\nnext(n for n in r.iter() if n.get('id')=='stop').set('stop-color','blue')\nET.SubElement(next(n for n in r.iter() if n.get('id')=='frame'),'{http://www.w3.org/2000/svg}circle',{'id':'new','r':'2'})\nET.ElementTree(r).write(OUTPUT_SVG,encoding='unicode')\n"
        p={**program(source),'issue_ids':['missing','existing'],'target_ids':['frame','editable']}
        result=self.run_native(before,raw,[p])
        self.assertEqual(result['rcd'][0]['status'],'failed',result['rcd'])
        self.assertTrue(result['rcd'][0]['rolled_back'])
    def test_native_duplicate_source_without_insertion_still_executes(self):
        before='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><rect id="a" width="1"/><rect id="b" width="1"/></svg>'
        raw=[{'id':x,'image_id':'case','category':'A','target_ids':[x],'neighbor_ids':[]} for x in ('a','b')]
        same='import xml.etree.ElementTree as ET\nr=ET.parse(INPUT_SVG).getroot()\nET.ElementTree(r).write(OUTPUT_SVG,encoding="unicode")'
        plans=[{**program(same),'id':'p'+x,'issue_ids':[x],'target_ids':[x]} for x in ('a','b')]
        result=self.run_native(before,raw,plans)
        self.assertEqual([x['status'] for x in result['rcd']],['executed_no_change','executed_no_change'],result['rcd'])
    def test_native_unrelated_duplicates_with_separate_insertion(self):
        before='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><g id="frame"/><rect id="a" width="1"/><rect id="b" width="1"/></svg>'
        raw=[{'id':x,'image_id':'case','category':'A','target_ids':[x],'neighbor_ids':[]} for x in ('a','b')]+[{'id':'missing','image_id':'case','category':'A','target_ids':[],'neighbor_ids':[],'container_id':'frame'}]
        same='import xml.etree.ElementTree as ET\nr=ET.parse(INPUT_SVG).getroot()\nET.ElementTree(r).write(OUTPUT_SVG,encoding="unicode")'
        plans=[{**program(same),'id':'p'+x,'issue_ids':[x],'target_ids':[x]} for x in ('a','b')]
        source="""import xml.etree.ElementTree as ET
r=ET.parse(INPUT_SVG).getroot()
ET.SubElement(r.find('.//*[@id="frame"]'),'{http://www.w3.org/2000/svg}circle',{'id':'new','r':'2'})
ET.ElementTree(r).write(OUTPUT_SVG,encoding='unicode')"""
        plans.append(program(source))
        result=self.run_native(before,raw,plans)
        self.assertEqual([x['status'] for x in result['rcd']],['executed_no_change','executed_no_change','changed_unverified'],result['rcd'])
    def test_mixed_duplicate_source_still_fails_closed(self):
        with tempfile.TemporaryDirectory() as d:
            svg=Path(d)/'input.svg';svg.write_text(BEFORE)
            raw=ISSUES+[{'id':'existing','target_ids':['keep']}]
            normal={**program(),'id':'normal','issue_ids':['existing'],'target_ids':['keep']}
            with self.assertRaisesRegex(ValueError,'ambiguous'):guard.bind([program(),normal],raw,svg)
    def test_resource_families_and_external_reference_context(self):
        for tag in ('linearGradient','radialGradient','stop','marker','pattern','clipPath','mask','filter','feGaussianBlur','symbol'):
            before=f'<svg><g id="frame"/><g id="editable"><{tag} id="resource"/></g></svg>'
            root=ET.fromstring(before);root.find('.//*[@id="resource"]').set('x','changed')
            with self.subTest(tag=tag),self.assertRaises(ValueError):guard.prove(before,ET.tostring(root,encoding='unicode'),['frame'],['editable'])
        before='<svg><g id="frame"/><g id="editable"><rect id="paint"/></g><use id="protected" href="#paint"/></svg>'
        root=ET.fromstring(before);root.find('.//*[@id="editable"]').set('transform','translate(8)')
        with self.assertRaises(ValueError):guard.prove(before,ET.tostring(root,encoding='unicode'),['frame'],['editable'])

    def test_native_pure_insertion_reference_capture_and_structural_style_reject_both_policies(self):
        source="""import xml.etree.ElementTree as ET
r=ET.parse(INPUT_SVG).getroot()
ET.SubElement(r.find('.//*[@id="frame"]'),'{http://www.w3.org/2000/svg}circle',{'id':'new','r':'2'})
ET.ElementTree(r).write(OUTPUT_SVG,encoding='unicode')"""
        raw=[{'id':'missing','image_id':'case','category':'A','target_ids':[],'neighbor_ids':[],'container_id':'frame'}]
        contexts=['<use id="protected" href="#new"/>','<rect id="protected" width="2" fill="url(#new)"/>','<style>g:has(#new) + rect { fill: blue }</style><rect id="protected"/>','<style>#frame > :last-child { fill: blue }</style><rect id="protected"/>']
        for policy in (False,True):
            for context in contexts:
                with self.subTest(code_methods=policy,context=context):
                    before='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><g id="frame"/>'+context+'</svg>'
                    result=self.run_native(before,raw,[program(source)],code_methods=policy)
                    self.assertEqual(result['rcd'][0]['status'],'failed',result['rcd'])
                    self.assertTrue(result['rcd'][0]['rolled_back'])
                    self.assertIn('dependency',result['rcd'][0]['error'])

    def test_native_realistic_static_context_allows_insertion_both_policies(self):
        before='<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80"><style>.base { fill: rgb(20, 30, 40); stroke: #fff; } #protected { opacity: 0.8; } g .base { stroke-width: 1; }</style><defs><linearGradient id="immutablePaint"><stop id="colorStop" offset="0" stop-color="red"/></linearGradient></defs><g id="frame"><rect id="keep" class="base" width="2" fill="rgba(1, 2, 3, .5)"/></g><image id="photo" href="data:image/png;base64,iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8/x8AAwMCAO+a7V0AAAAASUVORK5CYII=" width="2" height="2"/><rect id="protected" fill="url(#immutablePaint)" width="3"/></svg>'
        source="""import xml.etree.ElementTree as ET
r=ET.parse(INPUT_SVG).getroot()
ET.SubElement(r.find('.//*[@id="frame"]'),'{http://www.w3.org/2000/svg}circle',{'id':'new','r':'2'})
ET.ElementTree(r).write(OUTPUT_SVG,encoding='unicode')"""
        raw=[{'id':'missing','image_id':'case','category':'A','target_ids':[],'neighbor_ids':[],'container_id':'frame'}]
        for policy in (False,True):
            with self.subTest(code_methods=policy):
                result=self.run_native(before,raw,[program(source)],code_methods=policy)
                self.assertEqual(result['rcd'][0]['status'],'changed_unverified',result['rcd'])
                self.assertEqual(result['rcd'][0]['insertion_common_guard']['status'],'passed')
    def test_local_reference_affected_scope_and_static_css_subset(self):
        for reference in ('#frame','#keep','#root'):
            before='<svg id="root"><g id="frame"><rect id="keep"/></g><use id="protected" href="'+reference+'"/></svg>'
            with self.subTest(reference=reference),self.assertRaises(ValueError):guard.prove(before,add(before),['frame'],[])
        for selector in ('.plain','#protected','rect','g .plain','rect.plain, #protected'):
            before='<svg xmlns="http://www.w3.org/2000/svg"><style>'+selector+' { fill: hsl(120deg 30% 40%); }</style><g id="frame"/><rect id="protected" class="plain"/></svg>'
            with self.subTest(selector=selector):guard.prove(before,add(before),['frame'],[])
        for selector in ('rect:nth-child(2)','g:has(#new)','g + rect','g > rect','@media all','[id="protected"]'):
            before='<svg xmlns="http://www.w3.org/2000/svg"><style>'+selector+' { fill: red; }</style><g id="frame"/><rect id="protected"/></svg>'
            with self.subTest(selector=selector),self.assertRaises(ValueError):guard.prove(before,add(before),['frame'],[])

    def test_reference_css_value_and_href_boundaries(self):
        for context in ('<style>.x {fill:url(#new);}</style><rect id="protected" class="x"/>','<use id="protected" href="#frame"/>','<rect id="protected" style="fill:var(--paint)"/>','<image id="protected" href="external.png"/>'):
            before='<svg xmlns="http://www.w3.org/2000/svg"><g id="frame"/>'+context+'</svg>'
            with self.subTest(context=context),self.assertRaises(ValueError):guard.prove(before,add(before),['frame'],[])
        for color in ('rgb(1,2,3)','rgba(1 2 3 / .5)','hsl(120deg 30% 40%)','hsla(120,30%,40%,.5)'):
            before='<svg xmlns="http://www.w3.org/2000/svg"><g id="frame"/><rect id="protected" fill="'+color+'"/></svg>'
            with self.subTest(color=color):guard.prove(before,add(before),['frame'],[])
