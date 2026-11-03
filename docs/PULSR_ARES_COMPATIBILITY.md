# Pulsr → ARES: compatibility audit

Reference: https://github.com/0xCodez/pulsr (MIT, © 2026 Pulsr contributors);
`docs/ALGORITHMS.md`, `Shared/ScoreEngine.swift`, `docs/design/pulsr-iris.html`.

## Safe reuse already included in this integration

- **Recovery iris**: original responsive CSS design inspired by Pulsr's orb,
  but fed directly by WHOOP's existing native Recovery percentage and ARES's
  night-quality filter. No duplicate or fabricated recovery model.
- **Trend panels**: ARES already has its own longitudinal RMSSD, resting HR,
  sleep, training load, planned sessions and weekly trends; retain them.
- **Behavior diary**: ARES LAB already has auditable coffee, dinner-end and
  bedtime events plus *exploratory* associations of dinner/caffeine timing
  with WHOOP-measured sleep, HRV and resting HR, requiring meaningful sample
  sizes. Do not replace this with simplistic causal claims.

## Do not import incompatible formulas

| Pulsr component | Inputs/assumptions | ARES status |
|---|---|---|
| Recovery logistic score | Apple Health **SDNN** HRV, RHR, respiratory rate, sleep; 30-day prior | WHOOP provides **RMSSD**, not SDNN; retain native Recovery and existing ARES baseline. |
| Strain 0–21 via Banister TRIMP | Minute-by-minute heart-rate stream and individualized HRmax | ARES imports WHOOP cycles/workout summaries and Tredict; no validated continuous minute HR stream. Show WHOOP's original strain when available; do not recompute it. |
| Stress monitor 0–3 | Minute-level heart rate outside training | Not available under current source contract; omit. |
| Sleep need / performance | Sleep duration, regularity, stages, debt, prior-day strain | WHOOP publishes some sleep performance and need fields; do not pretend unverified source fields are directly present. Consider separately after source mapping and validation. |
| Body Age / Healthspan | VO₂max, age/sex norms, HRV type, steps, Z2–3, sleep | Motivational model, not clinical; require complete reliable inputs and explicit uncertainty before enabling. |
| Journal recovery impact | Behavior yes/no, next-day recovery, sufficient comparable nights | ARES LAB has different captured events. Its current time-banded and quality-filtered analyses are more transparent about missingness and confounding. |

## Acceptance criteria for any additional Pulsr-derived metric

1. Declare exact input fields, source device and time zone.
2. Keep WHOOP RMSSD and Apple Health SDNN distinct; neither may be
   automatically substituted for the other.
3. Never infer absent minute HR, sleep stages, fitness scores or training
   compliance from summaries alone.
4. Expose sample size, missingness, calibration stage, units, methodology
   and uncertainty clearly.
5. Unit-test synthetic edge cases and evaluate on de-identified historical
   windows before showing it as a stable ARES metric.
6. Respect Pulsr's MIT attribution if adapting software.

ARES Scientific Atelier remains the computational source of truth in Gonzalo OS.
