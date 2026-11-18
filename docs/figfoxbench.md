# FigFoxBench-v3

[Dataset on Hugging Face](https://huggingface.co/datasets/FigFoxBench/FigFoxBench-v3) · [Copyright and use restrictions](figfoxbench-terms.md)

FigFoxBench-v3 contains 100 scientific figures extracted from conference papers. It groups figures into four levels of visual clutter using **FC-adapted**, a score based on the color, contrast, and orientation channels of Feature Congestion. Channel normalization scales are calibrated on these 100 images, and quartiles define the bin boundaries. The score measures relative clutter within this collection; it is not a validated measure of reconstruction difficulty or human perception.

| Bin | Figures |
| --- | ---: |
| C1: low | 25 |
| C2: medium-low | 25 |
| C3: medium-high | 25 |
| C4: high | 25 |

The bin directories and `sources/` retain copies of the same images. There are 100 samples, not 200. Source papers, per-image scores, file hashes, frozen parameters, and reproduction records are retained in the Hugging Face repository.

## Access and permitted purpose

The dataset is **private**. Sign in to an authorized Hugging Face account to access it. If access is needed, contact a FigFoxBench maintainer through an existing project contact; this page does not provide automatic access or a public download. Authorization is subject to the [dataset access policy](figfoxbench-terms.md) and applicable third-party rights.

The intended purpose is noncommercial scientific-figure reconstruction benchmarking and evaluation of existing models. Commercial use and model training are prohibited by the access policy. Do not submit dataset content to a service that retains it for model training. An authorized evaluation does not authorize incorporating inputs, reconstructions, annotations, or derived examples into training corpora.

## Source rights and limitations

The source inventory contains 50 CVPR figures, 16 ICLR figures, 17 NeurIPS figures, and 17 ICML figures from 79 source-paper URLs. The source/license screening dated 2026-11-18 found:

| Count | Evidence available |
| --- | --- |
| 50 | No explicit redistribution license found in the inspected CVPR source pages and PDFs |
| 33 | Exact official submission records specify CC BY 4.0 |
| 13 | PMLR publisher-policy evidence for CC BY 4.0; individual license records not all retrieved |
| 3 | CC BY-NC-SA 4.0 (image IDs 068, 077, 083) |
| 1 | CC BY-NC-ND 4.0 (image ID 067) |

These are paper-level findings, not figure-level clearance. Figure/page matching, version equivalence, crop history, and embedded third-party credits remain to be checked. The full [source audit](https://huggingface.co/datasets/FigFoxBench/FigFoxBench-v3/blob/main/docs/copyright-audit.md) is available to authorized dataset users. Private hosting does not itself supply copyright permission.

This GitHub integration contains documentation and links only: no dataset image files, thumbnail sheets, archive, or access credentials. It does not claim that the 100-figure collection is identical to the historical 80-figure study described elsewhere in this repository.
