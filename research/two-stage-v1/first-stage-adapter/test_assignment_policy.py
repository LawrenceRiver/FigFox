"""Synthetic boundary tests only; no model, rendering, or native case execution."""
import ast
import json
from pathlib import Path
import sys
import tempfile
import unittest

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE))
import assignment_policy as ap
NATIVE=HERE/'source/src'
if not NATIVE.exists():
    NATIVE=HERE.parents[1]/'native-metadata-workflow-v6-20261028/source/src'
sys.path.insert(0,str(NATIVE))
from figfox_plus.native.capabilities import reject_disabled_program, freeze_policy, trace_context
from figfox_plus.native.review_problem_first_v13.sandbox import validate_stdlib_source


def setup_cell(root,on=False):
    inputs=root/'inputs';inputs.mkdir()
    p={'version':'capabilities-v1','sam':True,'code_methods':on}
    (inputs/'capabilities.json').write_text(json.dumps({'policy':p,'sha256':ap.digest(p)}))
    (inputs/'observer-assignment.json').write_text(json.dumps({'format':'observer-assignment-v1','mode':'enabled' if on else 'disabled_by_assignment','capability_sha256':ap.digest(p)}))
    return p


class AssignmentTests(unittest.TestCase):
    def test_typed_off_and_revision_freeze(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=setup_cell(root)
            self.assertEqual(ap.load(root),p)
            freeze_policy(root,p)
            with self.assertRaisesRegex(ValueError,'cannot change'):
                freeze_policy(root,{**p,'code_methods':True})
            value=json.loads((root/'inputs/capabilities.json').read_text());value['policy']['code_methods']=0
            (root/'inputs/capabilities.json').write_text(json.dumps(value))
            with self.assertRaises(ValueError):ap.load(root)

    def test_disabled_observer_explicit_and_fail_closed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);setup_cell(root)
            self.assertTrue(ap.disabled(root))
            (root/'inputs/analysis').mkdir()
            with self.assertRaisesRegex(ValueError,'active artifact'):ap.load(root)

    def test_off_native_rejects_module_and_records_policy_trace(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);p=setup_cell(root)
            with trace_context(root,p,'synthetic-boundary'):
                with self.assertRaisesRegex(ValueError,'code methods disabled'):
                    reject_disabled_program({'id':'synthetic','route':'module'},p)
            row=json.loads((root/'invocation-trace.jsonl').read_text())
            self.assertEqual(row['capability_hash'],ap.digest(p))
            self.assertEqual(row['status'],'rejected')

    def test_off_generated_python_stdlib_only(self):
        with tempfile.TemporaryDirectory() as d:
            p=setup_cell(Path(d))
            reject_disabled_program({'id':'p','route':'generated_python','source_code':'import math\nx = math.sqrt(4)'},p)
            validate_stdlib_source('import math\nx = math.sqrt(4)')
            with self.assertRaises(ValueError):validate_stdlib_source('from figfox_plus.native import sp')
            with self.assertRaises(ValueError):reject_disabled_program({'route':'generated_python','repairs':[{'method':'sp'}]},p)

    def test_controller_forwards_policy_to_all_deep_boundaries(self):
        tree=ast.parse((HERE/'flow.py').read_text());calls=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.Call) and isinstance(node.func,ast.Attribute) and node.func.attr in ('select_valid_programs','execute_programs'):
                calls.append(node)
                self.assertTrue(any(k.arg=='capabilities' and isinstance(k.value,ast.Call) and isinstance(k.value.func,ast.Attribute) and k.value.func.attr=='load' for k in node.keywords))
        self.assertEqual(len(calls),3)

    def test_native_s1_d_structural_requirements_are_conditional(self):
        source=NATIVE/'figfox_plus/native/review_problem_first_v13/programs.py'
        tree=ast.parse(source.read_text());guards=[]
        for node in ast.walk(tree):
            if isinstance(node,ast.If) and any(isinstance(x,ast.Raise) and isinstance(x.exc,ast.Call) and x.exc.args and isinstance(x.exc.args[0],ast.Constant) and x.exc.args[0].value in ('regular solid must be replaced with SP cuboid or lattice','arrow must be rebuilt with SP arrow') for x in node.body):
                guards.append(ast.unparse(node.test))
        self.assertEqual(len(guards),2)
        self.assertTrue(all("policy['code_methods']" in guard for guard in guards))

if __name__=='__main__':unittest.main()
