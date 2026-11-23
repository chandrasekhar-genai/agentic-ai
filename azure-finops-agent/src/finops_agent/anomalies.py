"""Daily cost anomaly detection per service using a robust (median/MAD) z-score.

Median and MAD are used instead of mean/stddev so that one previous spike does
not inflate the baseline and hide the next one.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from datetime import date, timedelta

from .data import CostIndex


@dataclass
class Anomaly:
    service: str
    day: date
    actual: float
    expected: float
    robust_z: float
    top_resources: list[tuple[str, float]] = field(default_factory=list)  # (resource_id, delta)

    @property
    def excess(self) -> float:
        return self.actual - self.expected


def detect(
    index: CostIndex,
    baseline_days: int = 14,
    lookback_days: int = 7,
    z_threshold: float = 3.5,
    min_excess: float = 20.0,
) -> list[Anomaly]:
    found: list[Anomaly] = []
    first_checked = index.last_day - timedelta(days=lookback_days - 1)
    for service, by_day in index.by_service_day.items():
        for day in sorted(d for d in by_day if d >= first_checked):
            window = [by_day.get(day - timedelta(days=k), 0.0) for k in range(1, baseline_days + 1)]
            med = statistics.median(window)
            mad = statistics.median(abs(x - med) for x in window) or max(med * 0.01, 1e-9)
            z = 0.6745 * (by_day[day] - med) / mad
            if z >= z_threshold and by_day[day] - med >= min_excess:
                found.append(Anomaly(service, day, by_day[day], med, round(z, 1),
                                     _contributors(index, service, day, baseline_days)))
    return sorted(found, key=lambda a: (a.day, -a.excess))


def _contributors(index: CostIndex, service: str, day: date, baseline_days: int) -> list[tuple[str, float]]:
    deltas = []
    for rid, by_day in index.by_resource_day.items():
        if index.service_of.get(rid) != service:
            continue
        base = statistics.median(by_day.get(day - timedelta(days=k), 0.0) for k in range(1, baseline_days + 1))
        deltas.append((rid, by_day.get(day, 0.0) - base))
    return sorted((d for d in deltas if d[1] > 0), key=lambda d: -d[1])[:3]
