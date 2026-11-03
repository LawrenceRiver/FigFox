# FigFox

从论文原图重建可编辑 SVG，再用原图证据检测、规划修复、执行与复核。原生执行完成与视觉质量通过分别报告。

Reconstruct scientific figures as editable SVGs, then detect, plan, execute and verify repairs against the reference. Execution completion is reported separately from visual quality.

## Current research architecture · 2026-11-01

![FigFox visual-gated research pipeline](docs/assets/figfox-visual-gated-20261101.png)

Reference image and verified SAM3 assets → GPT-5.5 draft → **D1 practical initial gate** → **C1 issue identification** → **C2 scoped native-method repair** → local execution/render → **D2 visual review and bounded redispatch** → validated checkpoint selection/merge → editable SVG, PNG and remaining-issue record.

D1 prefers continuing with local repair; systemic failure can request local-first regeneration. D2 reuses existing C2 method subsets, supports early stopping and at most two repair rounds. Formal evaluation is separate.

**Validation status:** this is the latest research design with isolated assisted prototype tests. D1 adaptive local-regeneration integration, a complete autonomous latest-version cohort, and final end-to-end efficiency remain unvalidated. The legacy `chain` executable has not silently become this full supervisor. No benchmark ranking is claimed.

- [Complete chain, evidence bindings and implementation boundaries](docs/architecture-visual-gated.md)
- [Archived bounded two-stage protocol](docs/architecture-two-stage.md)
- [Separate v2 evaluation protocol](docs/evaluation-unified-v2.md)
- [Supplied v2 scoring implementation and registry](benchmark/figfox-score-v2/README.md)

Current experimental result tables and post-hoc repair materials are **internal review only** and are not part of this public architecture update. The private experiment archive and tables are distributed separately.

## Existing package and legacy entry

The package remains `figfox_plus`. The existing `chain` executable is the **older** flow, not the newly published two-stage experiment supervisor. Its installation, SAM3 configuration and usage are preserved in the [legacy package instructions](docs/legacy-chain-readme-20261030.md). The new supervisor is published as an auditable experiment snapshot; workstation/runtime/input bindings are explicit, and no unsupported portable one-command claim is made.

API keys, model weights, dataset images, raw paid responses and private accounting are not included. Use an explicitly selected local environment file or process environment for credentials.
