# Agentic AI for DevOps & Cloud Platforms

Four working projects where **agentic AI meets platform engineering**: incident
response, RAG platforms, FinOps and infrastructure review on Azure and Kubernetes.
Each one is built the way I'd run it in production: least-privilege identities,
GitOps, CI quality gates, and humans in the loop wherever an AI could change
something that matters.

| Project | What it does | Highlights |
|---|---|---|
| [**aiops-incident-agent**](aiops-incident-agent) [![ci](https://github.com/chandrasekhar-genai/agentic-ai/actions/workflows/aiops-incident-agent.yml/badge.svg)](https://github.com/chandrasekhar-genai/agentic-ai/actions/workflows/aiops-incident-agent.yml) | Takes a Prometheus alert, investigates it like an on-call SRE (pods, events, logs, PromQL), posts the root cause to Slack/Teams and proposes a fix that runs **only after an engineer approves it** | Azure OpenAI tool calling · read-only tools · action allowlist · least-privilege RBAC · Helm · Argo CD · Trivy |
| [**azure-rag-landing-zone**](azure-rag-landing-zone) [![ci](https://github.com/chandrasekhar-genai/agentic-ai/actions/workflows/azure-rag-landing-zone.yml/badge.svg)](https://github.com/chandrasekhar-genai/agentic-ai/actions/workflows/azure-rag-landing-zone.yml) | Private, keyless RAG platform on Azure, in Terraform | Private endpoints · Entra ID only · **APIM AI gateway** with per-identity token limits · Container Apps · **LLMOps eval gate** that blocks bad releases |
| [**azure-finops-agent**](azure-finops-agent) [![ci](https://github.com/chandrasekhar-genai/agentic-ai/actions/workflows/azure-finops-agent.yml/badge.svg)](https://github.com/chandrasekhar-genai/agentic-ai/actions/workflows/azure-finops-agent.yml) | Weekly Azure cost review: anomalies, orphaned/idle/oversized resources, and a **Terraform pull request** with the fixes | Robust anomaly detection · Resource Graph KQL · OIDC GitHub Actions · numbers from code, narrative from the model |
| [**terraform-pr-review-agent**](terraform-pr-review-agent) [![ci](https://github.com/chandrasekhar-genai/agentic-ai/actions/workflows/terraform-pr-review-agent.yml/badge.svg)](https://github.com/chandrasekhar-genai/agentic-ai/actions/workflows/terraform-pr-review-agent.yml) | GitHub Action that reviews Terraform PRs: landing-zone guardrails on the **plan**, Checkov, Infracost and an AI-written review comment | Policy-as-code · destructive-change and data-residency checks · prompt-injection aware · deterministic pass/fail |

## Principles across all four

- **Deterministic decisions, AI explanations.** Pass/fail, savings figures and
  remediation permissions come from tested code. The model investigates,
  explains and prioritises.
- **Humans approve changes.** Agents read freely but change nothing in
  production without a named approver or a reviewed pull request.
- **Keyless and private.** Entra ID managed identities and workload identity,
  private endpoints, and OIDC from CI instead of stored secrets.
- **Runs without a cloud account.** Every project has an offline mode, so the
  demos, tests and CI work on a laptop.

## Try any project in a minute

```bash
git clone https://github.com/chandrasekhar-genai/agentic-ai && cd agentic-ai

cd aiops-incident-agent && pip install -e ".[dev]" && make demo          # incident investigation
cd ../azure-finops-agent && pip install -e ".[dev]" && finops-agent analyze \
  --costs examples/costs.csv --inventory examples/inventory.csv --tf-dir examples/terraform --out out
cd ../azure-rag-landing-zone && pip install -e ".[dev]" && make eval     # RAG + eval gate
cd ../terraform-pr-review-agent && pip install -e ".[dev]" && tfreview --plan examples/plan.json
```

Each project's README covers its architecture (diagram), design decisions (ADRs)
and how to run it against real Azure resources.

## About me

**Chandrasekhar Venkata Malladi**: DevOps & Solution Architect in Abu Dhabi
with 16 years in cloud, DevOps, SRE and AI platforms (Azure, AWS, Kubernetes,
Terraform, LLMOps). Azure Solutions Architect Expert · Azure Security Engineer ·
AWS Security Specialty · CKA.
[LinkedIn](https://www.linkedin.com/in/chandrasekhar-mallandi-70712b39)

## License

[MIT](LICENSE)
