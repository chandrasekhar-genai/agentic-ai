# ADR 0001: Human-in-the-loop remediation with an action allowlist

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

An LLM agent that can change production is only as safe as its worst
hallucination. Prompt injection is also a real risk here: pod logs and event
messages are attacker-influenced text that flows straight into the model.

## Decision

1. **Investigation tools are read-only.** The model can read pods, events, logs
   and metrics. It has no tool that writes.
2. **Remediation is a separate layer** (`remediation.py`) that the model cannot
   call. The model only *proposes* actions in its final answer.
3. **Allowlist.** Only `rollout_restart` and `scale_deployment` are executable,
   only on `deployment/*`, only in `ALLOWED_NAMESPACES`, and scale is bounded by
   `MAX_SCALE_REPLICAS`. Anything else is downgraded to a *recommendation* for a
   Git/IaC pull request.
4. **Named human approval.** Every executable action needs an `X-Approver`
   identity (and optionally a shared token behind an OIDC ingress). Approver and
   result are recorded on the incident.
5. **Kubernetes RBAC mirrors the allowlist**, so even a compromised process
   cannot exceed it: get/list pods, logs, events; get/patch deployments and
   deployments/scale. No Secrets, no delete, no exec.

## Consequences

- Mean time to *diagnose* drops; mean time to *act* still includes a human,
  which is the right trade-off until the agent has an evaluation track record.
- Live changes drift from Git. Every executable action is paired with a
  recommendation to commit the change (e.g. add an HPA), and Argo CD should
  ignore `/spec/replicas` on HPA-managed workloads.
- Expanding the allowlist is a deliberate code + RBAC change with review.
