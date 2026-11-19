# Factual reconstruction pipeline

The API runner builds an SVG draft (G0), inspects it alongside the source (G1), then verifies differences and plans local edits (G2). It writes the editable figure to `final.svg` and its preview to `final.png`.

## Run

Follow the [setup guide](setup.md) and set `OPENAI_API_KEY` in your shell. Review the models and budget in `configs/factual.json` before running.

```bash
PYTHONPATH=src python -m figfox_plus factual \
  --image reference.png --out runs/example --config configs/factual.json --no-sam
```

Replace `reference.png` with your source. To use SAM3, start the [optional service](setup.md#optional-sam3) and omit `--no-sam`. Add `--no-repair` for draft-only output.

## Continue from a G0 checkpoint

Reuse a saved draft that matches the source image and the original SAM setting. For a draft created without SAM3, run:

```bash
PYTHONPATH=src python -m figfox_plus factual \
  --image reference.png --out runs/continued --config configs/factual.json \
  --no-sam --checkpoint runs/example/G0
```

The runner checks the source and SVG hashes against the checkpoint manifest. It reuses the verified draft and runs the remaining stages in the new output directory.

## Interrupted runs

When resuming, use the same inputs, settings and output directory. The runner checks saved requests and results before reuse. If a request failed with an uncertain charge, check the provider’s records before starting a separate attempt. `result.json` reports execution status. Compare the rendered PNG with the source to assess visual fidelity.
