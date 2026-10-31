# Reference and static-CSS support boundary

This version replaces blanket legitimate-context exclusions. It remains a common, reviewable execution guard under both code assignments, without new prompts/tools/model calls. `dependency_proof` returns its affected-ID set, checked preexisting refs, grammar version and supported-context counts in the common guard receipt.

Allowed when the old XML is otherwise invariant:

- Existing `image href="data:image/png;base64,..."` content; no local SVG-ID binding occurs.
- Local `href="#id"` and quoted/unquoted `url(#id)` only when their referenced ID is neither new nor affected by the transaction. Unchanged unresolved references stay unresolved; a new ID cannot capture them.
- Literal rgb/rgba/hsl/hsla numeric colors, ordinary literal SVG paint/font/stroke values.
- Static CSS class/ID/type/universal and compound selectors, comma lists and whitespace descendants. Only explicit SVG presentation properties and checked static values are accepted. Since protected old ancestry/attributes remain, these selectors' old-node matches do not change simply because children are added.

Affected IDs conservatively include anchor and independently authorized target subtrees plus all named ancestors. Referencing these can expose inserted/changed content elsewhere and therefore rejects. Resource definitions remain invariant regardless of placement; separately authorized target subtrees containing resources remain unsupported. Reference checks run for pure insertion as well as mixed existing-target transactions.

Rejected contexts include structural/positional/pseudo/:has/sibling/child/attribute selectors, at-rules, CSS comments/escapes, dynamic var/env/attr/expression or unknown functions/properties, external or unsupported hrefs/URLs, unknown fragment syntax, active animation/script/foreign content, root anchors and ambiguous insertion source bindings. These are explicit common-guard exclusions; they must not be attributed to model or method quality. Plain embedded-PNG and simple-static-style fixtures are supported, rather than excluded by unrelated href/function syntax.

This grammar does not implement a general browser dependency engine. It proves protected XML and the declared reference/static-style invariants within this boundary, not universal unchanged pixels: geometric occlusion and text/layout/visual correctness still require the native checks and independent verifier. The tests use actual native validation and macOS sandbox execution but isolate numerical measurement/checkpoint rendering; no full renderer/API/real-figure efficacy result is claimed. Reviewed adapters, native source and frozen smoke are untouched.
