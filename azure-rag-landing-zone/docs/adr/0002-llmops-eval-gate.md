# ADR 0002: Evaluation gate in the deployment pipeline

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

RAG quality regresses silently: a new model version, prompt edit, chunk size or
index change can lower answer quality without any error or alert. Unit tests do
not catch this.

## Decision

- Keep a versioned golden set (`evals/golden.jsonl`) with in-scope questions
  (expected source, facts that must appear) and out-of-scope questions (must be
  refused).
- Measure retrieval hit rate, answer recall, citation rate, refusal accuracy
  and p95 latency; thresholds live in `evals/thresholds.json` and changes to
  them go through review.
- Run the gate in CI against an offline deterministic baseline, and in the
  deploy workflow against the live API after ingestion. A failure stops the
  release.

## Consequences

- Quality becomes a release criterion with a visible history in job summaries.
- The golden set must grow with the corpus. Each production miss should become
  a new test case.
- Keyword-based answer checks are cheap but strict; an LLM-as-judge
  groundedness score is on the roadmap for semantic checks.
