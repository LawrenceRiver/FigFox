"""One look per category. The model decides; the host does not demand a second pass."""
from ..review_problem_first_v3.inspection_contract import inspection_regions
from .source_geometry import DISCOVERY_POLICY, REPAIR_POLICY
from ..color_guard import BOUNDARY_DISCOVERY, BOUNDARY_REPAIR


CATEGORIES = ('F', 'E', 'B', 'S1', 'D', 'S2')
PROMPT = '''This is the first request. Inspect all six categories together: F Overlap and Overflow, E Alignment and Symmetry, B Typesetting and Formulas, S1 Regular Cuboids and Lattices, D Arrow Geometry, and S2 Inconsistent Patches. programs must be an empty array []; do not write repair code.
Record missing or semantically different icon patches under S2, not the other categories. Record defects upon observation. Use confirmed for decision in F and E.
F - Overlap and Overflow. Touching with zero clearance also counts:
1. Arrangements of geometric objects and text pressing against each other, or the same arrow / arrowhead drawn in two layers. Compare visible label and symbol counts with the original; asset pixels and traced paths can duplicate native text even when SVG text IDs are unique.
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
S1 Regular Cuboids and Lattices. Apply the source-dimensionality policy below before reporting flattened or malformed solids. Inspect each actual cuboid, including small divided ones, for parallel, closed cells, correct segment count and stacking; do not treat bent division lines as texture. Color differences alone do not belong here. Use the provided 1/2 Crop pairs to distinguish source faces from planar divisions.
D Arrow Geometry. Check only these items: the arrowhead tip and the shaft endpoint must coincide; direction must match the original figure; arrowhead size must match its pixel dimensions in the original figure; whether start and end land on frames follows the original figure. Record if missing, extra, reversed in direction, tip misaligned, head size incorrect, hanging in empty space when it should connect to a frame, or connected when it should leave space. Use confirmed for decision. Do not treat arrows as overlap.
S2 Inconsistent Patches and Structural Boundaries. Inspect full-figure structural outlines as well as the separate 1/2 Crop pairs for small patches. Record a missing original boundary, a visible stroke erased into its fill/background, a completely inconsistent patch color, or a completely missing element. Match each small icon or status badge to its original symbol and meaning: an unrelated number, checkmark or arrow is an inconsistent patch even if its color and placement match. Use confirmed for decision. Minor color differences or incorrect positions do not belong to this category.
Perform one general inspection pass by comparing the full original figure with the current render, the current SVG, and the provided 1/2 Crop pairs. For Regular Cuboids and Lattices and Inconsistent Patches, perform one additional separate pass over the 1/2 Crop pairs for each category. Do not list region numbers; do not write counter-evidence for areas without problems.
Output compact_category_sweeps in order F,E,B,S1,D,S2. For a category without problems, candidates is an empty array []. Do not output other_sweep.''' + '\n' + DISCOVERY_POLICY + '\n' + BOUNDARY_DISCOVERY

REPAIR_PROMPT = '''This is the second request. Write programs collectively for the listed F, E, B, S1, D, and S2 categories. Retain issue IDs and original detection evidence; do not add new issues. S1 source reinspection may explicitly downgrade a false or uncertain detection under the source-dimensionality policy below; echo other issues unchanged.
Each relation requires a unique non-empty id. Reference that exact id as check_id in convergence.repairs.
Each independent program must read the current local SVG and preserve unrelated content. Omit unused optional fields instead of supplying null or placeholder values. Leave runtime iteration limits to the bounded host default when unnecessary; provide actual source-based relations, measurements and mutation targets. Never invent visual parameters merely to satisfy a pre-check.
For F, repair according to the identified reason; multi-step operations are permitted. For frames, modify container boundaries; do not shrink content into an overly small frame. For text, modify text or symbols. Move the element only when the identified issue is positional. Ellipses and dashed lines must follow the row they belong to.
For confirmed duplicate layers, keep the source-faithful instance and remove only the redundant content; preserve adjacent labels and frames. Bind convergence checks to surviving content and its actual neighbors, not IDs removed by the repair.
In relations, use predicate; do not write kind. For separate, specify a positive min_gap; for contain, specify a positive padding. Use legal_overlap only when the overlap is present in the original figure itself. Frame modifications belong in operations using bp_patch.
Every relation must match existing IDs in the current SVG; otherwise, the program will not execute. contain: specify content as subject_id and frame as object_id, or specify frame as container_ids and content as target_ids. separate: specify the two objects as subject_id and object_id, or write them in that order into target_ids. Do not put frames into neighbor_ids.
For E, when endpoint heights or arrow shaft lengths are incorrect, modify endpoints or lengths according to the original figure; do not merely translate the entire arrow to the center. Both symmetric sides must be modified. Align large icons to axes according to the original figure.
For B, repair only compilation failures, subscript/superscript errors, and compilation errors in symbols such as radicals. Use SP formula; tex commands are strictly limited to those compilable under base, ams, and newcommand. Do not modify text that already renders correctly merely for font uniformity. Move formulas as a whole unit, not individual glyphs.
For S1, apply the independent source-pixel proof policy below to every replaced cuboid. measurement_viewport encloses construction; target_tp uses the current-render object extent; mode is contain. The original determines projection, visible faces, cell counts and block arrangement; source pixel coordinates and current SVG placement coordinates are different domains.
For D, use sp_replace with kind as arrow. The arrowhead tip and the shaft endpoint must coincide. head_length and head_width follow pixel dimensions in the original figure. Direction follows the original figure. Connect start and end points to frames if they connect in the original figure, or leave clearance if they leave clearance. Arrow programs follow the same explicit dependency rule as every other category; use [] only for independent scopes.
For S2, repair an existing structural boundary with bp_patch and source-pixel color/style evidence, preserving its children; do not rasterize an entire panel. Use sp_photo for a small missing or completely inconsistent image patch. Restore the specific source symbol, not a generic badge; keep the existing object placement and unrelated content.
When using sp_photo, provide actual source correspondence and crop proof; omit unused optional settings. args.source_crop specifies original figure pixels [x,y,w,h], which must enclose full_object_xywh and fall entirely within the original figure. args.crop_review is {object_complete:true, clipped:false, full_object_xywh:[x,y,w,h], edges_reviewed:{left:true,top:true,right:true,bottom:true}, evidence:all four edges of this element in the original figure fall inside the crop}. The key name is edges_reviewed; do not write sides. At the same level as method, provide source_location: {basis:original_semantic, description:this element in the original figure}. If unable to establish this source correspondence and proof, preserve the target and report the unresolved reason.
Each item in alignment_checks is {id,target_ids,reference_ids,mode:center_x|center_y|left|right|top|bottom,tolerance:0.5,reference_evidence}.
convergence is {max_iterations:6, alignment_checks, repairs:[{check_id, method:tp_align|tp_transform|tp_fit, target_ids, args}]}. check_id must match the id of a relation or an alignment_check.
For every category, independent scopes use depends_on as []. Programs mutating the same SVG object or overlapping group/child scopes must list the preceding program ID in depends_on. This includes adding an outline to a group whose children another program changes. Declare when only for an intended execution-status condition; do not invent a condition to bypass a failed repair.
Programs failing pre-checks will not execute. Do not write lengthy repair rationales.''' + '\n' + REPAIR_POLICY + '\n' + BOUNDARY_REPAIR


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
