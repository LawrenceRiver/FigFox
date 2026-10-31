"""Conservative literal-only feasibility proof for a frozen native SP path.

Unknown means defer to native execution, never a certificate of safe rendering.
No native modules, scene, constructor, or renderer are loaded here.
"""
import hashlib
import math
from pathlib import Path

# These bytes jointly define typed dispatch, resolution, default host scale,
# first adaptive padding, strict pixel guard, and applicable convergence methods.
NATIVE_BINDING = {
    'src/figfox_plus/native/sp_v2.py': '8b9300c803e635f1bfa5cd1b1a03def8b24ad13586fce3f585e89fd2e0f9a3c2',
    'src/figfox_plus/native/repair_toolbox.py': '16af279cefd409c2572638ecf78a00e37c1b71e1c9eb545627a7722a1f5f23a4',
    'src/figfox_plus/native/single_call/executor.py': '163924b07d1d2945db0c71b998bb281216295368d529f57872faddd6dc0f8735',
    'src/figfox_plus/native/review_problem_first_v13/programs.py': '8170cb1d3d8d233477d89389021119ebd5fa3f4066a9eafc4c6234edeb2c0fde',
    'src/figfox_plus/native/review_problem_first_v13/quality.py': '526e038f9299b4541b3aaed7f6d457179637dfaefb3ed29565dbfc88fee2a9c9',
    'src/figfox_plus/native/review_problem_first_v13/replay.py': '31ef8a5448f2a406f944330103713a882608ec56fa334b0a6e61ca886bb10f7b',
}
HOST_SCALE = 4
PIXEL_BUDGET = 40_000_000


def binding_matches(source_root):
    """Defer every proof if any byte defining the frozen path has drifted."""
    try:
        return all(hashlib.sha256((Path(source_root)/name).read_bytes()).hexdigest()==expected
                   for name,expected in NATIVE_BINDING.items())
    except OSError:
        return False


def literal_budget_proof(viewport):
    """Return only an over-budget lower-bound proof, otherwise unknown.

    Directed rounding makes every width/height/product a lower bound on the
    native float calculation. Geometry union can only expand the supplied box.
    Restrict magnitude/cancellation and reserve an additional relative margin;
    extreme numerics and values near the strict boundary are deliberately unknown.
    """
    unknown={'status':'unknown'}
    edges=('left','top','right','bottom')
    if not isinstance(viewport,dict) or set(viewport)!=set(edges):return unknown
    values=[viewport[key] for key in edges]
    if any(type(value) not in (int,float) for value in values):return unknown
    try:
        if any(not math.isfinite(value) or abs(value)>1_000_000_000 for value in values):return unknown
        left,top,right,bottom=map(float,values)
    except (OverflowError,ValueError):return unknown
    down=lambda value:math.nextafter(value,-math.inf)
    up=lambda value:math.nextafter(value,math.inf)
    width=down(right-left);height=down(bottom-top)
    if min(width,height)<=0:return unknown
    if max(abs(left),abs(right))>width*1_000_000 or max(abs(top),abs(bottom))>height*1_000_000:return unknown
    padding=max(8,down(width*.1),down(height*.1))
    padded_width=down(down(right+padding)-up(left-padding))
    padded_height=down(down(bottom+padding)-up(top-padding))
    pixels=down(down(down(padded_width*padded_height)*HOST_SCALE)*HOST_SCALE)
    if not math.isfinite(pixels) or pixels<=PIXEL_BUDGET*(1+1e-9):return unknown
    return {'status':'proven_over_budget','pixel_lower_bound':pixels,
            'pixel_budget':PIXEL_BUDGET,'host_scale':HOST_SCALE,
            'basis':'literal supplied viewport lower bound; frozen native first padding'}


def reject_proven_budget(program,source_root):
    """Raise ordinary per-program feedback only for a bound typed literal proof."""
    if program.get('route')!='module_program' or program.get('when') or not binding_matches(source_root):return
    def visit(operations,path):
        if not isinstance(operations,list):return
        for index,op in enumerate(operations):
            if not isinstance(op,dict) or op.get('when') or not isinstance(op.get('args'),dict):continue
            here=f'{path}[{index}]';args=op['args']
            if op.get('method')=='bp_program':
                visit(args.get('operations'),here+'.args.operations')
            elif op.get('method')=='sp_replace':
                if any(str(key).startswith('$') for key in args):continue
                proof=literal_budget_proof(args.get('measurement_viewport'))
                if proof['status']=='proven_over_budget':
                    raise ValueError(f"construction measurement at {here}.args.measurement_viewport provably exceeds pixel budget: lower bound {proof['pixel_lower_bound']:.12g} > {PIXEL_BUDGET} at frozen host scale {HOST_SCALE}; native runtime guards remain authoritative")
    visit(program.get('args',{}).get('operations'), 'args.operations')
    # Frozen active E/F convergence supports only TP repairs. Other categories do
    # not execute convergence, so no convergence payload invokes this SP API.
