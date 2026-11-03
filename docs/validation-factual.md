# Factual pipeline validation

Offline validation for this release:

- 39 provider, runtime, ablation-plan and factual-pipeline checks passed.
- All 160 historical A/B operation sequences replayed with the released
  native executor and matched the final SVG text exactly.
- Fresh fixture execution, completed-run reuse, mismatched-source rejection,
  interrupted-G0 hash rejection and uncertain-request suppression were tested.
- No paid provider requests were made for release validation.

The broader legacy suite passed 137 tests and failed 14 tests in the available
Conda environment after browser configuration. Failures involved the older
macOS sandbox Python launcher and dependent legacy follow-up tests; the
sandboxed interpreter could not import its standard-library encodings module.
These legacy tests are not counted as passed. The new factual runner executes
validated native operations and does not use that generated-code sandbox.

Historical G0 drafts were reused. The offline replay does not establish fresh
provider behavior, end-to-end latency, human editing acceptance or superiority
over another method. Full fresh-run provider/SAM integration requires a
separate measured run with explicitly configured credentials and budget.
