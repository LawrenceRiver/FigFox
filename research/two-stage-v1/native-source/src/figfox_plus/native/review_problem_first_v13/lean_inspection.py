"""One look per category. The model decides; the host does not demand a second pass."""
from ..review_problem_first_v3.inspection_contract import inspection_regions


CATEGORIES = ('F', 'E', 'B', 'S1', 'D', 'S2')
PROMPT = '''This is the first request. Inspect all six categories together: F Overlap and Overflow, E Alignment and Symmetry, B Typesetting and Formulas, S1 Regular Cuboids and Lattices, D Arrow Geometry, and S2 Inconsistent Patches. programs must be an empty array []; do not write repair code.
Do not record missing icons in the preceding categories. Record defects upon observation. Use confirmed for decision in F and E.
F - Overlap and Overflow. Touching with zero clearance also counts:
1. Arrangements of geometric objects and text pressing against each other, or the same arrow / arrowhead drawn in two layers.
2. Text, titles, or geometric objects that should be inside a frame, but are flush against edges or extending outside the frame. State reasons first (can be multiple: frame, text, position).
3. Ellipses or dashed continuation lines remaining in old positions, or pressing against frame edges.
4. Content drawn outside the boundary of the overall figure.
Do not record overlaps that are present in the original figure itself.
E Alignment and Symmetry. Check paired, symmetrical, coaxial, and equal-height structures against the original figure, pair by pair. Do not report structures that are originally asymmetrical in the original figure, and do not force the current render into an artificially averaged arrangement. Appearing aligned between left and right in the current render itself cannot substitute for symmetry in the original figure.
1. Paired arrows: height at both ends, shaft length, and distance to center axis. Sharing the same start or bottom edge does not mean the other end is aligned.
2. Large schematic icons and large geometric objects: center, edges, or axes must align.
3. Members of the same group: center axis, height at both ends, length, and spacing must all be examined.
B Typesetting and Formulas. Font differences do not matter, as long as rendering is clear and generally uniform across the same figure. Retain existing uniform formats. Do not change text that already displays correctly.
Formulas must compile using local MathJax base, ams, and newcommand. Record only these types, with decision as confirmed: incorrect subscripts or superscripts; miscompiled symbols such as square roots; formula fails to compile. If content is identical and only position is wrong, categorize under E or F. If not as certain, mark as uncertain.
S1 Regular Cuboids and Lattices. The object shown in the original figure is a cube or cuboid. The body can be divided into segments, where division lines are parallel to corresponding edges, and grid cells are closed parallelograms. When the current render is no longer a correct cuboid due to drawing method, use confirmed for decision: missing a face, squashed into a flat plane, or an adjacent face does not share an edge with the main face; or the outer shell is present, but division lines are bent into sharp angles, run through the middle to form triangular shapes, are not parallel to edges, or segment count or direction does not match the original figure, looking visually garbled. Do not overlook division lines just because three faces are still present and endpoints fall on the edges. Do not treat malformed lines as texture. If geometry is already correct and only position or overlap is wrong, categorize under E or F. Do not record color differences. The top edge of the main face must have the same slant as in the original figure; do not turn it into a front-facing face with horizontal and vertical edges. Both top face and side face must be visible. If the original figure has multiple cuboids stacked in a pile, and the current render arranges them in a single row or line of flat blocks, record this as well; the block count and stacking arrangement must match the original figure. Also record any piece where division lines bend into sharp angles; do not overlook it just because it still resembles a block overall. Every cuboid with divisions must be inspected individually, including the smallest one. Record it if the division lines do not form closed parallelograms. Perform a separate pass over the provided 1/2 Crop pairs specifically for regular cuboids.
D Arrow Geometry. Check only these items: the arrowhead tip and the shaft endpoint must coincide; direction must match the original figure; arrowhead size must match its pixel dimensions in the original figure; whether start and end land on frames follows the original figure. Record if missing, extra, reversed in direction, tip misaligned, head size incorrect, hanging in empty space when it should connect to a frame, or connected when it should leave space. Use confirmed for decision. Do not treat arrows as overlap.
S2 Inconsistent Patches. Perform a separate pass over the provided 1/2 Crop pairs for this category, cross-referencing the small patches inside. Record if color is completely inconsistent with the original figure, or if this element is completely missing. Use confirmed for decision. These require patching. Minor color differences or incorrect positions do not belong to this category.
Perform one general inspection pass by comparing the full original figure with the current render, the current SVG, and the provided 1/2 Crop pairs. For Regular Cuboids and Lattices and Inconsistent Patches, perform one additional separate pass over the 1/2 Crop pairs for each category. Do not list region numbers; do not write counter-evidence for areas without problems.
Output compact_category_sweeps in order F,E,B,S1,D,S2. For a category without problems, candidates is an empty array []. Do not output other_sweep.'''

REPAIR_PROMPT = '''This is the second request. Write programs collectively for the listed F, E, B, S1, D, and S2 categories. Echo back issues as-is; do not add new issues.
For F, repair according to the identified reason; multi-step operations are permitted. For frames, modify container boundaries; do not shrink content into an overly small frame. For text, modify text or symbols. Move the element only when the identified issue is positional. Ellipses and dashed lines must follow the row they belong to.
In relations, use predicate; do not write kind. For separate, specify a positive min_gap; for contain, specify a positive padding. Use legal_overlap only when the overlap is present in the original figure itself. Frame modifications belong in operations using bp_patch.
Every relation must match existing IDs in the current SVG; otherwise, the program will not execute. contain: specify content as subject_id and frame as object_id, or specify frame as container_ids and content as target_ids. separate: specify the two objects as subject_id and object_id, or write them in that order into target_ids. Do not put frames into neighbor_ids.
For E, when endpoint heights or arrow shaft lengths are incorrect, modify endpoints or lengths according to the original figure; do not merely translate the entire arrow to the center. Both symmetric sides must be modified. Align large icons to axes according to the original figure.
For B, repair only compilation failures, subscript/superscript errors, and compilation errors in symbols such as radicals. Use SP formula; tex commands are strictly limited to those compilable under base, ams, and newcommand. Do not modify text that already renders correctly merely for font uniformity. Move formulas as a whole unit, not individual glyphs.
For S1, use sp_replace with kind as geometry. If unsegmented, data.shape is cuboid. If the body in the original figure is divided into segments (including cases with malformed division lines), data.shape is lattice; set divisions to the cell counts on the front and side faces according to the original figure-it remains a single object; do not retain the original polylines. origin, u, and v define the main face; depth or depth_length plus depth_angle defines depth. Colors of each face follow the original figure. measurement_viewport encloses the construct; target_tp uses the extent of that object in the current render; mode is contain. Do not hand-draw polygons; do not paste photos. u and v must have the same slant as the main face in the original figure; if the top edge is slanted, do not make it horizontal. depth must ensure the side face is visible. If multiple blocks are stacked in a pile in the original figure, divide them into multiple cuboids matching the original block count; do not arrange them into a single flat strip.
For D, use sp_replace with kind as arrow. The arrowhead tip and the shaft endpoint must coincide. head_length and head_width follow pixel dimensions in the original figure. Direction follows the original figure. Connect start and end points to frames if they connect in the original figure, or leave clearance if they leave clearance. depends_on must be empty [] for arrow programs.
For S2, Inconsistent Patches. Where small patch color is completely inconsistent with the original figure, or this element is completely missing, use sp_photo to crop the corresponding region from the original figure and patch it in.
When using sp_photo, all fields are strictly required; missing any item causes execution to be skipped. args.source_crop specifies original figure pixels [x,y,w,h], which must enclose full_object_xywh and fall entirely within the original figure. args.crop_review is {object_complete:true, clipped:false, full_object_xywh:[x,y,w,h], edges_reviewed:{left:true,top:true,right:true,bottom:true}, evidence:all four edges of this element in the original figure fall inside the crop}. The key name is edges_reviewed; do not write sides. At the same level as method, provide source_location: {basis:original_semantic, description:this element in the original figure}. If unable to provide all fields completely, do not use sp_photo.
Each item in alignment_checks is {id,target_ids,reference_ids,mode:center_x|center_y|left|right|top|bottom,tolerance:0.5,reference_evidence}.
convergence is {max_iterations:6, alignment_checks, repairs:[{check_id, method:tp_align|tp_transform|tp_fit, target_ids, args}]}. check_id must match the id of a relation or an alignment_check.
Programs that are mutually independent must have depends_on as []. Programs containing only D or only S2 must have depends_on as an empty array [], so do not modify an object already modified by an earlier program. When other programs modify the same object sequentially, the subsequent program must list the id of the preceding program in depends_on.
Programs failing pre-checks will not execute. Do not write lengthy repair rationales.'''


def _object(properties, required=None):
    return {'type': 'object', 'properties': properties,
            'required': list(properties) if required is None else required, 'additionalProperties': False}


def _array(items):
    return {'type': 'array', 'items': items}


def build_schema(schedule, review_only=False):
    regions = inspection_regions(schedule)
    text = {'type': 'string'}
    refs = _array({'type': 'string'})
    region = {'type': 'integer', 'enum': [r['region'] for r in regions]}
    props = {}
    if not review_only:
        candidate = _object({
            'region': region, 'original_evidence': text, 'current_evidence': text,
            'decision': {'type': 'string', 'enum': ['confirmed', 'uncertain']},
            'issue_ids': refs,
        })
        props['compact_category_sweeps'] = _array(_object({
            'category': {'type': 'string', 'enum': list(CATEGORIES)},
            'whole_image_observation': text, 'svg_observation': text,
            'candidates': _array(candidate),
        }))
    props.update({name: _array({'type': 'object'}) for name in ('issues', 'programs', 'prior_issue_reviews')})
    return _object(props)


def _need(condition, message):
    if not condition:
        raise ValueError(message)


def _text(value, label):
    _need(isinstance(value, str) and bool(value.strip()), label + ' requires nonempty evidence')


def audit(schedule, plan, issues=None):
    report = {
        'coverage_kind': 'one_pass_decision',
        'records_complete': False, 'images_seen_verified': False,
        'semantic_completeness': 'not_assessed', 'visual_acceptance': 'not_assessed',
        'visual_passed': False, 'status': 'inspection_incomplete', 'errors': [],
        'limitations': ['One pass is a decision, not a second confirmation.',
                        'Execution and visual acceptance are separate.'],
    }
    try:
        catalog = inspection_regions(schedule)
        by_region = {r['region']: r for r in catalog}
        image_ids = {r['image_id'] for r in catalog}
        _need(isinstance(plan, dict), 'plan must be object')
        sweeps = plan.get('compact_category_sweeps')
        _need(isinstance(sweeps, list) and all(isinstance(s, dict) for s in sweeps), 'compact_category_sweeps required')
        _need([s.get('category') for s in sweeps] == list(CATEGORIES), 'category order must be ' + ' '.join(CATEGORIES))
        for sweep in sweeps:
            _text(sweep.get('whole_image_observation'), 'whole_image_observation')
            _text(sweep.get('svg_observation'), 'svg_observation')
            _need(isinstance(sweep.get('candidates'), list), 'candidates must be array')
        actual = plan.get('issues') if issues is None else issues
        _need(isinstance(actual, list), 'actual issues required')
        known = {}
        for issue in actual:
            _need(isinstance(issue, dict), 'issue must be object')
            ident = issue.get('id')
            _need(isinstance(ident, str) and bool(ident.strip()) and ident not in known, 'invalid/duplicate issue ID')
            _need(issue.get('category') in CATEGORIES and issue.get('image_id') in image_ids, 'issue category/image outside itinerary')
            _need(issue.get('decision') in ('confirmed', 'uncertain', 'preserved', 'duplicate'), 'invalid issue decision')
            known[ident] = issue
        linked = set()
        for sweep in sweeps:
            category = sweep['category']
            for row in sweep['candidates']:
                _need(isinstance(row, dict), 'candidate must be object')
                region_id = row.get('region')
                _need(type(region_id) is int and region_id in by_region, 'candidate region is not a host identity')
                _text(row.get('original_evidence'), 'candidate original_evidence')
                _text(row.get('current_evidence'), 'candidate current_evidence')
                decision = row.get('decision')
                _need(decision in ('confirmed', 'uncertain'), 'invalid candidate decision')
                refs = row.get('issue_ids')
                _need(isinstance(refs, list) and all(isinstance(i, str) for i in refs) and refs, 'candidate requires issue_ids')
                _need(len(refs) == len(set(refs)), 'duplicate issue reference')
                for ident in refs:
                    _need(ident in known, 'unknown issue reference')
                    issue = known[ident]
                    _need(issue['category'] == category and issue['image_id'] == by_region[region_id]['image_id'],
                          'candidate issue category/image mismatch')
                    _need(issue['decision'] == decision, 'candidate and issue decision mismatch')
                    linked.add(ident)
        required = {i for i, issue in known.items() if issue['decision'] in ('confirmed', 'uncertain')}
        _need(required <= linked, 'confirmed/uncertain issue lacks same-category candidate')
        report.update(records_complete=True, status='one_pass_recorded',
                      candidate_count=sum(len(s['candidates']) for s in sweeps), linked_issue_count=len(linked))
    except (ValueError, TypeError, KeyError) as exc:
        report['errors'].append({'code': 'invalid_lean_inspection', 'message': str(exc)})
    return report
