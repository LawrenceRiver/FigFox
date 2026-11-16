# FigFox

**Reconstruct scientific figures as editable SVGs, then repair local discrepancies against the original image.**

Scientific figures need more than a similar appearance: labels must retain their meaning, repeated objects must retain their counts, and arrows must connect the right components. FigFox starts with a complete vision–language model draft, inspects it alongside the source, and applies targeted edits to existing SVG objects.

The output combines native text, shapes, paths, and groups with optional source-derived image assets. Photographs and textures can be preserved as movable, replaceable images while surrounding labels and connections remain native SVG elements.

## How it works

```text
Source figure
    ↓
Optional SAM3 asset extraction
    ↓
G0 · Complete SVG draft
    ↓
G1 · Paired source/draft inspection and factual differences
    ↓
G2 · Fact verification, target identification, and repair plan
    ↓
Local SVG operations → final SVG + rendered PNG
```

- **Reconstruct a complete draft.** Preserve the figure's overall layout and relationships before intervening locally.
- **Inspect paired evidence.** Compare source and draft views, retaining full-image context and requested close-ups. Record source and candidate readings separately.
- **Identify the intended object.** Use object IDs, containers, neighbours, and relationships to connect a visible discrepancy to an SVG target.
- **Apply scoped edits.** Execute ordered operations such as changing text or attributes, replacing nodes, or inserting source-derived assets. Validate object references and edit scope, and record unresolved issues.

Execution acceptance records that the planned operations were applied. Fidelity and practical editability require separate evaluation.

## Quick start

Clone the repository and install its Python dependencies in a virtual environment. The current runner uses POSIX file locking; use macOS or Linux.

```bash
git clone https://github.com/LawrenceRiver/FigFox.git
cd FigFox
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

Configure provider credentials in your environment and review the selected JSON configuration before running. Model identifiers, endpoints, token limits, recorded price assumptions, and the run budget are explicit configuration fields.

The [`historical-cohort.json`](configs/historical-cohort.json) configuration records GPT-5.5 for G0, G1, and G2 and uses `OPENAI_API_KEY`. Start without SAM3:

```bash
PYTHONPATH=src python -m figfox_plus factual \
  --image reference.png \
  --out runs/example \
  --config configs/historical-cohort.json \
  --no-sam
```

For SAM-assisted reconstruction, set up the local SAM3 service using the [installation guide](docs/legacy-chain-readme-20261030.md), then omit `--no-sam`. SAM is an optional source-asset reuse route; it is useful when selected image content should be carried over rather than redrawn.

[`factual.json`](configs/factual.json) is a separate configuration with GPT-5.5 for G0 and DeepSeek for G1/G2. It requires both `OPENAI_API_KEY` and `DEEPSEEK_API_KEY`. These provider settings describe different configurations; switching between them does not reproduce the same experimental condition. Check current provider availability and prices before making requests.

### Outputs and recovery

The run directory contains `final.svg`, `final.png`, and `result.json`, alongside stage artifacts and request receipts. The result records artifact hashes, execution status, and timing scope; it does not assign an automatic visual-quality pass.

To continue from an existing G0 draft, add:

```bash
--checkpoint checkpoints/example
```

A checkpoint contains `initial.svg` and a `manifest.json` binding it to the source image, SAM assignment, and generation provenance. The runner verifies these bindings before reuse. Historical checkpoint continuation time is reported separately from a fresh run starting at the source image.

Use `--no-repair` to stop at the draft control. For a same-draft repair comparison, reuse the same verified G0 checkpoint for repaired and unrepaired outputs. Interrupted or ambiguous provider requests retain their identities and charge reserves rather than being automatically resent.

## Evaluation

The [17-criterion registry](benchmark/figfox-score-v3/README.md) covers scientific content, relationships and structure, visual presentation, editability, and conditional image/chart fidelity. The current research protocol uses saved Codex harness visual judgments and representative editing probes. Harness judgments are model-assisted assessments, not independent human reviews or new API scoring receipts.

Current reporting distinguishes fidelity, editability, and overall quality. Pass, partial pass, and failure map to 1, 0.5, and 0. D09 is retained for historical display and excluded from current aggregates. Unknown and not-applicable judgments remain explicit and are excluded from score denominators; editing claims require actual operation evidence. Method comparisons and ablations can use different valid-item masks, so their aggregate scores are not interchangeable.

The fixed 80-figure study compares three configurations:

| Configuration | SAM-assisted draft | Repair | Draft relationship |
| --- | --- | --- | --- |
| Full | Yes | Yes | Reference configuration |
| Without SAM | No | Yes | Separately generated SAM-off draft |
| Without repair | Yes | No | Exactly the same draft as Full |

Full versus its unrepaired draft measures the complete repair path. The SAM comparison also changes the draft; the three conditions do not form a complete factorial experiment. SAM remains optional, without an established aggregate quality advantage in the current study. Repair quality and editing utility are assessed separately.

## Repository scope

This repository contains the public reconstruction runner, native editing implementation, prompts, configuration examples, criterion registry, and historical archive-verification script. The `factual` command is the reconstruction entry point; `chain` is an older workflow.

The later harness review interface, revised statistics scripts, and web-editor evidence are not yet packaged here. The registry and historical verification script alone do not reproduce the current research evaluation. Saved visual judgments also require the corresponding artifacts and review evidence; they cannot be recreated by a statistics script alone.

The manuscript, supplementary files, source-image collection, experimental result archives, raw provider responses, credentials, and model weights are not included in this repository. The public runner has offline integration and historical native-replay checks; this does not establish a fresh end-to-end evaluation of every configuration.

## Documentation

- [Runner, checkpoints, and request recovery](docs/factual-pipeline.md)
- [17-criterion registry and historical numbering migration](benchmark/figfox-score-v3/README.md)
- [Local SAM3 setup and legacy installation reference](docs/legacy-chain-readme-20261030.md)
- [Historical ablation archive verifier](scripts/verify_ablation.py)
- [Earlier architecture](docs/architecture-history-20261101.md)
