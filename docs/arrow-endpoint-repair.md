# D endpoint repair method note

For a confirmed D issue involving an **existing** straight, locally marker-ended SVG path, a `module_program` may use one `bp_patch` per affected shaft to change only its `d` endpoint. Each path must have exactly one absolute `M`/`L` segment; the start, marker, style, and other attributes stay intact. The operations must cover exactly the declared subset of issue targets, with no repeated target or convergence repair. Missing arrows and other D work still use the SP arrow constructor.

The host admits an inward endpoint whose center projects strictly inside the old segment and whose decimal rounding box intersects that segment. This checks the form and scope of the edit; it does not establish the correct landing against the original figure. Transaction and visual checks still decide execution status and acceptance. A successful edit remains `changed_unverified`, with `visual_acceptance` pending.
