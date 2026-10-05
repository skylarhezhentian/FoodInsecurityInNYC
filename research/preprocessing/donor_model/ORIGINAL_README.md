# Food-Bank Donor-Supply Estimation Model

Turns a food bank's *partial, curated* public donor list into a *complete* estimate of donor-level
supply (lbs/yr), and transfers to food banks that publish less. Calibrated on **City Harvest**,
cross-checked against **Food Bank For NYC** FY2025 audited financials.

## Headline finding
At a 90M-lb control total, publicly **named** donors (12 with amounts + 55 named) are only
**~32 %** of rescued volume; **~68 %** is an **unlisted tail of ~3,000 small donors**. Models built
on published names alone capture a quarter of the mass — the tail must be modelled explicitly.

## Layout
```
src/data.py          inputs, canonical schema, de-duplication policy
src/model.py         estimation core (numpy-only: log-normal MLE, rank-size, raking, transfer)
src/run_pipeline.py  end-to-end → data/results.json + data/per_donor_estimates.csv + stdout report
src/figures.py       → figures/fig1..6.png
docs/research_writeup.md   full methodology + justified choices + validation + limitations
```

## Run
```bash
python3 -m venv .venv && .venv/bin/pip install numpy matplotlib
.venv/bin/python src/run_pipeline.py
.venv/bin/python src/figures.py
```

## Method in one paragraph
S1 fix units (lbs; $1.90/lb bridge) and de-dup aggregates. S2 fit the heavy-tailed **shape**
(log-normal + power-law) from the 12 anchors. S3 build a portable **per-category recovery-rate**
table from sector-surplus priors. S4 **rake** A (published) + B (named) + C (unlisted tail) to a
control total. S5 **transfer** to a new org from only its throughput + a business-mix vector.
Validated by leave-one-out and by cross-organisation $-reconciliation against Food Bank NYC.

> Dependency note: built numpy+matplotlib-only because the host's stdlib `pydoc` is corrupted
> (breaks scipy/pandas). See `docs/research_writeup.md` §8.
