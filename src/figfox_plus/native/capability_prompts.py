"""One common quality/policy block for all four assignments; docs vary explicitly."""
import hashlib
import json
from .capabilities import normalize_capabilities

COMMON_QUALITY = '''Inspect and reproduce the original figure faithfully. Complete base frames before conduction drawing; refit their proportional edges, alignment, sibling separation and nested containment. For each frame inventory every visible object, establish an origin, and construct objects in one direction at a time according to their relationships to origin and neighbors. Assign stable IDs and preserve native SVG coordinates and transforms. Fill omissions before submission; an inventory in desc or empty placeholder is not visible construction. Preserve uncovered text, borders, arrows and details during any replacement. Preserve colors, gradients, opacity, CSS inheritance and light-on-dark contrast. Cuboids must have the original main-face slant, visible side faces, shared edges, divisions and block count. Arrowhead tips and shaft endpoints must coincide, with original direction, size, corners, connections and clearance. Repair endpoint/length errors at the endpoints, not just by translation. Formula repairs concern actual compilation/symbol/subscript errors, not clear text with a different font. Edit within declared issue scope, preserve neighbors, honor dependencies and retain stable IDs. Host safety, resource, scope and read-only geometry checks apply equally; failures roll back. Execution never constitutes visual acceptance.'''
COMMON_CONDITIONAL_POLICY = '''Use only capabilities in availability_manifest. If code_methods is true, registered SP/BP/TP, crop and color methods are available according to their supplied documentation. If false, first output complete visible native SVG and repair with generated_python using Python standard-library XML/math and your own geometry; do not request module operations, library imports, host measurements, crop/color methods or convergence repairs. For S1/D use registered constructors when available; otherwise construct the geometry and arrows yourself with the same visual requirements. If SAM is available and matching assets exist, first construct visible SVG then bind confirmed assets and replace only covered construction; preserve original block coordinates and relative arrangement. If assets are absent or uncertain, retain complete SVG construction. Unsupported declarations must never be emitted. E/F require the same declared alignment/contain/separate checks and two successful read-only checks; automatic convergence repairs are available only with code_methods. When unavailable, set repairs to [] and repair geometry yourself. Unresolved conditions must remain reported.'''

PROGRAM_SHAPE = '''Programs are {id,issue_ids,image_id,base_revision,phase:preconstructor|reconstructor,route:module_program|generated_python,target_ids,depends_on:[],rcd_predescription,args?,source_code?,relations?,convergence?}. generated_python receives INPUT_SVG and OUTPUT_SVG file paths; parse with xml.etree.ElementTree and write the complete SVG to OUTPUT_SVG. Target IDs must exist and belong to the issue scope; shared target edits require dependencies. D and S2 programs have depends_on: []. For E/F specify convergence={max_iterations:6,alignment_checks:[],repairs:[]}. E requires checks {id,target_ids,reference_ids,mode:center_x|center_y|left|right|top|bottom,tolerance:0.5,reference_evidence}. F requires relations {id,predicate:contain|separate,subject_id,object_id,reference_evidence,padding|min_gap}; padding and min_gap must be positive. Relations reference current SVG IDs. Return unresolved issues honestly.'''

def blocks(policy):
    p=normalize_capabilities(policy)
    availability=json.dumps({'version':p['version'],'sam':p['sam'],'code_methods':p['code_methods'],
       'repair_routes':['module_program','generated_python'] if p['code_methods'] else ['generated_python'],
       'common_host_services':['SVG rendering','same 1/2 comparison crops','ID navigation','read-only quality guards']},sort_keys=True)
    return {'common_quality':COMMON_QUALITY,'common_conditional_policy':COMMON_CONDITIONAL_POLICY,'availability_manifest':availability}

def block_hashes(policy):
    return {k:hashlib.sha256(v.encode()).hexdigest() for k,v in blocks(policy).items()}

def common_prompt(policy):
    return '\n'.join(k+'\n'+v for k,v in blocks(policy).items())

def repair_prompt(policy, *, followup=False):
    shape=PROGRAM_SHAPE if normalize_capabilities(policy)['code_methods'] else PROGRAM_SHAPE.replace('route:module_program|generated_python','route:generated_python')
    return common_prompt(policy)+'\n'+shape+ ('\nThis is the one-time receipt-driven followup. Address only listed unlanded issues using the latest SVG. Return listed issues unchanged; do not add issues.' if followup else '\nRepair the identified issues in one batch. Preserve inspection order and supplied original/current comparisons.')
