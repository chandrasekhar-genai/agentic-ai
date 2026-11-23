# Terraform PR Review Agent

[![ci](https://github.com/chandrasekhar-genai/agentic-ai/actions/workflows/terraform-pr-review-agent.yml/badge.svg)](https://github.com/chandrasekhar-genai/agentic-ai/actions/workflows/terraform-pr-review-agent.yml)
![python](https://img.shields.io/badge/python-3.11%2B-blue)
![license](https://img.shields.io/badge/license-MIT-green)

A GitHub Action that reviews Terraform pull requests the way a platform
architect would. It checks the **planned values** against landing-zone
guardrails, adds **Checkov** and **Infracost** results, and posts one
readable comment with an **AI-written review**: what changes, what is risky,
and what to ask the author.

> The pass/fail decision is deterministic policy. The AI only explains.
> See [ADR 0001](docs/adr/0001-deterministic-gate-ai-narrative.md).

## What it catches

| Rule | Severity | Example |
|---|---|---|
| `destructive-change` | high | replace/delete of a database, storage account, Key Vault, AKS, resource group… |
| `allowed-locations` | high | a resource outside the approved regions (data residency) |
| `public-network-access` | high | `public_network_access_enabled = true` on PaaS data services |
| `nsg-open-admin-port` | high | SSH/RDP open to `*` / `Internet`, including wide port ranges |
| `storage-public-blobs` | high | anonymous blob access |
| `required-tags` | medium | missing `owner`, `env`, `cost-center` |
| `keyvault-purge-protection` | medium | Key Vault without purge protection |
| `aks-local-accounts`, `aks-public-api` | medium | AKS local accounts or an unrestricted public API server |
| `storage-tls`, `storage-shared-key` | medium / low | weak TLS, shared-key auth |

Rules run on `terraform show -json` output, so they see values that come from
variables, modules and data sources, which source-only scanners miss.

## Example comment

From the fixture in [`examples/`](examples) (a PR that upgrades PostgreSQL,
opens SSH, adds a VM in the wrong region and makes a storage account public):

```markdown
## Terraform review
❌ Blocking findings – changes requested

+3 create · ~1 update · ±1 replace · -0 delete · cost +USD 349.16 (2,141 → 2,490)/month

### What this PR changes
- Creates 3 resource(s): azurerm_network_security_rule.ssh, module.batch.azurerm_linux_virtual_machine.worker, …
- Replaces 1 resource(s): azurerm_postgresql_flexible_server.orders
### Risks
- azurerm_postgresql_flexible_server.orders: replace of a stateful resource (replace because cannot update) …
- azurerm_network_security_rule.ssh: rule allow-ssh allows SSH/RDP from the internet; use Bastion or JIT access
### Questions for the author
- Is the replacement of the stateful resource intended, and is a tested backup/restore or migration plan in place?
- Monthly cost increases by USD 349.16; is this budgeted?

▸ Policy findings (8)   ▸ Checkov (3 failed checks)   ▸ Cost by resource (Infracost)
```

With `llm: azure` the narrative is written by Azure OpenAI from the same
context, including the attribute diffs (here, the PostgreSQL `version` 15 → 16
change that forces the replace). Without a model, a deterministic template
writes it.

## Use it

```yaml
- uses: chandrasekhar-genai/agentic-ai/terraform-pr-review-agent@main
  with:
    plan-json: plan.json            # terraform show -json tfplan > plan.json
    checkov-json: checkov.json      # optional
    infracost-json: infracost.json  # optional
    llm: azure                      # or offline
    fail-on: high                   # high | medium | low | never
```

A complete workflow (OIDC login, plan, Checkov, Infracost, review) is in
[`examples/workflow.yml`](examples/workflow.yml). Configure your rules in
`.tfreview.toml` ([example](.tfreview.toml.example)): approved regions,
required tags, failure level and reviewed exceptions.

Run locally:

```bash
pip install -e ".[dev]"
tfreview --plan examples/plan.json --checkov examples/checkov.json --infracost examples/infracost.json
```

## Design

- Deterministic policy decides; the model only writes the narrative and has no tools.
- Plan content is treated as untrusted data in the prompt (prompt-injection aware).
- Model outage → the comment is still posted with full policy results.
- One comment per PR, updated in place on every push.
- Azure OpenAI auth via Entra ID (`azure/login` OIDC), no API key needed.

## Roadmap

- OPA/Rego rule pack as an alternative to the Python rules
- AWS and GCP rule sets
- Suggested fixes as GitHub review suggestions on the changed lines

## License

MIT – see the [repository license](../LICENSE).
