# FigFox

Reconstruct scientific figures as editable SVGs using reference-grounded inspection and scoped native edits.

## Current pipeline

Reference image → optional SAM3 assets → GPT-5.5 G0 → G1 factual inspection → G2 independent verification and repair plan → deterministic native execution → SVG and PNG.

The `factual` command runs these stages in one process. It also supports hash-verified G0 checkpoints, retaining the source-to-draft-to-final lineage. Execution acceptance and independent quality evaluation are reported separately.

```bash
pip install -r requirements.txt
PYTHONPATH=src python -m figfox_plus factual --image reference.png --out runs/example --config configs/factual.json
```

Set `OPENAI_API_KEY` and `DEEPSEEK_API_KEY` in the process environment. SAM-enabled runs require the existing local SAM3 service. The example configuration specifies provider identifiers, limits and recorded price assumptions.

- [Pipeline, checkpoint continuation and validation boundaries](docs/factual-pipeline.md)
- [17-criterion evaluation registry](benchmark/figfox-score-v3/README.md)
- [Installation and local SAM3 setup](docs/legacy-chain-readme-20261030.md)
- [Earlier architecture](docs/architecture-history-20261101.md)

The historical 80-image ablation reused 160 verified G0 drafts. Historical continuation timing is not a fresh continuous end-to-end measurement. The public runner is tested offline; no new paid cohort is implied by this release. Model responses, private accounting, dataset images, credentials and model weights are distributed separately from source code.
