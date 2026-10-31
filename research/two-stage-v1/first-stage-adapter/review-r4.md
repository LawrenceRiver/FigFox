# Independent supported-context extension review, round 4

Spec verdict: **pass within the declared fragment-reference/static-CSS grammar**.

Code-quality verdict: **pass**. No new actionable findings in that boundary. Prior reviews and proofs are preserved.

The extension replaces the blanket preexisting-href/function rejection with an explicit dependency proof. Fresh IDs cannot capture old local references. References to anchor/target subtrees and named ancestors reject, including pure insertion. Unrelated unchanged references and unresolved references that remain unresolved are allowed. Static descendant/type/class/ID CSS does not acquire structural selector semantics; unsupported selector or dynamic syntax rejects. Resource definitions remain invariant and writable resource-bearing old subtrees remain excluded.

All **49 supplied tests passed** using the pinned Python. The suite exercises actual native validation and macOS sandbox insertion in both policies with one neutral scene combining embedded PNG, static CSS, numeric functional colors and immutable gradient use. Earlier reference capture, affected context, structural CSS, XML-rights and rollback cases remain passing.

Independent probes in `review-r4-proof.json` confirmed acceptance of unrelated local href, quoted local paint URL, compound/comma/descendant static CSS with important declarations, and unresolved references that remain unresolved. They confirmed rejection of fresh-ID href/CSS capture, root-ancestor and anchor-descendant references, escaped URL syntax and pseudo selectors. No new bypass was established within the stated grammar.

Fairness is materially improved over R3: ordinary embedded-PNG and static-style scenes no longer lose insertion rights merely because they contain unrelated hrefs or `rgb()` syntax. Both assignments still face the same common proof. Unsupported contexts must remain common host exclusions in any efficacy accounting, not model failures or evidence of original V6 method quality.

This is still a bounded XML/reference/static-style invariant, not universal unchanged pixels or full SVG/CSS support. The affected-ID set conservatively includes whole anchor/target subtrees and named ancestors, so legitimate immutable-descendant references can still fail. Structural/pseudo/attribute/sibling/child selectors, escapes/comments, dynamic values, unsupported external resources, root anchors and ambiguous insertion sources remain explicit exclusions. New geometry can occlude old content or change text/layout; native and independent visual checks remain necessary.

Verified prior review hashes, reviewed-original manifest and identical native source symlink target. Tests isolate numerical measurement and checkpoint rendering, so they do not establish production renderer/API readiness or figure efficacy. No implementation edits, case/gold/actor-output reads, credentials or provider/model calls were made.
