# Source-faithful native reconstruction

Build frames together, refit their edges to the source, then follow actual connected objects within each region. Assign IDs to meaningful groups, labels, photos, native geometry and arrows. Describe source relationships in short SVG `<desc>` records where helpful. IDs are implementation targets, not evidence that a visible object is correct.

Use source proportions rather than a new grid. Repeated objects preserve their actual count, shape, order, scale and connections. An arrow has a complete shaft, every real bend and an attached head at its actual endpoint; preserve the source's filled/outlined, single/double-headed and curved/orthogonal treatment. Text and formulas retain exact case, punctuation, symbol identity and independent sub/superscript positions. Do not invent unreadable literals or flatten labels into outlines merely to imitate a font.

Photos, fine illustration texture and background imagery may use exact source crops, independently positioned and replaceable. Record their source bounds separately from target bounds. Keep source labels and arrows outside the raster crop and reconstruct them natively. Embed image data for standalone delivery. Do not reconstruct the entire figure by image wrapping, use whole panels as crops, or hide the source PNG behind an editable-looking overlay.

The current assistant directly authors the SVG. No raster image-generation call is needed to obtain SVG code. Without SAM, choose local crops from visible source evidence. Do not emit unresolved `asset_id`, `data-plus-crop`, SAM mappings, SP constructors or replacement directives: materialize the actual native elements and embedded crops before delivery.

After each region, refit contents against its actual frame, then check the complete figure for omissions and accidental duplicates. Exact fonts may be unavailable; use a readable editable substitute and disclose the difference. Use a complete SVG with explicit width, height and viewBox, unique stable IDs and local/embedded resources.

Source basis: [FigFox native reconstruction prompt](https://github.com/LawrenceRiver/FigFox/blob/main/prompts/first_native.md). The skill retains its frame-first and relational construction rules while replacing provider/SAM-specific execution assumptions with current-assistant authoring and resolved local assets.
