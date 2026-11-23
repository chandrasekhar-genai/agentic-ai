"""Readers for Checkov and Infracost JSON output (both optional)."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CheckovResult:
    check_id: str
    name: str
    resource: str
    file: str


def load_checkov(path: str | Path | None) -> list[CheckovResult]:
    if not path or not Path(path).exists():
        return []
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    reports = data if isinstance(data, list) else [data]
    out = []
    for rep in reports:
        for r in (rep.get("results") or {}).get("failed_checks", []):
            out.append(CheckovResult(r["check_id"], r.get("check_name", ""), r.get("resource", ""),
                                     r.get("file_path", "")))
    return out


@dataclass
class CostDiff:
    currency: str
    before: float
    after: float
    diff: float
    top: list[tuple[str, float]] = field(default_factory=list)


def _f(v: object) -> float:
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return 0.0


def load_infracost(path: str | Path | None) -> CostDiff | None:
    if not path or not Path(path).exists():
        return None
    d = json.loads(Path(path).read_text(encoding="utf-8"))
    top: list[tuple[str, float]] = []
    for p in d.get("projects", []):
        for r in (p.get("diff") or {}).get("resources", []):
            top.append((r["name"], _f(r.get("monthlyCost"))))
    top.sort(key=lambda t: -abs(t[1]))
    return CostDiff(d.get("currency", "USD"), _f(d.get("pastTotalMonthlyCost")), _f(d.get("totalMonthlyCost")),
                    _f(d.get("diffTotalMonthlyCost")), top[:5])
