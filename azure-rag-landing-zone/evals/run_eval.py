"""LLMOps evaluation gate.

Runs the golden set against the RAG pipeline (in-process) or a deployed API and
fails (exit 1) if any metric falls below evals/thresholds.json.

    python evals/run_eval.py                          # in-process, RAG_MODE from env (local by default)
    python evals/run_eval.py --api-url https://<app>   # deployed staging API
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "app"))

REFUSAL_MARKER = "i don't know"


def load_golden(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def ask_inprocess():
    from rag.pipeline import build_pipeline

    pipeline = build_pipeline()

    def ask(q: str) -> dict:
        a = pipeline.answer(q)
        return {"answer": a.answer, "retrieved": a.retrieved, "citations": [c.__dict__ for c in a.citations],
                "latency_ms": a.latency_ms}
    return ask


def ask_api(base_url: str):
    import httpx

    client = httpx.Client(base_url=base_url.rstrip("/"), timeout=60)

    def ask(q: str) -> dict:
        start = time.perf_counter()
        r = client.post("/chat", json={"question": q})
        r.raise_for_status()
        data = r.json()
        data["latency_ms"] = int((time.perf_counter() - start) * 1000)
        return data
    return ask


def p95(values: list[int]) -> int:
    if not values:
        return 0
    ordered = sorted(values)
    return ordered[max(0, math.ceil(0.95 * len(ordered)) - 1)]


def evaluate(golden: list[dict], ask) -> tuple[dict, list[dict]]:
    rows = []
    for item in golden:
        res = ask(item["question"])
        answer = res["answer"].lower()
        in_scope = item["expected_source"] is not None
        cited_sources = {c["source"] for c in res.get("citations", [])}
        rows.append({
            "id": item["id"],
            "in_scope": in_scope,
            "retrieval_hit": in_scope and item["expected_source"] in res.get("retrieved", []),
            "answer_ok": in_scope and all(m.lower() in answer for m in item["must_include"]),
            "cited_expected": in_scope and item["expected_source"] in cited_sources,
            "refused": REFUSAL_MARKER in answer,
            "latency_ms": res["latency_ms"],
            "answer": res["answer"],
        })
    scoped = [r for r in rows if r["in_scope"]]
    oos = [r for r in rows if not r["in_scope"]]

    def rate(items: list[dict], key: str) -> float:
        return round(sum(r[key] for r in items) / len(items), 3) if items else 1.0

    metrics = {
        "retrieval_hit_rate": rate(scoped, "retrieval_hit"),
        "answer_recall": rate(scoped, "answer_ok"),
        "citation_rate": rate(scoped, "cited_expected"),
        "refusal_accuracy": rate(oos, "refused"),
        "p95_latency_ms": p95([r["latency_ms"] for r in rows]),
    }
    return metrics, rows


def check(metrics: dict, thresholds: dict) -> list[str]:
    failures = []
    for name, limit in thresholds.items():
        value = metrics[name]
        ok = value <= limit if name.endswith("_ms") else value >= limit
        if not ok:
            failures.append(f"{name}={value} (threshold {limit})")
    return failures


def markdown(metrics: dict, thresholds: dict, rows: list[dict], failures: list[str]) -> str:
    lines = ["## RAG evaluation", "", "| Metric | Value | Threshold |", "|---|---:|---:|"]
    for k, v in metrics.items():
        lines.append(f"| {k} | {v} | {thresholds.get(k, '-')} |")
    lines += ["", "**Result:** " + ("✅ passed" if not failures else "❌ failed: " + "; ".join(failures)), ""]
    misses = [r for r in rows if (r["in_scope"] and not (r["answer_ok"] and r["retrieval_hit"]))
              or (not r["in_scope"] and not r["refused"])]
    if misses:
        lines += ["<details><summary>Misses</summary>", ""]
        lines += [f"- `{r['id']}`: {r['answer'][:200]}" for r in misses]
        lines += ["", "</details>"]
    return "\n".join(lines) + "\n"


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--api-url")
    p.add_argument("--golden", default=str(HERE / "golden.jsonl"))
    p.add_argument("--thresholds", default=str(HERE / "thresholds.json"))
    p.add_argument("--out", default="eval-results.json")
    args = p.parse_args()

    thresholds = json.loads(Path(args.thresholds).read_text(encoding="utf-8"))
    ask = ask_api(args.api_url) if args.api_url else ask_inprocess()
    metrics, rows = evaluate(load_golden(Path(args.golden)), ask)
    failures = check(metrics, thresholds)

    Path(args.out).write_text(json.dumps({"metrics": metrics, "rows": rows}, indent=2), encoding="utf-8")
    report = markdown(metrics, thresholds, rows, failures)
    print(report)
    if summary := os.getenv("GITHUB_STEP_SUMMARY"):
        with open(summary, "a", encoding="utf-8") as f:
            f.write(report)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
