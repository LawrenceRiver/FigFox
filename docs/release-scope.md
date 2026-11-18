# Public release scope — 2026-11-18

The factual G0/G1/G2 implementation, factual prompts and rendering runtime were compared byte-for-byte with the verified portable release prepared on 2026-11-03. They matched. That release followed the completed historical three-configuration, 80-figure study. The current 17-criterion registry also matches the local current registry.

This cleanup preserves that runner, native dependencies, standalone Skill and regression checks. The default factual configuration now explicitly uses the recorded all-GPT assignment, matching `historical-cohort.json`; the previous DeepSeek G1/G2 assignment is no longer the public default. This is a configuration selection, not a new evaluation or claim that model behavior is unchanged.

Removed from the current branch: the duplicate `research/two-stage-v1` source snapshot, the historical v2 scorer, old experiment scripts, obsolete architecture pages/images, the old root flow diagram and the manuscript PDF. Published history is preserved. Files removed from the current branch remain retrievable from earlier commits; this cleanup does not purge Git history.

The original cohort runner includes machine-specific recovery schedules and private archive paths. Those files and all raw experiments remain local. The portable runner provides the same construction/inspection/verification/local-edit method, not a byte-identical repackage of every historical controller. Later assistant visual reviews are separately described in [evaluation](evaluation.md).

The code-only verification for this publication makes no paid model requests and does not claim a fresh full-cohort reproduction. Existing validation limitations remain documented in [validation-factual.md](validation-factual.md).

`source-hashes.json` records the unchanged core file hashes for this cleanup. Dataset access policy is maintained separately and does not establish a software license. This release does not add a software license or invent a publication citation.

## README visual assets

The new editorial cover was generated with FigFox Generate V2, then reconstructed by the calling assistant through the standalone FigFox Skill as native text and geometry. A scoped typography repair and a separate actual text/shape editing probe were executed and rendered. The editable font is an approximation of the generated source; flat fills omit its fine raster texture. The Source and Editable SVG illustrations were subsequently replaced with the exact native `reference-image` and `final-editable-svg` groups from the author’s local architecture SVG. Their native geometry and embedded photo assets are preserved; nine red object-selection frames are editorial overlays. An author-requested bright orange FigFox wordmark (#FF7A1A), same-family text-depth layers, black supporting text, pale purple background dots and a hand-drawn rod arrow in the architecture’s greys (#A9ADB3/#4A5056) were added as scoped native SVG edits. The enlarged illustrations have no backing cards. These existing-SVG edits were applied through the FigFox Skill, and the README preview is rendered from the final SVG.

The three manuscript figures are reused unchanged from the author-provided original SVG/PNG files. No plot was regenerated and no measured values were altered. `docs/assets/asset-provenance.json` records their hashes. These selected illustrations do not release the full underlying image collection or raw experiment archive.
