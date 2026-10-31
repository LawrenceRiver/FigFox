Directly inspect the original figure to generate editable SVG code; extract colors directly from the original figure. Follow this order; do not skip steps.
1. Base frames: After all are completed, refit top, bottom, left, and right coordinates against original figure proportions.
2. Conduction drawing: Confirm the current object and its relationships to the origin and neighbors from the original figure before constructing it in SVG. After completing each base frame, refit the content inside that frame.
3. During conduction, establish mappings among original figure objects, constructed element IDs, and SAM asset IDs; after complete SVG construction and filling omissions, apply these mappings at the end to execute replacement. Content not covered by SAM must be retained.
4. Before submitting, cross-check against the original figure to fill omissions. Add any missing elements.
Every base frame must have an id, such as id="f01".

[Output]
Output only a single, complete, editable SVG containing base frames and the text, images, icons, and arrows from conduction drawing. Do not output anything else.

[Canvas]
{{CANVAS}}

[Arrow Library]
The identifier is the reference. Image crops are provided in the attached images.
The SAM library is used only to determine two things: whether it is double-headed or single-headed, and head dimensions in pixels.
{{ARROW_LIBRARY}}

[Base Frames]
In this step, write only the frames; do not write the text, images, icons, or arrows inside the frames.

First plan all base frames together according to the original figure, then establish them together. Base frames that are aligned in the original figure must also have their relative positions aligned when created. Before finalizing, ensure only that sibling frames do not overlap. Nested frames are not considered overlapping; an inner frame must be contained within its outer frame. For adjacent frames, compare the facing edges: the bottom edge of the upper frame with the top edge of the lower frame, and the right edge of the left frame with the left edge of the right frame.

Supplementary base frames (prioritize irregular shapes): Add base frames for content that does not yet have one. Prioritize irregular contours, determining position and size based on actual shapes in the original figure. When adding them, also ensure they do not overlap with existing sibling frames.

Scale base frames -> size repair: Cross-reference the original figure to scale each base frame to its intended size, correcting both oversized and undersized frames. After scaling, sibling frames still must not overlap.

After all base frames are completed, refit dimensions once more: check whether the top, bottom, left, and right coordinates of each frame match proportional edges in the original figure. If not, adjust coordinates according to original figure proportions.

Only after these steps are completed are you permitted to begin conduction drawing. Do not submit intermediate SVG separately.

[Conduction Drawing]
Select a base frame.
Before beginning conduction for this frame, inventory all visible content inside it from the original figure; do not decide whether to draw based on the presence of SAM assets. Briefly note objects and their relationships in <desc>. First complete genuine SVG/SP construction one by one and assign stable IDs to objects, without using empty placeholder boxes; challenging photographic areas can be handled using existing in-flight crop requests. Reserve SAM assets for replacement after conduction and SVG construction are completed.

Establish origin: Construct the origin in SVG first.
Begin unidirectional conduction: Move in only one direction that contains content at a time: upward, downward, leftward, rightward, or in any direction where content exists. Complete that direction before moving to the next. Do not spread out in all directions simultaneously.
Determine reference anchor: The reference anchor is the origin. Position the next entity relative to the origin.

For each subsequent entity reached, evaluate the following two layers before writing its code. After finishing it, proceed to the next entity in the same manner. Do not skip around to fill an entire block before moving to the next.

1. Subsequent Entity: Relative to Origin
Identify its relationship relative to the origin and construct it according to this relationship.
If it is an arrow: match its reference ID. Use the library only for double-head status and head pixel dimensions; if absent, treat as standard single-head.
Double-headed: specify marker-end at the end of the path, and add marker-start with orient="auto-start-reverse" at the start of the path.
Head size: define marker dimensions using library pixels: markerUnits="userSpaceOnUse", markerWidth=length in pixels, markerHeight=width in pixels. The triangle remains M0,0 L10,4 L0,8 Z.
Arrow and connecting line corners must follow the original figure; do not render all corners as curves, nor all corners as sharp bends. When both adjoining segments in the original figure are straight with a clear horizontal or vertical orthogonal bend: use polylines (L/H/V); do not round the corner with Q or C. Use a single Q only when the corner itself in the original figure has a subtle rounded fillet. If the original figure features a sweeping curve, keep C; do not flatten it into sharp bends.
If it is an image or icon: confirm the object and its relationships to the origin and neighbors from original figure context, and complete its initial construction and placement in SVG first. At the same time, locate the SAM asset covering this object from the original-figure overview board annotated with bounding boxes, establishing a mapping; do not skip initial construction even when a matching asset exists; execute replacement later using the established mapping, without guessing anew.

2. Whole Section: Equipartition / Symmetry Basis
For this section as a whole, state its basis of equipartition or symmetry (common examples: central symmetry, a horizontal line). Describe unique cases specifically; do not force generic templates.
After completing the content inside each base frame, refit inside the frame once: pull overflowing text back inside the frame, and check positions and sizes of foundational components such as arrows against the original figure.

[SAM Asset Mapping & Post-Replacement]
When you reach a photo, icon, or composite object during conduction drawing, confirm object boundaries against the full original figure. Locate the matching SAM asset from the original-figure overview board annotated with bounding boxes, establish the relationship "Original Figure Object - Constructed Element ID - SAM Asset ID", and record semantic rationales in <desc>. Do not guess an asset's purpose from an isolated crop first. Bounding boxes and IDs on the board are not content to reproduce.

Only after full-figure SVG construction is completed should you apply established mappings to replace elements at established positions. Multiple crops belonging to the same combination in the original figure must preserve their internal relative positions, spacing, and proportions, placed as a unified block; handle distinct objects separately, not merging them merely based on distance or bounding box overlap.

First clarify what the asset actually covers: delete the constructed SVG content and temporary placeholder boxes that are fully covered; retain true outer frames if the asset does not include them, deleting redundant frame constructions only when the asset fully encapsulates them. Uncovered text, arrows, borders, and details must be retained. If an existing group mixes elements to delete and elements to keep, separate them in SVG before replacement; do not delete the entire mixed group.

Retain the complete initial SVG construction code in the output, and declare on an independent post-replacement image or g: data-plus-replaces="IDs_to_delete_space_separated", and for associated elements to keep: data-plus-keeps="IDs_to_keep_space_separated". If the deletion list includes true frames with data-plus-kind="frame", you must explicitly list them in data-plus-covered-frames="frame_IDs_fully_covered". Replacement nodes and deleted nodes must not contain each other. Specified initial constructions are deleted only after code binds the asset; do not use empty groups to fake drawn content.

Example: after <g id="draft-object">actual drawn construction</g>, output <g id="replacement" data-plus-replaces="draft-object" data-plus-keeps="adjacent-label" transform="translate(dx dy)"><image href="ACTUAL_ASSET_ID" x="ORIGINAL_X" y="ORIGINAL_Y" width="ORIGINAL_W" height="ORIGINAL_H"/></g>. All corresponding IDs and anchor points are determined by you from the original figure.

When there is no matching asset or the mapping is uncertain, retain the constructed content without forcing replacement. After completion, check for mismatches, duplicates, residual placeholder boxes, and omissions.

source_crop=[x,y,width,height] in the SAM asset table represents the crop's true block coordinates on the original figure. When referencing an asset, keep image x/y/width/height at these exact original values; the host will also restore these values from SAM records. Express new placements using the outer native SVG <g transform="translate(dx dy)">. Determine dx/dy from the original figure, base frame, and conduction relations (0 for in-place reproduction). Do not guess each crop's position separately or rearrange the layout.

Multiple images originally arranged together in the same semantic block share the same outer g and the same translation offset, preserving their relative positions, spacing, dimensions, and arrangement; existing full-block crops can be used directly as a whole, avoiding redundant references to overlapping sub-crops. Group by original figure context, not by mechanical distance. Do not center or stretch images individually. Single images also use original coordinates plus outer translation.

Express using standard SVG, such as <g id="block_id" transform="translate(dx dy)"><image href="ACTUAL_ASSET_ID" x="orig_x" y="orig_y" width="orig_w" height="orig_h"/></g>. All values derive from the asset table or your overall conduction judgment; do not use placeholder declarations like data-plus-sam-group. Prioritize original dimensions; scale uniformly as a whole only when strictly required to fit a base frame, never altering proportions of individual group members.

Final replacement applies only to confirmed matching assets; do not omit initial SVG construction even when a matching asset is available. For missed detections or challenging areas, declare data-plus-crop="x,y,w,h" and data-plus-representation="raster|vector" for the host to crop from the original figure. Use raster for standard photos, and vector for multi-geometry combinations or abstract challenging areas; do not use a full-image screenshot to substitute for reconstruction.

Below are asset IDs, types, and SAM original block coordinates, matching attached crops in table order:
{{IMAGE_LIBRARY}}

When reusing definitions with <symbol> and <use>: every <use> must specify width and height, matching the viewBox dimensions of that <symbol>. Omitting width/height causes the element to stretch across the entire canvas; omitting them is forbidden.

[Fill Omissions]
Before submitting, cross-check the original figure against the SVG code written so far, one base frame at a time: check the preceding element inventory; every object visible in the original figure must have an actual visible implementation. In particular, inspect areas that have only a frame and title but blank interior graphics; writing a title does not mean content is complete, and absence of a SAM crop does not mean it can be omitted.

When SAM assets are absent, construct representable content with SVG/SP; for challenging regions that are difficult to construct accurately, use the existing data-plus-crop mechanism, with crop coordinates determined by you from the original figure. Never substitute unrelated assets or arbitrary simple lines. Small graphics, curves, textures, and internal symbols must also be faithfully supplemented from the original figure; do not leave their initial creation to later repair passes.

Check that these elements are not hidden by opacity=0, display:none, incorrect clipping, occlusions, or CSS style overrides; ensure fill on light text on dark backgrounds is not overridden by class fill rules. Submit the complete SVG only after actually filling all omissions; an element inventory in <desc> alone does not count as completed.

[Plus Supplement: Preserve Native SVG, Do Not Convert to Scene]
SVG coordinates follow native SVG semantics: rect x/y does not move child elements; only transform alters coordinate systems. Strive to use a unified viewBox preserving original figure proportions. Add data-plus-kind="frame" and stable IDs to all base frames and supplementary frames; assign stable IDs to semantic objects and groups as well. When expressing relationships, use text/names from the figure as subject and object, retaining rationales in <title> or <desc>.

SP can be declared in SVG as <g id="..." data-plus-sp='{"kind":"geometry","data":{...}}'/>; the host uses the actual constructors specified in the manual to fill in the content. Applicable to individual geometric objects (such as cuboids or lattices), arrows, text, and formulas; complex regions should follow photographic classification for local vectorization. All numerical values must be determined by you from the original figure, not copied from the examples.

SAM provides clues only; false positives need not be used. After host replacement, image assets and replaced draft constructions must not be retained at the same time to create duplicates. Submit only a complete SVG.

[Original Colors & On-Demand Color Sampling Method]
Accurately reproduce colors of background, frame surfaces, lines, text, and geometric faces from the original figure; do not substitute with uniform approximate palettes. Distinguish fill from stroke; note light-on-dark versus dark-on-light text, avoiding inherited styles overriding correct colors; gradients and opacity in the original figure cannot simply be treated as a single flat color.

No pre-computed color palette or hex library is provided. For solid color regions requiring exact fidelity, declare on the corresponding SVG element: data-plus-color='{"fill":[x,y,w,h],"stroke":[x,y,w,h]}', including only attributes that require sampling. Coordinates [x,y,w,h] are identified by you from the clean original figure, referencing sampling ROIs on the original figure-not the new placement in SVG. Upon receiving the SVG, local OpenCV takes the dominant mode color within that ROI, writes it into the element's corresponding attributes and inline style, and records the measured hex code; no color-sampling code is required from you.

Sampling ROIs must be chosen inside the target's solid interior, avoiding text, anti-aliased edges, shadows, and adjacent backgrounds. If a solid color sampling ROI cannot be determined for fine lines or fine text, construct them directly based on the original figure and leave them for subsequent verification; do not sample large surrounding backgrounds to cover them. Gradients should retain their gradient structure according to the original figure, rather than taking a single dominant color across the entire gradient region.

Use inline text fills; omit data-plus-color on frames and text.
