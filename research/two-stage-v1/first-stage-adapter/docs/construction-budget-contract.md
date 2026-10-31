# Conservative typed construction-budget preflight

The shared `Flow.preflight` used by check-plan and execute retains native shape,
scope, schema and dependency validation. After native selection, it may reject a
`module_program` containing a literal `sp_replace.measurement_viewport` whose
supplied box alone proves the first adaptive measurement exceeds 40,000,000
pixels. Rejected predecessors are removed before native dependency validation is
repeated. Feedback uses existing plan-check slots; this adds no model stage.

The frozen path is v13 programs -> single_call executor -> repair_toolbox
`execute_batch` (default host scale 4) -> `sp_v2.measure_construction_adaptive`.
Operation `args.scale` does not override that host scale. Native takes the union
with DOM paint bounds and pads the first window by `max(8, .1*width, .1*height)`.
The native guard is strictly `padded_width*padded_height*scale*scale > 40_000_000`.
The supplied box is only a lower bound; DOM geometry or retries can increase it.

`construction_budget.NATIVE_BINDING` pins all six source files defining dispatch,
resolution, scale, padding, guard and convergence applicability. Missing or changed
bytes defer all proofs to native. The helper mirrors this finite frozen
compatibility contract; it is not a shared native formula. Its own bytes and this
document enter `prompt_hashes`, while native source bytes remain frozen inputs.
Updating any native pin requires source review and fresh tests.

Only exact four-edge finite nonboolean int/float boxes are considered. Magnitudes
over 1e9, cancellation ratios over 1e6, invalid edges, overflow/nonfinite values,
expressions (`$measure`, `$calc`, `$result`), whole-argument expression keys,
extra/dynamic box keys, and a relative
1e-9 band above the boundary remain unknown. Directed rounding lowers each
arithmetic operation. At/below-budget or unknown results never certify safety.
Nested typed `bp_program` operations are traversed. Status-conditioned `when`
programs/operations defer proof. Frozen active E/F convergence accepts TP repairs
only; other categories do not execute convergence, so convergence payloads are not
scanned. Generated Python is explicitly deferred, without AST/source scanning.

No plan coordinates, raw plan bytes, constructors, DOM, rendering, provider,
credentials, or native guards are changed. This is feasibility feedback only;
visual quality, necessity, identity, completeness and missing-content gates remain
independent and mandatory.
