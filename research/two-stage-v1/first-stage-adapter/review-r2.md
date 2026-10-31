# Independent parity adapter re-review, round 2

Spec verdict: **changes requested** — one remaining P1 reference-dependency gap.

Code-quality verdict: **pass for the reported P2 fix** — no remaining unrelated duplicate-source regression found.

## Original counterexamples verified fixed

Independently reran the original proof script through a temporary copy that preserved all R1 artifacts. The standalone gradient mutation now fails with `global style/resource change`; the two unrelated same-source generated transactions both return `executed_no_change` under the context, matching native behavior. The supplied mixed-binding and collision regressions also pass. All **45 tests passed** in the pinned environment.

The added resource-family/context checks are conservative and appropriate in lieu of a dependency resolver. However, the dependency check runs only when a separately writable existing target exists.

## P1-R2 — protect reference dependencies during pure insertion

`insertion_guard.py:90–97` skips external href/URL/style checking when `authorized_nodes` is empty. This is exactly the ordinary pure missing-content insertion case.

Independent neutral fixture before execution:

```xml
<svg xmlns="http://www.w3.org/2000/svg" width="80" height="80">
  <g id="frame"/>
  <use id="protected" href="#new"/>
</svg>
```

A genuine absent finding has `target_ids=[]`, `container_id="frame"`. Stdlib generated Python appends `<circle id="new" r="2"/>` directly under `frame`. Every preexisting node and resource-definition byte remains unchanged; the fresh ID is valid and unique. Nevertheless, the preexisting protected `use` changes from an unresolved local reference to a resolved reference to the new circle. This creates an effect outside the insertion anchor through SVG reference binding.

Actual native execution plus actual macOS sandbox returned **`changed_unverified`, common proof `passed` in both code assignments**. Numerical measurement and checkpoint rendering were stubbed consistently with the supplied native tests. No rendering quality claim is needed: the missing reference-binding invariant is explicit in the XML. This is distinct from ordinary geometric occlusion, which remains the independent verifier's duty.

Apply a common fail-closed dependency rule to pure insertion as well. At least reject fresh-ID capture of existing protected href/URL references; also account for existing styles whose structural selectors can change protected appearance when children are inserted. Without a resolver, conservatively reject unsupported reference/style contexts for every insertion transaction. Preserve isolated geometry insertion in both arms. Add actual-native/sandbox tests for the protected-use case under both code policies.

Reproduce with `PYTHONPATH=. /Users/lawrenceriver/Desktop/7月/plus/.venv/bin/python -B review-r2-proof-reproduce.py`; results are in `review-r2-proof.json`.

## Preservation and assurance

Verified R1 review/proof hashes against `review-artifact-preservation.json`; all are unchanged. The reviewed original clone manifest remains unchanged and native source uses the identical symlink target. No implementation edits, case/gold reads, runtime actor outputs, model/provider calls or credential access occurred. Existing wrapper installation/restoration and final checkpoint-hook guarantees remain as reviewed. This review does not establish full renderer/runtime readiness or figure efficacy.
