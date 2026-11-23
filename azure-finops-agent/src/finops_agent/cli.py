"""finops-agent analyze --costs costs.csv --inventory inventory.csv [--tf-dir infra/] --out out/"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import anomalies as anomaly_mod
from .agent import AzureOpenAILLM, FinOpsAgent, OfflineLLM
from .data import CostIndex, load_costs, load_inventory
from .report import as_json, markdown
from .rules import evaluate
from .terraform import build_patch


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="finops-agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("analyze", help="analyse a cost export and inventory")
    a.add_argument("--costs", required=True)
    a.add_argument("--inventory", required=True)
    a.add_argument("--tf-dir", help="Terraform directory to generate a patch against")
    a.add_argument("--out", default="out")
    a.add_argument("--llm", choices=["offline", "azure"], default=os.getenv("LLM_PROVIDER", "offline"))
    a.add_argument("--fail-on-anomaly", action="store_true", help="exit 2 if anomalies are found (for CI)")
    args = p.parse_args(argv)

    index = CostIndex(load_costs(args.costs))
    inventory = load_inventory(args.inventory)
    findings = evaluate(inventory, index)
    anomalies = anomaly_mod.detect(index)

    patch, notes = ("", [])
    if args.tf_dir:
        patch, notes = build_patch(findings, args.tf_dir)

    llm = AzureOpenAILLM() if args.llm == "azure" else OfflineLLM()
    summary = FinOpsAgent(llm, index, findings, anomalies).summarise()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(markdown(index, summary, findings, anomalies, notes, bool(patch)), encoding="utf-8")
    (out / "report.json").write_text(as_json(index, findings, anomalies), encoding="utf-8")
    if patch:
        (out / "finops.patch").write_text(patch, encoding="utf-8")

    total = sum(f.est_monthly_savings for f in findings)
    print(f"{len(findings)} findings, {len(anomalies)} anomalies, "
          f"~{index.currency} {total:,.0f}/month savings -> {out}/report.md")
    return 2 if (args.fail_on_anomaly and anomalies) else 0


if __name__ == "__main__":
    sys.exit(main())
