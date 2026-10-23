# Native chain capability contract

The release chain accepts an assignment with exactly three fields:

```json
{"version":"capabilities-v1","sam":false,"code_methods":false}
```

Both switches require JSON booleans. Its hash is SHA-256 of UTF-8 JSON with sorted keys and compact separators. `capabilities=None` retains the existing all-on availability default. Formal callers must pass an explicit assignment. The CLI exposes `--sam on|off`, `--code-methods on|off` and `--sam-service-url`. `run_chain` also accepts `first_sender` and `review_sender` for offline transports.

`first`, review `prepare`, `run`, saved replay, followup, program validation/execution and generated Python receive the same assignment. Prepared policy and prompt hashes enter frozen input verification; changing the assignment at resume fails. Execution checkpoints also bind it into their signatures.

SAM-off branches before asset preparation and never opens its cache or evidence. SAM-on validates preparation status and source/asset hashes before the first model request. Empty successful manifests remain valid. Legacy explicit injected `sam={"assets":[]}` fixtures are accepted only through the default entry and are marked mock; they are not real SAM evidence. SAM binding and safe replacement remain available with code methods off.

Code-off retains visible native SVG generation and a scoped generated-Python repair route. The sandbox uses `-I -S`, mounts no method tree, omits `CURRENT_TP`, and permits a narrow stdlib XML/math authoring surface. AST checks and runtime file/import auditing supplement the existing macOS Seatbelt/resource limits. Direct imports, dynamic import helpers, source-file access, unavailable SVG declarations, module operations and nested convergence repairs are rejected. This finite tested defense is not a proof against every possible Python or operating-system exploit.

Read-only geometry acceptance, two-pass convergence checks, neighbor/scope/dependency checks, safe SVG validation, rendering and rollback remain common host services. Code-off receives no derived TP numbers, diagnostics, method manuals or implementation sources. Original/current images, SVG IDs and the same upstream half-crop comparisons remain available. The original followup trigger and one-request limit are retained.

The active release prompts share `common_quality` and `common_conditional_policy` blocks with identical hashes in all four assignments. Availability, corresponding method documentation and SAM evidence vary explicitly. This is a capability-package ablation, not an assertion that complete prompt bytes are identical or that the new prompts reproduce the frozen legacy output.

`invocation-trace.jsonl` separates common runtime, common guard, SAM intervention, code intervention and rejected requests. Host entry records include source hashes and, when applicable, program hashes and revisions. Generated-on Python additionally traces calls into the mounted package; its receipt retains those observations. These traces document actual fixture execution, not an adversarially tamper-proof remote attestation. Rejected requests are not counted as started interventions.

Final output follows the last committed review/followup checkpoint, including recovery of already committed followup state after a later failure. The chain exports `final/scene.svg`, `final/preview.png` and hashes in `chain-result.json`. Execution always leaves `visual_passed=false` until independent visual review.
