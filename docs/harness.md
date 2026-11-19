# FigFox harness

The API runner reconstructs a scientific figure from a source image. G0 produces the editable SVG draft. G1 compares the rendered draft with the source and records visible differences. G2 checks those differences and identifies the SVG objects to edit. Local tools apply the changes and render the final PNG.

Use `--no-sam` to run without an external segmentation service, or `--no-repair` to stop at the draft. See the [runner guide](factual-pipeline.md) for commands and checkpoint recovery, and the [architecture diagram](../README.md#architecture) for an overview.

The [standalone Skill](skill.md) uses the current assistant for visual inspection and local tools for editing. The [evaluation guide](evaluation.md) describes how to assess the resulting figure.
