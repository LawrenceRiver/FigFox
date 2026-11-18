# FigFox 17-criterion registry

`registry.json` defines D01–D17. `migration.json` records the mapping from historical 18-criterion provider records. The former D15 bitmap-usage criterion is excluded; former D16–D18 shift to D15–D17.

For current harness/human aggregates, pass, partial pass and fail map to 1, 0.5 and 0; compute `100 × sum(valid item scores) / valid item count`. Exclude unknown and not-applicable judgments, report their counts and retain the valid-item mask. A zero valid denominator is unavailable. D09 is retained for historical display and excluded from current aggregates.

Historical binary provider summaries may use `100 × pass / (pass + fail)`; label them separately and do not present them as the current partial-credit aggregate. Preserve original provider receipts, numbering and hashes. A projected 17-item record is not a new provider evaluation.

Real edit operations are required for editing-software claims. See the [evaluation protocol](../../docs/evaluation.md).
