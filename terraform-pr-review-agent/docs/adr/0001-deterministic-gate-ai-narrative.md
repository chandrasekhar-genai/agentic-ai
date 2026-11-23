# ADR 0001: Deterministic gate, AI narrative

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

Reviewers skim large Terraform plans and miss the one line that matters: a
replace of a database, a rule opening SSH to the internet, a resource in the
wrong region. An LLM summary helps humans read the plan faster, but an LLM must
not decide whether a change is allowed: it can be wrong, and plan content
(names, tags, descriptions) is attacker-controllable text.

## Decision

- **Pass/fail comes only from deterministic rules** evaluated on the *planned
  values* (`terraform show -json`), not on source code. This catches values that
  come from variables, modules and data sources, which static scanners miss.
- **Checkov and Infracost** are optional inputs and are reported, not
  re-implemented.
- **The model writes the narrative only**: what changes, why it is risky, what
  to ask the author. It has no tools, and its output is labelled as AI-generated.
  If the model is unavailable the comment is still posted with full policy
  results.
- **One comment per PR**, updated in place (hidden marker), so the thread stays
  readable across pushes.
- **Exceptions are explicit** (`ignore = ["rule:address"]` in `.tfreview.toml`)
  and therefore reviewed in the same pull request.

## Consequences

- Teams can adopt it in "report only" mode (`fail-on: never`) and tighten later.
- New platform rules are small Python functions with unit tests.
- The rules are Azure-focused today; other providers need their own rule set.
