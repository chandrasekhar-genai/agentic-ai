"""Load cost exports and resource inventory (stdlib only, no pandas)."""

from __future__ import annotations

import csv
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path


@dataclass(frozen=True)
class CostRow:
    day: date
    subscription: str
    resource_group: str
    resource_id: str
    resource_name: str
    service: str
    cost: float
    currency: str


@dataclass
class Resource:
    resource_id: str
    name: str
    type: str
    sku: str
    location: str
    state: str
    avg_cpu: float | None
    max_cpu: float | None
    avg_mem: float | None
    attached: bool | None
    tags: dict[str, str] = field(default_factory=dict)

    @property
    def is_vm(self) -> bool:
        return self.type == "microsoft.compute/virtualmachines"


def _float(v: str) -> float | None:
    v = (v or "").strip()
    return float(v) if v else None


def _bool(v: str) -> bool | None:
    v = (v or "").strip().lower()
    return None if not v else v in {"true", "1", "yes"}


def _tags(v: str) -> dict[str, str]:
    pairs = (p.split("=", 1) for p in (v or "").split(";") if "=" in p)
    return {k.strip().lower(): val.strip() for k, val in pairs}


_COST_ALIASES = {
    "date": ("date", "usagedate"),
    "subscription": ("subscriptionname", "subscriptionid"),
    "resource_group": ("resourcegroup", "resourcegroupname"),
    "resource_id": ("resourceid", "instanceid"),
    "resource_name": ("resourcename",),
    "service": ("metercategory", "servicename"),
    "cost": ("costinbillingcurrency", "cost", "pretaxcost"),
    "currency": ("billingcurrency", "billingcurrencycode", "currency"),
}


def _pick(row: dict[str, str], field_name: str, default: str = "") -> str:
    for alias in _COST_ALIASES[field_name]:
        if row.get(alias):
            return row[alias]
    return default


def _date(v: str) -> date:
    v = v.strip()[:10]
    if "/" in v:  # older export schemas use MM/DD/YYYY
        m, d, y = v.split("/")
        return date(int(y), int(m), int(d))
    return date.fromisoformat(v)


def load_costs(path: str | Path) -> list[CostRow]:
    """Load an Azure Cost Management export (actual or amortized), any schema version.

    Column names are matched case-insensitively against the known aliases above.
    """
    rows = []
    with open(path, newline="", encoding="utf-8-sig") as f:
        for raw in csv.DictReader(f):
            r = {k.strip().lower(): (v or "") for k, v in raw.items() if k}
            rid = _pick(r, "resource_id")
            rows.append(CostRow(
                day=_date(_pick(r, "date")),
                subscription=_pick(r, "subscription"),
                resource_group=_pick(r, "resource_group"),
                resource_id=rid.lower(),
                resource_name=_pick(r, "resource_name") or rid.rsplit("/", 1)[-1],
                service=_pick(r, "service", "Other"),
                cost=float(_pick(r, "cost", "0")),
                currency=_pick(r, "currency", "USD"),
            ))
    return rows


def load_inventory(path: str | Path) -> dict[str, Resource]:
    with open(path, newline="", encoding="utf-8-sig") as f:
        out = {}
        for r in csv.DictReader(f):
            res = Resource(
                resource_id=r["ResourceId"].lower(),
                name=r["Name"],
                type=r["Type"].lower(),
                sku=r.get("Sku", ""),
                location=r.get("Location", ""),
                state=r.get("State", "").lower(),
                avg_cpu=_float(r.get("AvgCpuPct30d", "")),
                max_cpu=_float(r.get("MaxCpuPct30d", "")),
                avg_mem=_float(r.get("AvgMemPct30d", "")),
                attached=_bool(r.get("Attached", "")),
                tags=_tags(r.get("Tags", "")),
            )
            out[res.resource_id] = res
        return out


class CostIndex:
    """Pre-aggregated views over the cost rows."""

    def __init__(self, rows: list[CostRow]) -> None:
        if not rows:
            raise ValueError("cost export is empty")
        self.rows = rows
        self.currency = rows[0].currency
        self.last_day = max(r.day for r in rows)
        self.by_service_day: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
        self.by_resource_day: dict[str, dict[date, float]] = defaultdict(lambda: defaultdict(float))
        self.service_of: dict[str, str] = {}
        for r in rows:
            self.by_service_day[r.service][r.day] += r.cost
            self.by_resource_day[r.resource_id][r.day] += r.cost
            self.service_of[r.resource_id] = r.service

    def last_n_days(self, resource_id: str, n: int = 30) -> float:
        start = self.last_day - timedelta(days=n - 1)
        return sum(c for d, c in self.by_resource_day.get(resource_id.lower(), {}).items() if d >= start)

    def total_last_n_days(self, n: int = 30) -> float:
        start = self.last_day - timedelta(days=n - 1)
        return sum(r.cost for r in self.rows if r.day >= start)

    def service_series(self, service: str) -> list[tuple[date, float]]:
        return sorted(self.by_service_day.get(service, {}).items())
