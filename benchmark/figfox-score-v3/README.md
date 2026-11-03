# FigFox 17-criterion registry

`registry.json` defines D01–D17. `migration.json` records the mapping from the
historical 18-criterion registry. The former D15 bitmap-usage criterion is
excluded; the final three criteria shift down by one.

For an aggregate criterion score, report `100 × pass / (pass + fail)` alongside
the pass, fail, unknown and not-applicable counts. If the denominator is zero,
the score is unavailable. This statistic is not an editing-software success
rate and does not convert unknown judgments to passes.

Historical provider responses retain their original numbering and hashes.
Do not present projected 17-item records as new provider evaluations.
