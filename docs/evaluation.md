# Evaluation

The current [registry](../benchmark/figfox-score-v3/registry.json) defines D01–D17. Keep fidelity, editability and overall scores distinguishable.

## Judgment sources

- Historical API receipts retain their original model identities, numbering and hashes.
- Current assistant-harness judgments require actual image inspection and declared reviewer origin. They are model-assisted judgments, not independent human reviews or new paid API receipts.
- Human editability claims require real editing operations and their evidence. A screenshot, valid SVG or executed transaction is not enough to establish editing-software acceptance.

For current harness/human judgments, pass, partial pass and fail map to 1, 0.5 and 0. Exclude unknown and not-applicable judgments from the score denominator and report their counts separately. A zero valid denominator is unavailable. D09 remains available for historical display and is excluded from current aggregates. Method comparisons and ablations may have different valid-item masks; report the mask and do not substitute one aggregate for another.

The old 18-criterion API protocol is historical. Its mapping is retained in [migration.json](../benchmark/figfox-score-v3/migration.json); mapping old judgments does not create new provider evaluations. In particular, the old binary pass/(pass+fail) statistic differs from the current partial-credit aggregate.

## Study and dataset identities

The historical ablation cohort contains 80 figures. FigFoxBench-v3 is a separate 100-figure collection. Do not relabel the former as evaluation on the latter without an actual new run.

Full and Without repair share the same hash-verified initial draft. Without SAM uses a separately generated initial draft. These three conditions do not form a complete factorial design. Retain failures, retries, unknown-charge reserves and timing scope in private experiment records. Continued historical drafts do not establish fresh end-to-end latency.

## Published scope

This repository publishes the criterion registry, reconstruction code and an offline archive verifier. It does not publish raw study outputs, provider responses, per-figure judgments or private source images. `scripts/verify_ablation.py` checks a locally supplied historical archive; it is not an automatic visual scorer.
