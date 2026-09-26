"""User taxonomy: six ordered categories and four on-demand categories."""
QLIST = [
    {'id':'A','name':'Content Issues','definition':'Errors in factual text, spelling, terminology, or formula content. Confirm using context and reliable knowledge; distinct from depiction errors in photos or geometry.','checks':['Distinguish printing artifacts','Do not guess or modify content when the knowledge is uncertain'],'legacy_types':['content']},
    {'id':'B','name':'Typesetting and Formulas','definition':'Symbols, fonts, font size, radicals, sub/superscripts, or compilation rendering inconsistent with the reference original. Preserve content corrected in A; render with correct SP.','checks':['Reference original','Current SVG position','Construct first then measure'],'legacy_types':['typesetting']},
    {'id':'C','name':'Line Routing','definition':'Lines traversing wrong regions, missing segments, routing, bend-point coordinates or angles, or curve forms inconsistent. Locate by semantic relationships between neighboring frames, modify via BP.','checks':['Source and target','Traversed regions segment by segment','Missing segments','Bend points and curves'],'legacy_types':['arrow_route']},
    {'id':'D','name':'Arrows','definition':'Missing arrows or arrowhead-to-shaft relationship inconsistent with the reference. Check for missing arrows via PNG-to-PNG comparison; perform four standard checks after patching.','checks':['PNG missing-arrow check','Shaft exposure','Connect to frame or leave clearance','Arrowhead pixel size and direction at the same scale','Tip must coincide with shaft endpoint'],'legacy_types':['arrow_geometry','missing']},
    {'id':'E','name':'Alignment and Symmetry','definition':'Bound groups that fail to match in axis alignment, edge alignment, center alignment, equal spacing, or left-right symmetry; bind members first, then fine-tune coordinates with respect to the center axis.','checks':['Bound groups and inner/outer frames','Center axis and absolute distance to axis','Connected linkages'],'legacy_types':['alignment']},
    {'id':'F','name':'Overlap and Overflow','definition':'Two or more objects violating separation, margin clearance, or containment relationships. Both parties trigger TP alarms; return to the original figure to judge which to modify, then check neighbors and their associated objects.','checks':['Do not falsely report valid containment','Flush-edge clearance','Two parties or multiple parties','Original relations among the involved objects','New neighbor alarms','Soft visual acceptance of the relation against the original figure'],'legacy_types':['overlap','overflow']},
    {'id':'S1','name':'Photo and Geometry Relative-Size and Content Errors','definition':'Depiction errors, relative size, structure, missing parts, or asset edge contamination in photos, geometry, or patterns. Distinct from A content issues.','checks':['PNG missing-item check','Overlap clues and original figure dimensions','Neighbor positions in current render','Simple geometry SP','Fallback to original figure crop upon failure','No extraneous edge lines','RMBG subject integrity','Precise crop or abstract vector'],'legacy_types':['relative_size','geometry','missing','fill_spill']},
    {'id':'S2','name':'Planar Shapes','definition':'Planar shape, orientation, contour, or fill overflowing intended boundaries; inspect the original figure, semantically locate the corresponding object in the current render, and modify the shape using BP.','checks':['Correct contour','Orientation','Fill and stroke boundaries'],'legacy_types':['planar_shape','fill_spill']},
    {'id':'S3','name':'Colors','definition':'Verify colors for every object; semantically locate the color patch corresponding to the same content in the original figure, sample and replace color with OpenCV; do not assume correspondence by identical coordinates.','checks':['Clean ROI','Correct component','fill or stroke','CSS and shared references'],'legacy_types':['color']},
    {'id':'S4','name':'Similar but Different Count','definition':'Semantic unit count does not match after comparing enlarged PNGs; not SVG path count. Add, remove, or combine via BP.','checks':['Magnification and occlusion','Preserve distinctions between units','Add/remove identity','Layout after count adjustment'],'legacy_types':['count']},
]
BY_ID = {q['id']:q for q in QLIST}
MAIN_ORDER = ['A','B','C','D','E','F']
TOLERANCE = {'printing_artifacts_only':True,
             'similar_depiction_not_content_error':True,
             'general_usable_difference_exemption':False}


def markdown():
    lines=['# Q list: 6 ordered primary categories + 4 as-needed categories',
           'The historical 14 categories are local tool adaptation tags only; model output must only use the 10 categories in this table. Missing items, fill spill, and geometry details are retained as sub-checks and not dropped.',
           'Tolerance is limited to printing artifacts in the original figure; highly similar content is not reported as a visual content error, and is not generalized into ignoring all usable differences.','']
    for q in QLIST:
        lines += [f"## {q['id']} {q['name']}", q['definition'], 'Required checks: '+'; '.join(q['checks'])+'.','']
    return '\n'.join(lines)
