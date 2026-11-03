# Factual reconstruction pipeline

The current executable connects reference preparation, G0 construction, G1
factual inspection, G2 independent checking and repair planning, and local SVG
execution in one process. Each stage persists its inputs and receipts.

```text
reference → optional SAM3 assets → G0 SVG → paired views
          → G1 facts and differences → requested close-ups
          → G2 independent checks and scoped native edits
          → local execution → SVG and PNG
```

G1 records source and candidate readings separately. G2 checks every recorded
fact, can add evidenced differences, and assigns each issue either concrete
operations or an unresolved disposition. Native execution enforces target
scope, canvas identity, operation coverage, unique IDs and safe references.
Execution acceptance does not establish visual quality or editing-software
compatibility.

## Run

Install the Python requirements and the existing local SAM3 service described
in the legacy installation guide. Set credentials through the process
environment. Provider endpoints, model identifiers, limits and prices are
explicit in the configuration. No keys are stored in configuration files.

```bash
PYTHONPATH=src python -m figfox_plus factual \
  --image reference.png --out runs/example --config configs/factual.json
```

This measures the fresh process, including G0 preparation. Use `--no-sam` for
the SAM-off condition and `--no-repair` for the G0-only control.

## Continue from a G0 checkpoint

```bash
PYTHONPATH=src python -m figfox_plus factual \
  --image reference.png --out runs/continued --config configs/factual.json \
  --checkpoint checkpoints/example
```

A checkpoint contains `initial.svg` and `manifest.json`, with source SHA256,
initial SVG SHA256, the SAM assignment and generation provenance. All are
checked before the checkpoint is used. G0 and its descendants remain part of
the same sample lineage. An A/C comparison uses the same checkpoint; it does
not generate a second control draft.

Historical checkpoint continuation is identified as such. Its measured
continuation time is not a fresh end-to-end measurement. The 80-image cohort
reused historical drafts and has separate provider-stage measurements.

## Requests and recovery

Requests persist a unique identity and conservative charge reserve before
HTTP dispatch. Interrupted or ambiguous calls are not automatically resent.
Completed replies are reused only when input and response hashes match.
Provider output and usage are preserved even when later schema validation
fails. A fresh independent retry requires a distinct recorded attempt and
budget review. The configuration budget covers the entire output directory.

The new runner has offline integration and historical native-replay tests.
No new paid cohort was run for this release. Its default G1/G2 provider is
DeepSeek. The separate historical-cohort configuration records GPT-5.5 for
G1/G2, as used by the completed 80-image cohort; changing providers requires
fresh evaluation rather than relabeling historical results.

## Evaluation

The current registry has 17 criteria. The former bitmap-usage criterion D15
was removed; former D16–D18 map to D15–D17. Existing 18-item provider receipts
remain historical evidence. A 17-item report is a disclosed projection of
those judgments, not a newly issued provider receipt. Unknown and inapplicable
judgments are retained. Independent evaluation is separate from generation
latency and cost.
