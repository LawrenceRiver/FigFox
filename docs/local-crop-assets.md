# Local crop assets

The first-stage SVG can request a local crop using `data-plus-crop="x,y,width,height"`. Coordinates refer to the original image. The existing target geometry controls placement; an empty `g` uses the source crop coordinates.

The host preserves crop background by default. This keeps meaningful scene, mask and chart content that background removal can erase. For an isolated object that really needs transparency, set `data-plus-remove-background="true"`; only the exact strings `true` and `false` are accepted. The corresponding local `asset` operation accepts a strict boolean `remove_background`.

`data-plus-representation="raster"` retains a PNG. Other crop requests use vector paths, with ImageTracer as the default. An explicit `data-plus-backend` may select `imagetracerjs`, `vtracer` or `pixelruns`. The existing pixelruns limit is 262,144 source pixels per crop. It encodes horizontal runs of equal pixel colors; it does not recover independent data series or semantic geometric objects, and its SVG may be large.

For a separately drawn draft, the original `data-plus-replaces`, `data-plus-keeps` and `data-plus-covered-frames` rules still apply. The host restores these declarations after a successful crop and verifies the generated node, source image and asset file before permitting vector replacement. Merely putting a path or an authentication-looking attribute in model SVG gives no replacement permission. Frame identities, including frame descendants of a cropped subtree, continue to require explicit coverage before later draft removal.

Existing bound SAM PNG replacements continue to use their original path. Duplicate targets, overlapping deletions, protected objects and unrelated frames keep their checks. A successful local operation certifies execution, not visual acceptance.

These options add no model request. They do not change the first-stage prompt or automatically select a backend. Same-response local experiments verified background preservation and draft removal on two figures; full benchmark quality and general semantic editability remain unverified.
