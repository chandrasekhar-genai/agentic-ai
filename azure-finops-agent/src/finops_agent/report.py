"""Markdown and JSON report output."""

from __future__ import annotations

import json
from dataclasses import asdict

from .anomalies import Anomaly
from .data import CostIndex
from .rules import Finding


def markdown(index: CostIndex, summary: str, findings: list[Finding], anomalies: list[Anomaly],
             patch_notes: list[str], has_patch: bool) -> str:
    cur = index.currency
    total = sum(f.est_monthly_savings for f in findings)
    spend = index.total_last_n_days(30)
    out = [
        f"# Azure FinOps report – period ending {index.last_day.isoformat()}",
        "",
        f"Last 30 days spend: **{cur} {spend:,.0f}** · Identified savings: **{cur} {total:,.0f}/month** "
        f"({(total / spend * 100) if spend else 0:.0f}% of spend)",
        "",
        summary.strip(),
        "",
        "## Anomalies (last 7 days)",
    ]
    if anomalies:
        out += ["| Day | Service | Actual | Expected | Robust z | Top contributor |", "|---|---|---:|---:|---:|---|"]
        for a in anomalies:
            top = a.top_resources[0][0].rsplit("/", 1)[-1] if a.top_resources else "-"
            out.append(f"| {a.day} | {a.service} | {a.actual:,.2f} | {a.expected:,.2f} | {a.robust_z} | `{top}` |")
    else:
        out.append("None detected.")
    out += ["", "## Findings", "| Resource | Finding | Action | Monthly cost | Est. saving/month | Risk |",
            "|---|---|---|---:|---:|---|"]
    for f in findings:
        out.append(f"| `{f.name}` | {f.kind} | {f.action} | {f.monthly_cost:,.2f} | {f.est_monthly_savings:,.2f} "
                   f"| {f.risk} |")
    out += ["", "## Terraform changes",
            "A patch for the IaC-managed resources is in `finops.patch` (apply with `git apply`, then plan and review)."
            if has_patch else "No Terraform changes generated."]
    if patch_notes:
        out += ["", "Not mapped to Terraform (handle manually or import into IaC):"] + [f"- {n}" for n in patch_notes]
    out += ["", f"_Estimates use each resource's own last-30-day cost in {cur}; validate before acting._", ""]
    return "\n".join(out)


def as_json(index: CostIndex, findings: list[Finding], anomalies: list[Anomaly]) -> str:
    return json.dumps(
        {
            "period_end": index.last_day.isoformat(),
            "currency": index.currency,
            "spend_last_30d": round(index.total_last_n_days(30), 2),
            "est_monthly_savings": round(sum(f.est_monthly_savings for f in findings), 2),
            "findings": [asdict(f) for f in findings],
            "anomalies": [asdict(a) for a in anomalies],
        },
        indent=2,
        default=str,
    )
