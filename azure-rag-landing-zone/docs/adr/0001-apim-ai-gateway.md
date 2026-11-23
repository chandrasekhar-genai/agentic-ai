# ADR 0001: API Management as the AI gateway in front of a private Azure OpenAI

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

Several apps and jobs will share the same Azure OpenAI capacity. We need to
know who is consuming tokens, stop one client from exhausting the quota,
handle throttling centrally, and avoid distributing model keys.

## Options

1. Apps call Azure OpenAI directly with their own managed identities.
2. Apps call through API Management, which calls Azure OpenAI with its identity.

## Decision

Option 2. APIM is injected into the VNet in **external** mode, so it can reach
the private endpoint of Azure OpenAI while clients authenticate with Entra ID
tokens validated by `validate-azure-ad-token`. Key-based access is disabled on
Azure OpenAI (`local_auth_enabled = false`), so the gateway is the only path.

## Consequences

- Per-identity token budgets (`azure-openai-token-limit`) and central retry.
- One place for request logging, usage attribution and adding a second regional
  backend for failover later.
- Extra cost and latency of APIM. Developer SKU for non-production, Premium for
  production (SLA, multi-zone).
- APIM in a VNet needs specific NSG rules (management 3443, load balancer 6390,
  outbound to Storage, SQL, Key Vault and Azure Monitor); they are in
  `network.tf`.
