# Independent insertion-parity re-review, round 3

Spec verdict: **pass within the explicitly supported subset**.

Code-quality verdict: **pass**. No new actionable findings within that boundary. Prior review and proof artifacts are preserved.

## R2 gap resolved

The preexisting reference/style dependency scan now applies to every insertion transaction, including pure absent-content programs without separately writable old targets. Independently replayed the original R2 `use href="#new"` capture through actual native execution and macOS sandboxing, using a temporary script copy to preserve prior artifacts. Both ON and OFF now fail and roll back with `unsupported preexisting reference/style dependency`.

All **46 tests passed** in the pinned environment. This includes actual native/sandbox rejection for dangling href, paint URL and stylesheet selector contexts, ordinary isolated insertion success in both assignments, prior gradient/resource protections, unrelated repeated-source pass-through, and fail-closed source collisions. No implementation edits were made.

## Exact assurance and fairness boundary

For supported simple geometry scenes, a genuine absent object can be inserted through stdlib generated Python under either code assignment. The same common before-checkpoint proof runs on module insertion, after its operations/convergence. Explicit existing-target permission and protected old XML checks remain separate. The correction removes the old route-based direct-repair impossibility within this supported subset.

Reference/style ambiguity is handled by rejecting the transaction in both arms, rather than claiming XML equality proves preserved reference semantics. This is a conservative common execution boundary, not universal restoration rights for all valid SVG scenes. In an efficacy analysis, unsupported contexts must remain explicitly identified as common guard exclusions, not attributed to model weakness or constructor quality. Any paired task restriction or excluded denominator should be reported consistently.

Independently verified two deliberate legitimate-SVG false rejections: a protected rectangle with harmless `fill="rgb(1,2,3)"`, and an existing embedded PNG image href elsewhere in the SVG. Both block insertion even though the tested simple addition need not alter them. Safe stylesheets/references may likewise be refused. This matches the report's stated boundary and is a material usability/coverage limit, not a newly hidden bypass. Improving that coverage would require a separately reviewed dependency resolver or narrower proved allowlist.

The proof does not certify unchanged protected pixels. Added geometry can occlude existing geometry or affect text/layout even without changing old XML, and independent visual verification remains necessary. Root/descendant-anchor limitations, conservative parser/source-ambiguity handling, and unclaimed hostile filesystem concurrency protection remain. These are not full renderer/runtime/API readiness results.

## Preservation and evidence

`review-r3-proof.json` records independent simple-geometry success, legitimate-context conservative rejections, preserved prior review hashes, unchanged original clone manifest and identical native source symlink target. R1/R2 reviews and proofs were not overwritten. Actual native/sandbox tests used neutral XML; numerical measurement and checkpoint rendering were stubbed. No case/gold data, runtime actor outputs, credentials, model or provider calls were used.
