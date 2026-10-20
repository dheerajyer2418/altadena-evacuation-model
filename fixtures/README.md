# Offline demonstration fixture — **SYNTHETIC, not Altadena**

These files let the model run with **no internet and no credentials**. Anything
produced from them is a **synthetic test result**, not an Altadena finding.

| file | what it is |
|---|---|
| `toy_network.graphml` | deterministic 4×4 grid from `make_toy_grid()`; node (0,0) is NW, the south row are safety destinations. Coordinates sit near Altadena only so maps render. |
| `synthetic_households.csv` | a small synthetic household sample from `make_synthetic(seed=12345)` + IPU synthesis. |

The offline demo (`python -m scripts.run_demo`) regenerates equivalent inputs
deterministically from the same seeds and runs the full pipeline (population →
network → hazard → all four AV policies → metrics/plots/map) into
`outputs/demo/`, labeling every result as synthetic.
