# FigFox harness

The released reconstruction workflow is:

1. **G0 — complete construction.** Read the source and construct a complete editable SVG. Optional SAM3 assets preserve selected source image content.
2. **G1 — paired inspection.** Compare actual source/draft whole views and paired regions. Record source readings, candidate readings, literal facts, differences and uncertainty. Request tighter crops when evidence is insufficient.
3. **G2 — verification and repair planning.** Recheck G1 facts, bind differences to native object IDs, and produce ordered, scoped edit transactions or explicit unresolved dispositions.
4. **Local execution.** Validate the plan, protect SVG scope and references, execute edits and render SVG/PNG outputs. Execution acceptance is separate from fidelity and practical editability.

## Two execution modes

The **API runner** is `src/figfox_plus/factual/pipeline.py`; it uses the explicit configurations in `configs/` and the G1/G2 prompts in `prompts/factual/`. G0 reuses the shared native construction implementation. Internal native helpers retained for this dependency chain are not additional published experimental methods.

The **standalone Skill** performs the construction and visual reasoning through the calling assistant, followed by the bundled local tools. It is self-contained under `skills/figfox/`. Sequential roles within the same assistant must not be reported as independent reviewers.

The later evaluation harness inspects saved images directly and records its actual origin. It does not create new independent API receipts. See [evaluation](evaluation.md) for the 17-criterion protocol. A statistics script alone cannot recreate a visual judgment.

## Historical controls

The 80-figure study used three configurations: Full (SAM + repair), Without SAM (separately generated SAM-off draft + repair), and Without repair (the exact Full G0). The portable runner supports `--no-sam`, `--no-repair` and hash-verified checkpoints; it does not silently generate or resume a paid 80-figure cohort. Selecting a model configuration is an explicit choice, not evidence that a historical experiment was rerun.

See [runner usage](factual-pipeline.md), [release provenance](release-scope.md), and [Skill instructions](../skills/figfox/SKILL.md).
