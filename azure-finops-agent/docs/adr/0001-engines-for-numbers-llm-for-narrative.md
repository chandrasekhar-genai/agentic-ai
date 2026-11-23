# ADR 0001: Numbers from deterministic engines, narrative from the model

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

FinOps reports go to finance and engineering leads, and a single wrong figure
destroys trust in the whole report. LLMs are good at explaining and
prioritising but unreliable at arithmetic over thousands of cost rows.

## Decision

- **Anomaly detection** uses a robust z-score (median and MAD over a 14-day
  baseline) per service. Median/MAD is not inflated by previous spikes, unlike
  mean/stddev, so repeated incidents are still detected.
- **Optimisation rules** are plain, conservative, unit-tested Python. Savings
  are estimated from each resource's own last-30-day cost, so they are in the
  billing currency and need no price list.
- **The agent** sees results only through tools (`list_findings`,
  `list_anomalies`, `get_service_trend`) and is instructed to use only the
  numbers they return. It decides what to drill into and writes the narrative.
- **Changes are a Terraform patch in a pull request**, never direct API calls.
  Resources not managed in Terraform are listed for manual action.

## Consequences

- Reports are reproducible: the same export gives the same numbers, with or
  without a model (an offline template writes the summary in CI).
- Rule thresholds are explicit and reviewable; tuning them is a code change.
- The model can be swapped or upgraded without re-validating the maths.
