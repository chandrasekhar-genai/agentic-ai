# ADR 0002: Azure OpenAI behind a provider interface, with an offline planner

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

Enterprises in regulated and sovereign environments need the model to stay in a
specific region and tenant, authenticate without static keys, and be testable
in CI where no model endpoint is reachable.

## Decision

- A minimal `LLM.chat(messages, tools)` interface with two implementations:
  - `AzureOpenAILLM` for Azure OpenAI / Azure AI Foundry deployments. With no
    `AZURE_OPENAI_API_KEY` set it authenticates with Entra ID through
    `DefaultAzureCredential` (AKS Workload Identity in-cluster), so no secret
    is stored in Kubernetes.
  - `OfflineLLM`, a deterministic rule-based planner that follows the same tool
    protocol.
- `temperature=0` and a bounded step count (`MAX_AGENT_STEPS`) for repeatable
  investigations.

## Consequences

- The full pipeline (webhook → tools → verdict → approval) runs in CI and on a
  laptop with `make demo`.
- The offline planner doubles as a baseline: a new model or prompt should beat
  it on the recorded incident scenarios before it ships.
- Adding another provider (Anthropic, a self-hosted model) is one class.
