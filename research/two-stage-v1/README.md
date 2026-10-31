# Actual bounded two-stage experiment source

This directory preserves the source used to complete 80 originals × four native conditions. `snapshot-sha256.json` records exact source hashes. It does **not** contain dataset images, private runs, credentials or model/tokenizer weights.

- `runner/two_stage_runner.py`: A1/A2 C-neutral initial reuse and four parallel detection/plan/execute/verifier branches.
- `runner/joint_detector_adapter.py`: explicit same-response role routing, exact references, preserved raw findings, conservative protocol projections.
- `runner/bounded_*`, `planner_*`, `model_envelope_binding.py`: transport, request/receipt identity and native validation boundaries.
- `runner/two-stage-adapter`: frozen role contracts and native adapters. Its `source` link must resolve to `native-source` when bound in a workspace.
- `runner/two-stage-bridge/prepare_cell.py`: immutable explicit-input preparation, source/capability/hash checks.
- `runner/first-stage-harness-bridge-20261029`: native first-generation bridge; actual GPT callback, no substitute image generation.
- `first-stage-adapter`: initial adapter contracts, with its source explicitly bound to the same native tree.
- `native-source`: the frozen native implementation, distinct from the repository's legacy current package.
- `config.template.json`: non-secret binding template; placeholders must be resolved locally, never sent directly as a live config.

## Reproduction and entry point

The recorded experiment entry is `runner/two_stage_runner.py`. Its original workspace constants, fixed historical cohort UUID, cache lookup layout and `run_ablation` defaults are intentionally preserved and hash-listed. Consequently **running this snapshot directly from an arbitrary checkout is not a supported one-command reproduction**. A fresh deployment must bind ROOT/CONTROL/OLD/CFG and native/runtime/registry/matrix paths, create a fresh accounting/cohort identity, freeze its own input manifest, validate source links and review the explicit configuration. Do not reuse the historical UUID against an unrelated ledger or silently change frozen runtime hashes.

The legacy public `chain` command is still available through the main package. It does not implement the new four-condition experiment supervisor. This separation prevents a new diagram from falsely describing an older executable path. A portable product entry is separate work; this publication supplies the actual experiment code rather than pretending it is already packaged.

Offline tests were run in the experiment workspace: **188 tests passed** (`final-delivery-regression.log`, not bundled as private runtime evidence). Several integration fixtures depend on that workspace's native runtime/source bindings, so this is not a claim that all 188 execute in an unconfigured clone. Lightweight hash verification works anywhere:

```sh
python3 verify_snapshot.py
```

Local SAM3 and browser/vector runtimes must be installed separately. Credentials are read through environment or an explicitly chosen local env file, never committed. Never run a live queue without checking the active PID, singleton lock and request journal. Unknown-charge requests keep their conservative reserves.
