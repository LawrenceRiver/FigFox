# Independent insertion-parity adapter review

Spec verdict: **changes requested** (P1 resource invariant gap).

Code-quality verdict: **changes requested** (P2 unrelated transaction regression).

This review concerns only the new insertion-parity patch. It does not rerate the previous compatibility review or change any frozen smoke.

## P1 — protect resource definitions outside defs

`insertion_guard.py:66–69` defines the common global invariant through an incomplete tag list. `defs` is frozen, but SVG resources need not be children of `defs`. A `linearGradient` directly under an independently writable group is omitted from `globals_`; `same` then returns immediately for that authorized group (`85–88`). Its stops can change even when an unchanged protected rectangle elsewhere uses `fill="url(#paint)"`.

Independently reproduced through the **actual native executor and macOS generated-code sandbox**: a transaction links one genuine missing issue anchored at `frame` plus a genuine existing-target issue on `editable`; it appends a fresh circle under `frame` and changes `stop-color` from red to blue in `editable/linearGradient#paint`. The protected rectangle remains bytewise untouched but references the changed paint resource. Result: `changed_unverified`, common proof `passed` at checkpoint. No rendering was needed to establish the missing resource invariant; visual quality is not asserted.

Freeze all resource definitions regardless of placement, and account for their relevant context/reference effects, or conservatively reject writable subtrees carrying globally referenced resources. At minimum cover gradients/stops, markers, patterns, clip paths, masks, filters and symbols, with tests for resources outside `defs`. Preserve separately authorized ordinary geometry writes. The independent verifier remains necessary, but cannot substitute for the promised precommit global-resource proof.

## P2 — avoid source-uniqueness checks for unrelated programs

`insertion_guard.py:135–139` wraps **every** generated execution and requires source text to match one program. This is enforced even when `bindings` is empty and no insertion issue exists. Consequently, two native-valid independent existing-target programs with identical generated source both fail `insertion guard: ambiguous sandbox source`.

Independent actual-native/sandbox comparison: two category-A issues target separate existing rectangles; each program runs identical stdlib XML read/write code. Both return `executed_no_change` without this context; both fail with the context. Source uniqueness is a defensible fail-closed fallback for insertion attribution, but should not change existing-target transactions that have no insertion proof requirement.

Bind to the actual immutable invocation context/index, or safely pass unrelated invocations through while retaining strict insertion binding. Test an empty binding set with duplicate sources, plus mixed insertion/noninsertion source collisions. Do not solve this by allowing an insertion to borrow another program's proof.

## Verification and strengths

The supplied pinned suite passed **40 tests**. Its actual-native tests demonstrate successful genuine absent generated insertion in both code assignments, plus rollback for protected modification/deletion. The common wrapper is installed around native execution, restored in `finally`, and runs checkpoint proof after module operations/convergence. Original active issue anchors, explicit separate target rights, and program/source hashes are bound. Unknown/duplicate identity and missing proof cases fail closed.

Independent probes are saved as `review-proof.json` and `review-proof-reproduce.py`. Reproduce from this adapter with `PYTHONPATH=. /Users/lawrenceriver/Desktop/7月/plus/.venv/bin/python -B review-proof-reproduce.py`. Checkpoint rendering and numerical measurement are deterministic stubs; actual native validation, execution transaction and sandbox run. The probes do not inspect case images, gold, model outputs, providers or credentials.

The reviewed source manifest remains unchanged; only cloned `flow.py` differs, with the identical native source symlink target. Docs/prompts remain identical. No implementation edits were made.

## Bounds of assurance

The native module transaction test stubs `_perform`; it establishes final common-proof hook placement, not a production renderer/module run. Exact nonroot anchors are supported; root and descendant-anchor insertion remain conservative exclusions. Receipt verification checks recorded in-memory proof plus receipt-file existence, not an adversarially rewritten log. No concurrent hostile writer or final runtime/API readiness assurance is established. These limitations do not negate the demonstrated generated insertion parity, but P1 must be fixed before treating the common proof as satisfying the requested scope guarantees.
