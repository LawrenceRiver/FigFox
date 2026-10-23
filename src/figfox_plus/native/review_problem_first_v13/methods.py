"""Case-independent review methods, bound to the real TP/SP/BP implementation.

Only explicit package modules are inspected. No run directories, task reports,
annotations or private evaluation files are searched or loaded.
"""
from copy import deepcopy
import hashlib
import inspect
import json

from ...sp.catalog import CATALOG
from ...sp import geometry, content, arrows, compiler
from .. import tp_v2, sp_v2, repair_toolbox
from ..single_call.qlist import QLIST

ORDER = ('E', 'F', 'B', 'A', 'S1')
_LOCATION = (
    'Describe the primary subject, reference objects, nearby text, colors, and relative spatial '
    'relationships (up/down/left/right) before binding the stable object identity in the current SVG; '
    'perform independent semantic localization in the original figure without inheriting TP coordinates '
    'from the current render.'
)
_RCD = (
    'Record real execution only: issue and program identities, method version, input and output '
    'revisions, actual parameters or code hash, results and errors, fallback chains, target-object and neighbor '
    'checks, and items still pending visual verification. Pre-descriptions cannot substitute for confirmed repairs.'
)
_POSITION_CHECK = (
    "Remeasure the updated object; check the target object's own relationships first, then check surrounding neighbors and "
    'affected connections. Passing mechanical checks with zero alarms still requires visual comparison against the original figure.'
)

# These are generic methods, not image-specific repair prescriptions.
_DETAILS = {
 'A': {
  'observe': ['Inspect factual meaning of text, terminology, spelling, and formulas; also check semantic icon identities, arrow directions, duplicate arrowheads, missing connections, and structural members. Replacing an icon with another symbol type is not an ignorable style difference, and relationship errors are not similarity issues.'],
  'counterevidence': ['Do not forcibly replicate errors caused by minor printing artifacts in the original figure; mark uncertain when lacking reliable knowledge, and do not fabricate domain conclusions.'],
  'prepare_parameters': ['Bind current text or formula objects; provide old content, new content, justification for correction, and styles to preserve.', 'Record dependencies on subsequent B typesetting steps; object width may change after modifying content.'],
  'execute': ['Modify valid text nodes via BP bp_patch text; for formulas, update tex and construct with SP formula.', 'Verify composition when handling mixed glyphs or multi-line structures; bp_patch.text removes child nodes and must not erase existing typesetting without planning.'],
  'postcheck': ['Reverify factual meaning and unchanged content; proceed to B for rendering, measurement, and layout after content changes.', _POSITION_CHECK],
  'fallback': ['Retain as unresolved when knowledge basis is insufficient rather than forcing edits; rollback the transaction upon execution failure.'],
  'methods': ['bp_patch','sp_replace'],
 },
 'B': {
  'observe': ['Different fonts or slight font-size differences are not issues as long as rendering is legible and largely consistent across the same figure. Existing uniform formatting is preserved. Do not change font if the text renders correctly as-is.', 'Formulas must compile using local MathJax base, ams, and newcommand packages. Only compilation failures, incorrect sub/superscripts, or compilation errors in symbols such as radicals are recorded as issues.'],
  'counterevidence': ['Do not treat font family or minor font size differences as errors. Do not attribute all layout conflicts to font issues; identical content with misplaced positions should be handled by E/F.'],
  'prepare_parameters': ['Identify object identity, code location, and styles in current SVG; text x/y is the baseline, while formula x/y is the top-left of the viewport.', 'Prepare kind, data, measurement_viewport, and target_tp; keep the construction viewport separate from the current render target region, and preserve styles of non-problematic text.'],
  'execute': ['Construct via SP text/formula and run sp_replace after measurement; formulas are rendered by existing local MathJax; transform the whole group rather than individual glyphs.'],
  'postcheck': ['Inspect the genuinely rendered symbols and styles; successful compilation does not substitute for correctness; update identity and measurement after construction before layout adjustment.', _POSITION_CHECK],
  'fallback': ['Record an error if unsupported formula commands or font dependencies are unavailable; rollback and do not replace with empty objects.'],
  'methods': ['sp_replace','measure','tp_transform'],
 },
 'C': {
  'observe': ['Compare source and target, each line segment, bend points, angles, curve forms, and missing segments; describe between which two neighbors the route passes and its relative clearance.'],
  'counterevidence': ['Intentional clearances or curves in the original figure must not be forcibly connected to frames or straightened; isolated arrowhead issues belong to D.'],
  'prepare_parameters': ['Read current paths and endpoints; determine each segment route and neighbor constraints based on original figure semantics, and prepare d/points or complete waypoints.'],
  'execute': ['Update path d/points via BP bp_patch; if reconstruction is needed, specify route and waypoints via SP arrow.', 'Recheck the entire line after adding missing segments; do not rely on TP to automatically route complex polylines.'],
  'postcheck': ['Verify traversed regions for each segment, corner angles, connections with frames, and whether new occlusions are introduced; then proceed to D to check head and shaft.', _POSITION_CHECK],
  'fallback': ['Retain as unresolved if the route cannot be reliably determined; rollback the entire modification if an invalid path is generated or connections are broken.'],
  'methods': ['bp_patch','sp_replace'],
 },
 'D': {
  'observe': ['Inspect missing arrows, duplicates, and directions via PNG-to-PNG comparison; do not guess counts from SVG node counts.', 'Sequentially check whether the shaft is exposed according to the original figure, connected to frame or leaving clearance, arrowhead shape and pixel size at the same scale, and coincidence between the arrowhead tip and the shaft endpoint.'],
  'counterevidence': ['Shaft exposure itself is not an error; if exposed in the original figure, it should also be exposed in the current render. Connecting to a frame or leaving clearance is determined by the original figure.', 'Triangles can be isosceles or equilateral without forcing equilateral; tips connect to endpoints rather than line midpoints.'],
  'prepare_parameters': ['Specify route, direction, waypoints, head_length/head_width, stroke_width, and color; estimate arrowhead size under equal display scale.', 'Check whether the arrow is double-headed; when missing, prepare new object identity and insertion container; when existing, preserve replacement identity relationships.'],
  'execute': ['Construct via SP arrow; draw the shaft underneath the arrowhead, with marker tip coinciding with path endpoint. Supplement connecting lines and routes via BP as needed.', 'Run all four standard checks after patching missing arrows.'],
  'postcheck': ['Check shaft exposure, frame connection or clearance, arrowhead size and direction, whether the arrowhead tip coincides with the shaft endpoint, and duplicate arrows; correlate with E alignment and C routing.', _POSITION_CHECK],
  'fallback': ['Rollback upon construction or connection failure; complex obstacle avoidance requires explicitly rewritten routes, as existing SP does not automatically avoid obstacles.'],
  'methods': ['sp_replace','bp_add','bp_patch'],
 },
 'E': {
  'observe': ['Proactively compare group-to-group center axes, absolute distances from left/right edges to axis, vertical matching heights, shaft lengths, centers, edges, and equal-spacing relationships.', 'A group may include inner/outer frames, text, and multiple members; identify bound groups first, and do not look only at individual small objects.'],
  'counterevidence': ['Alignment or symmetry must have justification from the original figure; asymmetrical structures in the original figure must not be forcibly equalized.'],
  'prepare_parameters': ['List bound members, reference group, alignment axis, and internal relative positions to preserve; read current group TP and neighbors.', 'Calculate the required movement or member adjustments in the current SVG based on relationships in the original figure; use root coordinate transformations for nested objects rather than inadvertently modifying local coordinates.'],
  'execute': ['Fine-tune coordinates for bound groups via BP/TP; tp_align supports standard modes, while complex mirrored relationships use explicitly calculated tp_transform.', 'Do not alter content casually; when length genuinely requires modification, combine with independent construction steps from C/D.'],
  'postcheck': ['Remeasure group alignment, member completeness, and arrow connections, verifying that inner and outer frames have not separated.', _POSITION_CHECK],
  'fallback': ['Mark uncertain when relationships are unclear; rollback and redetermine the binding set if bound movement disrupts structures.'],
  'methods': ['measure','tp_align','tp_transform','bp_patch'],
 },
 'F': {
  'observe': ['Inspect separation, margin clearance, and containment relationships across at least two parties: text, formulas, geometry, images, frames, ellipsis marks, dashed continuations, and connections. Overlapping arrangements of geometry and text also count.', 'Determine whether the cause is the frame, text, or positioning, which may be multiple. Resize the container when a frame is too small; do not just move the content. Touching edges in the current render when clearance exists in the original figure must also be inspected; valid containment and overlaps inherent to the original figure are not errors.'],
  'counterevidence': ['The tightest bounding box enclosing visible glyphs is not required to be square; axis-aligned TP intersections are only candidates, as sparse graphics might not actually collide.'],
  'prepare_parameters': ['Semantically locate all participating objects and measure current tight TP; define each relationship justified by the original figure.', 'Consult the original figure to determine whether to modify the text, upper frame, base frame, or multiple parties; prepare movement, scaling, or frame boundary coordinates while considering neighbors.'],
  'execute': ['Apply a TP transform/fit or modify the base frame via BP; remeasure within bounded turns until declared relationships produce zero alarms and visual appearance matches the original figure.'],
  'postcheck': ['Pass 1 checks originally participating objects; Pass 2 specifically checks neighbors, new TP alarms, and associated neighbor objects.', 'Visual discrepancies remain non-compliant; reclassify cascading issues and do not merely silence alarms.'],
  'fallback': ['Stop and record as unresolved when no progress is made or the local turn limit is reached; rollback failed attempts, and do not move objects indefinitely to squeeze neighbors.'],
  'methods': ['measure','check_tp','tp_transform','tp_fit','bp_patch'],
 },
 'S1': {
  'observe': ['Inspect missing parts, subject structure, closed faces, shared edges, depth, occlusion, texture, relative size, and extraneous edge lines via PNG-to-PNG comparison.', 'Examine overlap clues before estimating original figure dimensions; overlap does not automatically prove incorrect object dimensions; it may instead be caused by incorrect positioning or the base frame.'],
  'counterevidence': ['Highly similar content is not reported as a content error due to tiny pixel differences; distinct from factual content issues in A.', 'Successful construction or deleting black fill does not mean the geometric structure has been reconstructed correctly.'],
  'prepare_parameters': ['Perform independent semantic localization of the object and surrounding references in the original figure, extracting only dimensions and relationships; then locate neighbors, containers, and anchor edges in the current SVG to determine placement coordinates.', 'For simple geometry, prepare construction parameters, shared edge vectors, face colors, and composite occlusion ordering; for photos, prepare independently located original source_crop and current target_tp.'],
  'execute': ['For simple regular geometry, prioritize SP geometry construction before rendering; complex assets can directly use sp_photo.', 'Original figure crops must be complete and clean with extraneous edge lines removed; check subject integrity after RMBG, and preserve the clean original crop if the subject is damaged.', 'Prioritize raster for precise depiction; vector may be chosen for abstract depiction. The existing vector backend does not imply an implemented dedicated micro-particle Bezier algorithm.', 'Select alignment edges according to current render containers and neighbors, placing proportionally; do not mistake original figure pixel coordinates for SVG coordinates.'],
  'postcheck': ['Visually inspect geometric structure or crop integrity, background damage, anchor edges, and dimensions; compare remaining container margins.', _POSITION_CHECK],
  'fallback': ['Switch to sp_photo if geometric visual replication fails; mechanical failures can pre-declare local fallback, whereas visual failures require seeing the new image before deciding.', 'Revert to the original crop if RMBG damages the subject; relocate independently if cropping is inaccurate, without borrowing TP from current render to crop original figure.'],
  'methods': ['sp_replace','sp_photo','measure','tp_fit','tp_transform'],
 },
 'S2': {
  'observe': ['Compare planar contours, orientations, boundaries, open/closed states, and fill regions between the original figure and the current render.'],
  'counterevidence': ['3D face and depth structure errors belong to S1 and must not be concealed by merely modifying 2D fills.'],
  'prepare_parameters': ['Semantically locate the current shape, extracting node attributes or vertices; determine new contours from the original figure while preserving position relationships in the current render.'],
  'execute': ['Modify d/points or corresponding geometric attributes via BP; or replace using planar constructors in SP.'],
  'postcheck': ['Check contour, orientation, self-intersection, and edge fill.', _POSITION_CHECK],
  'fallback': ['Construct a new object when unexpressible with existing attributes; mark explicitly as unresolved if isolated execution capability is unavailable.'],
  'methods': ['bp_patch','sp_replace'],
 },
 'S3': {
  'observe': ['Check colors of semantically corresponding faces, text, arrows, backgrounds, and strokes object by object, distinguishing shadows and anti-aliasing from true color patch differences.'],
  'counterevidence': ['Identical coordinates across both figures do not guarantee identical content; do not sample colors from blended edges or backgrounds to replace the subject.'],
  'prepare_parameters': ['Independently locate a clean ROI for the corresponding component in the original figure; bind the fill/stroke/CSS or shared references actually taking effect in the current render.'],
  'execute': ['sample_colors returns the modal color of the ROI using OpenCV; apply the actual sampled result through BP rather than sampling without making the corresponding modification.', 'Shared styles or symbols affect other objects; verify scope before modifying.'],
  'postcheck': ['Verify via rendering that colors take effect, modify the correct component, and do not alter unrelated shared objects.'],
  'fallback': ['Reselect a clean area or retain as uncertain when gradients, textures, or blended ROIs cannot be represented by a mode; do not fabricate a flat color.'],
  'methods': ['sample_colors','bp_patch'],
 },
 'S4': {
  'observe': ['Inspect paired enlarged PNGs, count visible semantic units while accounting for occlusion, duplicates, and missing items; do not count SVG paths in place of objects.'],
  'counterevidence': ['An object may consist of multiple paths; an occluded member is not equivalent to a missing member.'],
  'prepare_parameters': ['List original and currently visible units and their differences; bind repeated groups and insertion containers, preparing identities for addition/removal, arrangement, and occlusion ordering.'],
  'execute': ['Perform atomic addition, removal, or combination via BP, reconstructing via SP array/cluster when necessary; preserve actual differences between units.'],
  'postcheck': ['Recheck PNG counts and occlusion; newly added objects must be genuinely visible.', _POSITION_CHECK],
  'fallback': ['Mark uncertain when resolution is insufficient; rollback the entire transaction if additions/removals are incomplete or neighbors are damaged.'],
  'methods': ['bp_add','bp_remove','sp_replace'],
 },
}


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def build_method_pack(qlist=None, registry=None, *, capabilities=None):
    """Return a detached JSON-compatible versioned method pack.

    Optional arguments verify the caller's taxonomy/registry against this
    versioned implementation; arbitrary caller prose or callables are not read
    into the model context. Sources are readable implementation excerpts, not a
    standalone runtime or a grant to execute code outside an isolated executor.
    """
    from ..capabilities import normalize_capabilities,capability_hash
    from ..capability_prompts import COMMON_QUALITY,COMMON_CONDITIONAL_POLICY
    from .execution_contract import build_execution_contract
    policy=normalize_capabilities(capabilities)
    if not policy['code_methods']:
        pack={'format':'review-method-pack-v1','assignment':policy,'capability_hash':capability_hash(policy),
              'runtime_contract':build_execution_contract(policy),'inspection_order':list(ORDER),
              'sources':{},'constructors':[],'helpers':{},'operation_contract':{},
              'cards':[],'common_quality':COMMON_QUALITY,'common_conditional_policy':COMMON_CONDITIONAL_POLICY}
        pack['version_hash']=_digest(pack)
        return pack
    if qlist is not None and [q.get('id') for q in qlist] != list(ORDER):
        raise ValueError('Q list must contain the five priority categories')
    if registry is not None and (set(registry) != set(CATALOG) or any(
            registry[name].get('parameters') != CATALOG[name]['parameters'] or
            registry[name].get('callable') is not CATALOG[name]['callable'] for name in CATALOG)):
        raise ValueError('registry must match the actual executable catalog')
    sources = {}
    def source(obj):
        key = obj.__name__ if inspect.ismodule(obj) else obj.__module__ + ':' + obj.__name__
        if key not in sources:
            code = inspect.getsource(obj)
            sources[key] = {'code':code, 'sha256':hashlib.sha256(code.encode()).hexdigest(), 'readonly':True,
                            'scope':'implementation source; imports/dependencies supplied by runtime'}
        return key
    # Shared dependencies are embedded once; no arbitrary path or caller source.
    for module in (geometry, content, arrows, compiler):
        source(module)
    constructors = []
    for name, entry in CATALOG.items():
        card = {k:deepcopy(v) for k,v in entry.items() if k not in {'callable','examples'}}
        fn = entry['callable']
        card.update(callable=fn.__module__+'.'+fn.__name__, signature=str(inspect.signature(fn)),
                    source_ref=source(inspect.getmodule(fn)) if inspect.getmodule(fn) is geometry else source(fn))
        constructors.append(card)
    helpers = {}
    for fn in (tp_v2.selection,tp_v2.transform,tp_v2.align,tp_v2.fit,
               sp_v2.construct,sp_v2.measure_construction_adaptive,sp_v2.replace,
               repair_toolbox._run_operation,repair_toolbox._patch,repair_toolbox._add,
               repair_toolbox._remove,repair_toolbox._photo):
        helpers[fn.__name__] = {'callable':fn.__module__+'.'+fn.__name__,
                                'signature':str(inspect.signature(fn)), 'source_ref':source(fn)}
    from ..single_call.executor import _sample_colors
    helpers['sample_colors'] = {'callable':_sample_colors.__module__+'._sample_colors',
                               'signature':str(inspect.signature(_sample_colors)), 'source_ref':source(_sample_colors)}
    cards=[]
    for base in sorted((q for q in QLIST if q['id'] in ORDER),key=lambda q:ORDER.index(q['id'])):
        card = {k:deepcopy(base[k]) for k in ('id','name','definition')}
        card.update(deepcopy(_DETAILS[base['id']]), semantic_location=_LOCATION, rcd=_RCD)
        if base['id']=='S1':
            card.update(name='Defective regular cuboid',definition='The object shown in the original figure is a cube or cuboid whose body may be divided into segments. In the current render, faces are missing, flattened into 2D, adjacent faces do not share edges, or division lines bend into sharp angles or run through the middle to form triangular shapes, becoming garbled. Having three outer shell faces does not substitute for correct segmentation. Objects with incorrect position or overlap but valid 3D structure do not belong here.',
                observe=['Inspect the main face of the regular solid, adjacent faces sharing edges, and body segments against the original figure. Division lines must be parallel to corresponding edges, and cells must be closed parallelograms. Record if faces are missing, flattened into 2D, adjacent faces do not share edges, division lines bend into sharp angles, triangular punctures appear in the middle, or segment counts/orientations do not match. Do not excuse an object just because three faces remain or endpoints fall on edges. The top edge of the main face must have the same slant as the original figure. Both the top face and the side face must be visible. Record multiple stacked blocks flattened into a single flat strip. Record blocks where division lines bend into sharp angles; do not excuse them just because they still resemble a block overall. Inspect every divided cuboid individually, including the smallest block. Record it if the division lines do not form closed parallelograms.'],
                prepare_parameters=['Bind the target cuboid in the current render. Prepare origin, u, v, and depth (or depth_length and depth_angle). When segmented, prepare lattice divisions based on how many cells are on the front face and side face in the original figure. Sample face colors from the original figure.'],
                counterevidence=['Do not report objects that are already correct cuboids. Color, photo, and icon differences do not belong here. Malformed division lines are not textures.'],
                execute=['Use sp_replace with kind as geometry. When unsegmented, data.shape is cuboid. When segmented, including malformed division lines, data.shape is lattice with divisions based on cell counts on the front and side faces in the original figure; it remains the same object, do not retain original polylines. measurement_viewport encloses construction, target_tp uses extent of object in current render, mode is contain. Do not draw polygons by hand, do not paste photos. Set u and v to match the slant of the main face in the original figure. Ensure depth makes the side face visible. Multiple blocks must match the block count in the original figure; do not arrange into a single flat strip.'],
                fallback=['Retain as unresolved if SP construction fails; do not fall back to photo crops.'],
                methods=['sp_replace','measure'])
        if base['id']=='A':
            card.update(name='Knowledge, Semantic Symbol, and Key Connection Errors',definition='Knowledge content, semantic icon identities, arrow directions/duplicates/missing items/connections, or missing structural members causing expression errors; usable abstract styles and subtle textures do not belong here.',
                prepare_parameters=['Determine the subtype first. For text and formulas, prepare old content, new content, justification, and styles; for icons, prepare original figure identity, complete asset, and current container; for arrows, prepare start/endpoints, heads, routes, connecting frames, and neighbors.',
                    'After localizing arrows using upstream SAM candidates, confirm in paired PNGs; do not replace actual counts with node counts or SAM corner counts. Bind all component paths, markers, and related frames to avoid modifying only one duplicate arrowhead.',
                    'After confirming missing members in original and current PNGs, prepare the complete structure, insertion container, and stable new IDs; do not count paths as semantic members.'],
                execute=['Text: Modify content via BP, construct via SP formula if necessary, then proceed to B. Icons: Insert complete original figure crop via SP photo or construct via reliable SP to preserve semantic identity.',
                    'Arrows: First fix the complete route and bend points via BP, then construct via SP arrow or modify shaft and head via BP; check whether the shaft should be exposed, connect to frame or leave clearance, verify arrowhead pixel size at the same scale, and ensure the arrowhead tip coincides with the line endpoint, and draw the shaft underneath the arrowhead. Direction is determined by the original figure. For duplicate heads, remove only demonstrably redundant members.',
                    'Missing arrows or members: Supplement via BP add or construct via SP, then thoroughly check direction, connection, alignment, and neighbors. Modifying shared markers must be scoped strictly to actually affected objects.'],
                postcheck=['Recheck knowledge, icon identity, or arrow start/endpoints, head-and-shaft, count, and connections by subtype. Check typesetting for text, and check E/F for structures and connecting lines; do not check text content alone.',_POSITION_CHECK],
                fallback=['Mark uncertain when knowledge or routing evidence is insufficient; rollback the transaction upon failure and retain explicit unresolved items. Abandon icon insertion if the crop is incomplete.'])
            card['methods']=['bp_patch','bp_add','bp_remove','sp_replace','sp_photo','measure']
        if base['id']=='E':
            card['observe'].append('Recognize bound groups, reference axes, group symmetry, and matching heights first before comparing members and neighbors. Standards come exclusively from the original figure; self-consistency between left and right in the current render is not an original-figure justification. Having the same start point or bottom edge does not mean the other end is aligned. Paired arrows symmetrical in the original figure and large schematic icons must both be checked against the axes of the original figure.')
            card['execute'].append('When endpoint height or length is incorrect, modify the endpoint or length according to corresponding relationships in the original figure; do not simply move the entire line to the center.')
        if base['id']=='F':
            card['observe'].append('Do not judge an object as normal just because it is roughly within a container: check margin clearance between visible subjects and frame lines on each side; containment and touching edges can occur simultaneously. Ellipsis marks, the last line of text, protruding geometry edges, and connecting line heads and shafts also count as visible subjects.')
            card['execute'].append('To restore frames, restore the top, bottom, and width of the frame itself according to the original figure before moving enclosed text. Separate sibling adjacent frames if they are separated in the original figure. Place ellipsis marks and marker dots back into the gaps. Do not shrink text first to conceal an erroneous frame.')
        if base['id']=='B':
            card['execute'].append('If reconstructing XML text structures manually, distinguish parent text, child text, and tail; make clear whether replacing the entire paragraph or performing a local replacement, and do not append a new formula while leaving the old string behind. Recheck the complete visible text sequence after rendering to avoid duplication or loss.')
            card['execute'].append('Check CSS inheritance and specificity first: class rules may override SVG presentation attributes like font-size or fill. When modifying actual appearance, handle existing inline styles or corresponding stylesheets on the target rather than claiming a font-size/color change by merely writing an overridden attribute; verify changes with actual rendering and updated TP, and re-inspect adjacent icons and text.')
        if base['id']=='A':
            card['observe'].append('Individually enumerate small icons next to headings, inside cards, and beside legends, establishing correspondence between original figure and current render using adjacent text; compare the identity of represented objects one by one, checking whether they are missing or replaced by other symbols. Do not inspect only the largest graphic, and do not inspect only SVG image nodes.')
            card['observe'].append('First read the original figure arrow into start subject, end subject, main shaft, and heads at each end, then match the complete connection in the current render. Bidirectional relationships do not allow two misaligned overlapping shafts; when encountering nearby paths, verify whether lines are redundantly drawn, arrowheads overlap, or actual endpoint directions are incorrect. SAM candidates and SVG paths assist verification separately; do not judge direction solely by path coordinate sequence.')
        if base['id']=='E':
            card['observe'].append('Check center axes, matching heights at both ends, lengths, and spacing once for each bound group. Record if inconsistent with the original figure. Numerical differences alone do not equal errors, but do not generate another round of counter-evidence merely to dismiss them.')
            card['execute'].append('Length or endpoint height errors usually cannot be solved solely by moving the entire line; modify actual endpoints/segment lengths or reconstruct via SP arrow according to corresponding relationships in the original figure, while preserving connections and directions. Do not record a length deviation during inspection only to align the center during repair.')
        card['version_hash'] = _digest(card)
        cards.append(card)
    from .execution_contract import build_execution_contract
    pack = {
        'runtime_contract':build_execution_contract(policy),'assignment':policy,'capability_hash':capability_hash(policy),
        'format':'review-method-pack-v1', 'inspection_order':list(ORDER),
        'repair_order':{'main':['A','B','S1','E','F'],'dependency_insertions':[]},
        'principles':{'tp_domain':'current_svg_only','diagnostic_crops':'immutable upstream paired inputs; never generated here',
          'inspection':'one look per category, then decide; crops already in the request are the zoom',
          'semantic_location':_LOCATION,
          'tolerance':'Printing artifacts in the original figure can be tolerated; highly similar content is not reported as a content error based on pixel differences; do not exempt overlaps, missing items, reversed directions, or structural distortion.',
          'ordering':'Content/Construction -> Stable Identity Mapping -> Latest Measurement -> Layout/Connection -> Target-Object Check -> Neighbor Check',
          'isolation':'Method sources are strictly limited to explicit package code; historical answers, callout annotations, or private acceptance criteria are forbidden as inputs; new code may only enter the verified isolated executor.'},
        'operation_contract': {
          'envelope':'method, target_ids, args; method is not nested in args',
          'coordinates':'TP/world insertion: current SVG root viewBox; BP scalar attributes: element-local; source_crop and sample ROI: independently located original pixels',
          'measure':{'args':{},'returns':'objects keyed by current IDs with measured tight_bbox/status'},
          'check_tp':{'args':{},'returns':'declared relationship report; not automatic visual judgment'},
          'tp_transform':{'args':{'world_matrix':'six finite invertible affine numbers'},'returns':'selected_ids, before, after, world_matrix'},
          'tp_align':{'args':{'reference_ids':'independent current IDs','mode':'center_x|center_y|left|right|top|bottom'},'returns':'TP transform report'},
          'tp_fit':{'args':{'target_tp':'left,top,right,bottom','mode':'contain|stretch'},'returns':'TP transform report'},
          'sp_replace':{'args':{'kind':'geometry|frame|text|formula|arrow','data':'matching constructor parameters','measurement_viewport':'local construction bounds','target_tp':'current scene bounds','mode':'contain|stretch'},'returns':'replacement_id, constructor_data, construction_measurement and replacement report'},
          'sp_photo':{'args':{'source_crop':'independent original pixel [x,y,width,height]','target_tp':'current scene bounds','representation':'raster|vector','remove_background':'boolean, default true','backend':'vector backend, default vtracer','padding':'nonnegative','mode':'contain|stretch'},'returns':'replacement_id, asset, source_mapping, representation, padded_target_tp'},
          'bp_patch':{'args':{'attributes':'allowed scalar SVG attributes by tag; see constraints','text':'optional replacement for text node, removes existing children'}, 'constraints':{'attributes':sorted(repair_toolbox._PATCH_ATTRS), 'geometry_by_tag':{k:sorted(v) for k,v in repair_toolbox._GEOMETRY_BY_TAG.items()}, 'style':sorted(repair_toolbox._STYLE_ATTRS), 'href':'local use references only, checked for scope and cycles'}, 'returns':'target_ids, applied attributes and text'},
          'bp_add':{'args':{'parent_id':'selected g/svg ID or @parent for common container of targets','svg':'one to five inert fragments; unique IDs on every new element'},'returns':'added_ids, resolved_parent_id, world_to_parent_matrix'},
          'bp_remove':{'args':{},'returns':'removed_ids'},
          'sample_colors':{'args':{'regions':'list of independently located original pixel xywh ROIs'},'returns':'samples with modal_rgb/modal_hex; connect returned value to actual patch'},
          'bp_program':{'args':{'operations':'ordered native TP/SP/BP operations'},'returns':'real operation reports; failing transaction must not partially apply'},
        },
        'cards':cards, 'constructors':constructors, 'helpers':helpers, 'sources':sources,
        'capabilities':{'automatic_visual_acceptance':False,'automatic_original_localization':False,
          'server_side_execution_verified':False,'micro_bezier_specialized_backend':False,
          'geometry':'Genuine constructors are listed under constructors; they do not automatically recover unknown perspective or textures.',
          'photos':'sp_photo crops according to provided original figure ROIs; RMBG and vectorization depend on available backends and do not automatically judge subject damage.',
          'generated_code':'Executability is determined by isolated executor probes; this method pack grants no host execution privileges.'},
        'rcd_contract':_RCD,
    }
    pack['version_hash'] = _digest(pack)
    return pack
