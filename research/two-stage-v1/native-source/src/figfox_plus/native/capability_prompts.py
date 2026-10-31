"""Full validated P4/v13 rules, with shared capability conditions.

FIRST_RULE_ADAPTATIONS is an auditable, exact replacement map against the
unchanged prompts/first_native.md. It adapts capability/stage/data placeholders,
not the quality or construction strategy. Repair rules come directly from the
original v13 constants, so an unused historical template cannot mask regression.
"""
import hashlib
import json
from ..state import PLUS_ROOT
from .capabilities import normalize_capabilities

FIRST_RULE_ADAPTATIONS = (
    ('[Output]\nOutput only', '[Output: first generation only]\nDuring first generation, output only'),
    ('{{CANVAS}}', 'Use the canvas dimensions supplied in this request.'),
    ('The identifier is the reference. Image crops are provided in the attached images.',
     'The identifier is the reference. If SAM arrow crops are present in the actual attachment manifest, use those crops.'),
    ('{{ARROW_LIBRARY}}', 'Use the SAM arrow table supplied in this request, if present; otherwise no SAM arrow library is supplied.'),
    ('3. During conduction, establish mappings', '3. When SAM assets are available, during conduction, establish mappings'),
    ('genuine SVG/SP construction', 'genuine SVG construction (or SP construction when code_methods is true)'),
    ('challenging photographic areas can be handled using existing in-flight crop requests.',
     'when code_methods is true, challenging photographic areas can be handled using existing in-flight crop requests; otherwise construct them in native SVG.'),
    ('At the same time, locate the SAM asset', 'When a SAM overview board and matching assets are supplied, at the same time, locate the SAM asset'),
    ('[SAM Asset Mapping & Post-Replacement]',
     '[SAM Asset Mapping & Post-Replacement: only for available confirmed matching SAM assets]'),
    ('For missed detections or challenging areas, declare', 'When code_methods is true, for missed detections or challenging areas, declare'),
    ('Below are asset IDs, types, and SAM original block coordinates, matching attached crops in table order:\n{{IMAGE_LIBRARY}}',
     'Use the supplied SAM asset table and actual attachment manifest for asset IDs, types, original block coordinates, and crop order. If none are supplied, no SAM crops or overview board are attached.'),
    ('construct representable content with SVG/SP;', 'construct representable content with SVG (or SP when code_methods is true);'),
    ('for challenging regions that are difficult to construct accurately, use the existing data-plus-crop mechanism,',
     'when code_methods is true, for challenging regions that are difficult to construct accurately, use the existing data-plus-crop mechanism (otherwise construct these regions in native SVG),'),
    ('SP can be declared in SVG as', 'When code_methods is true, SP can be declared in SVG as'),
    ('For solid color regions requiring exact fidelity, declare',
     'When code_methods is true, for solid color regions requiring exact fidelity, declare'),
)


def _adapt(text, replacements):
    for original, replacement in replacements:
        if text.count(original) != 1:
            raise ValueError('Validated prompt rule changed; review adaptation: ' + original)
        text = text.replace(original, replacement)
    return text


COMMON_QUALITY = _adapt((PLUS_ROOT / 'prompts/first_native.md').read_text(), FIRST_RULE_ADAPTATIONS)

COMMON_CONDITIONAL_POLICY = '''Use only capabilities in availability_manifest. If code_methods is true, registered SP/BP/TP, crop and color methods are available according to their supplied documentation. If false, first output complete visible native SVG and repair with generated_python using Python standard-library XML/math and your own geometry; do not request module operations, library imports, host measurements, crop/color methods or convergence repairs. For S1/D use registered constructors when available; otherwise construct the geometry and arrows yourself with the same visual requirements. If SAM is available and matching assets exist, first construct visible SVG then bind confirmed assets and replace only covered construction; preserve original block coordinates and relative arrangement. If assets are absent or uncertain, retain complete SVG construction. Unsupported declarations must never be emitted. E/F require the same declared alignment/contain/separate checks and two successful read-only checks; automatic convergence repairs are available only with code_methods. When unavailable, set repairs to [] and repair geometry yourself. Unresolved conditions must remain reported.'''
METHOD_APPLICABILITY = """The following full original rules retain their visual requirements in every assignment. Every instruction to use SP, BP, TP, sp_replace, sp_photo, bp_patch, crop/color declarations, registered constructors, or automatic convergence repairs is conditional on code_methods being true. Their schemas describe only the enabled route, never permission to use a disabled route. If code_methods is false, use complete native SVG in the first request and generated_python with Python standard-library XML/math in repair requests; implement the same geometry, formulas, colors and visible detail yourself. The S1 prohibition on hand-drawn polygons applies to the enabled constructor route; the disabled route must construct the correct cuboid/lattice geometry itself. When code_methods is false, do not request or import external method libraries, source, manuals or host TP numerical context. For E/F keep the identical relations/alignment checks and host read-only acceptance; with code_methods false set repairs: [] and make the needed changes in your own program. SAM mapping/replacement instructions apply only when sam is true and confirmed matching assets and the described evidence are actually supplied; otherwise retain complete visible construction. SAM availability does not grant crop/color/SP methods. A SAM overview is available only if the actual attachment manifest lists it. In repair requests, preserve initial construction requirements within the listed issue scope; do not rebuild unrelated frames or redo initial SAM replacement. First-generation SVG-only output instructions apply only to the first request; review and repair use their JSON/program response contracts. Edit within declared issue scope, preserve neighbors, honor dependencies and retain stable IDs. Host safety, resource, scope and read-only geometry checks apply equally; failures roll back. Execution never constitutes visual acceptance. generated_python receives INPUT_SVG and OUTPUT_SVG file paths; parse with xml.etree.ElementTree and write the complete SVG to OUTPUT_SVG."""


def blocks(policy):
    p=normalize_capabilities(policy)
    availability=json.dumps({'version':p['version'],'sam':p['sam'],'code_methods':p['code_methods'],
       'repair_routes':['module_program','generated_python'] if p['code_methods'] else ['generated_python'],
       'common_host_services':['SVG rendering','same 1/2 comparison crops','ID navigation','read-only quality guards']},sort_keys=True)
    return {'availability_manifest':availability,'common_conditional_policy':COMMON_CONDITIONAL_POLICY+'\n'+METHOD_APPLICABILITY,'common_quality':COMMON_QUALITY}

def block_hashes(policy):
    return {k:hashlib.sha256(v.encode()).hexdigest() for k,v in blocks(policy).items()}

def common_prompt(policy):
    return '\n'.join(k+'\n'+v for k,v in blocks(policy).items())


def repair_prompt(policy, *, followup=False):
    # Imports are lazy: orchestrator calls this only after its constants exist.
    from .review_problem_first_v13.lean_inspection import REPAIR_PROMPT
    from .review_problem_first_v13.orchestrator import PROGRAM_CONTRACT
    from .review_problem_first_v13.followup import PROMPT as FOLLOWUP_PROMPT

    repair = REPAIR_PROMPT
    contract = PROGRAM_CONTRACT
    if followup:
        repair = repair.replace('This is the second request.',
                                'This is the one-time receipt-driven followup request.')
        contract = contract.replace('Write programs only in the second request.',
                                    'Write programs for this one-time receipt-driven followup request.')
    # The original followup's module-only shape must allow the stdlib route too.
    followup_rules = FOLLOWUP_PROMPT.replace(
        'route:module_program,target_ids', 'route:module_program|generated_python,target_ids'
    ).replace('rcd_predescription,args,relations?',
              'rcd_predescription,args?,source_code?,relations?')
    if not normalize_capabilities(policy)['code_methods']:
        contract = contract.replace('route:module_program|generated_python', 'route:generated_python')
        followup_rules = followup_rules.replace('route:module_program|generated_python', 'route:generated_python')
    return (common_prompt(policy) + '\n[Repair rules; method directives are conditional as stated above]\n'
            + repair + '\n[Program contract and acceptance policy; same capability conditions apply]\n'
            + contract + ('\n' + followup_rules if followup else ''))
