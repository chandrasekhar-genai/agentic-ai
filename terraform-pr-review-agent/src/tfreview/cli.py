"""tfreview --plan plan.json [--checkov checkov.json] [--infracost infracost.json] [--post]"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import comment, guardrails
from .plan import load_plan
from .reviewer import SYSTEM_PROMPT, AzureOpenAIReviewer, OfflineReviewer, build_context
from .scanners import load_checkov, load_infracost


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="tfreview")
    p.add_argument("--plan", required=True, help="output of `terraform show -json tfplan`")
    p.add_argument("--checkov", help="checkov -o json output")
    p.add_argument("--infracost", help="infracost diff --format json output")
    p.add_argument("--config", default=".tfreview.toml")
    p.add_argument("--fail-on", choices=["high", "medium", "low", "never"])
    p.add_argument("--llm", choices=["offline", "azure"], default=os.getenv("TFREVIEW_LLM", "offline"))
    p.add_argument("--out", default="tfreview.md")
    p.add_argument("--post", action="store_true", help="create/update the PR comment (needs GITHUB_TOKEN)")
    args = p.parse_args(argv)

    cfg = guardrails.Config.load(args.config)
    fail_on = args.fail_on or cfg.fail_on
    plan = load_plan(args.plan)
    findings = guardrails.evaluate(plan, cfg)
    blocking = guardrails.blocking(findings, fail_on)
    checkov = load_checkov(args.checkov)
    cost = load_infracost(args.infracost)

    llm = AzureOpenAIReviewer() if args.llm == "azure" else OfflineReviewer()
    try:
        review = llm.complete(SYSTEM_PROMPT, build_context(plan, findings, checkov, cost))
    except Exception as exc:  # a model outage must not hide the deterministic results
        review = f"_AI review unavailable ({type(exc).__name__}); policy results below are complete._"

    body = comment.render(plan, findings, blocking, checkov, cost, review)
    Path(args.out).write_text(body, encoding="utf-8")
    if summary := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(body)

    if args.post:
        repo, number, token = os.getenv("GITHUB_REPOSITORY"), comment.pr_number(), os.getenv("GITHUB_TOKEN")
        if repo and number and token:
            print(f"PR comment {comment.upsert(body, repo, number, token)}")
        else:
            print("not a pull_request event or GITHUB_TOKEN missing; comment written to", args.out)

    print(f"{len(findings)} findings ({len(blocking)} blocking at '{fail_on}'), {len(checkov)} checkov failures")
    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
