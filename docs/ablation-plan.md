# Historical SAM × code-methods plan

`python -m figfox_plus.ablation_plan --manifest PATH --out PATH` validates the
historical-80 manifest and writes a plan. Run it from this repository with
`PYTHONPATH=src` when the package is not installed. The command only reads the
manifest and the original source images to verify SHA-256 hashes. It creates
the output with exclusive creation and refuses to overwrite an existing file.
There is no execute option or paid model/SAM call in this module.

The public CLI requires exactly 80 unique sample IDs, dataset IDs, source
hashes, and consecutive historical orders. It verifies the sample ID to
dataset ID mapping, matched status, historical and dataset source group and FC
bin agreement, all four 20-image FC strata, explicit empty unmatched,
ambiguous, and replacement lists, the source filename binding, and each
source file's actual SHA-256. A private test helper permits a smaller synthetic
manifest; it cannot relax the public CLI's 80-image requirement.

Each source produces S0C0, S1C0, S0C1, and S1C1 once. Within each historical
sample the execution order rotates by one cell for each successive historical
order, giving each position 20 appearances of each cell across 80 samples.
S1C1 is the one new formal full-capability cell per source. The plan does not
rerun or count other historical comparisons. Each cell carries the original
path and hash, historical order and strata, strict capability policy and its
canonical hash, a unique output directory, and an initial attempt identity.
The two SAM-on cells for a sample share a reuse-group identity for a future
verified real SAM manifest; this file does not create one.

The common requested configuration is GPT-5.5 at medium effort with 32,768
maximum output tokens for the first pass, and DeepSeek-flash at high effort
with a requested 64,000 output-token maximum for review. Review follows DS1,
DS2, and the existing conditional receipt-driven followup, capped at three
requests. The eventual runtime must apply context-capacity preflight and
record the actual request limits. All cells use the same common quality and
conditional rules. Capability availability, relevant tool descriptions, and
SAM evidence differ, so the plan does not claim byte-identical prompts. It
requires the runtime to verify shared policy hashes.

The saved artifact is deliberately `status: planned` and
`paid_execution_allowed: false`. Its SAM service and cumulative budget are
unverified. Before paid generation, a separate executor must recheck source
and capability hashes, verify a real SAM service and reusable manifest for
SAM-on cells, establish a cumulative budget bound and reservation, and log
every unique attempt. Runtime evidence must include actual intervention
counts, usage, elapsed time, terminal committed image hashes, and explicit
unknown or unreviewed outcomes. The plan does not estimate an unsupported
cost or authorize retries.
