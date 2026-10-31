# FigFox

从论文原图重建可编辑 SVG，再用原图证据检测、规划修复、执行与复核。原生执行完成与视觉质量通过分别报告。

Reconstruct scientific figures as editable SVGs, then detect, plan, execute and verify repairs against the reference. Execution completion is reported separately from visual quality.

## Latest architecture · 2026-10-31

![FigFox bounded two-stage architecture](docs/assets/figfox-two-stage-20261031.png)

1. **Shared reconstruction:** two GPT-5.5 drafts per original, A1 without SAM and A2 with local SAM3. Each is shared by the matching C0/C1 branches after provenance checks.
2. **Four parallel branches:** S0C0/S0C1/S1C0/S1C1, each with one joint detection call, one repair-planning call, local native execution/rendering and one post-render verifier call. DeepSeek thinking is disabled; normal total is 12 DeepSeek requests per original.
3. **Separate evaluation:** saved outputs are assessed post-hoc using FigFox scoring standard v2 (D01–D18), rather than adding grading calls inside the generation chain.

- [Architecture, branch mapping and measured generation status](docs/architecture-two-stage.md)
- [Actual bounded experiment code and source hashes](research/two-stage-v1/README.md)
- [Unified v2 evaluation protocol](docs/evaluation-unified-v2.md)
- [Supplied v2 scoring implementation and registry](benchmark/figfox-score-v2/README.md)

The latest generation cohort completed **80/80 originals and 320/320 native conditions**. Native visual-pass flags were **0/320** (`needs_followup`); this is not a claim of successful visual reconstruction or a formal grading result. Raw failures and unknowns are preserved. No benchmark win is asserted here.

## Existing package and legacy entry

The package remains `figfox_plus`. The existing `chain` executable is the **older** flow, not the newly published two-stage experiment supervisor. Its installation, SAM3 configuration and usage are preserved in the [legacy package instructions](docs/legacy-chain-readme-20261030.md). The new supervisor is published as an auditable experiment snapshot; workstation/runtime/input bindings are explicit, and no unsupported portable one-command claim is made.

API keys, model weights, dataset images, raw paid responses and private accounting are not included. Use an explicitly selected local environment file or process environment for credentials.
