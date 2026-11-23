"""Optimisation rules: orphaned resources, idle and oversized VMs, non-prod schedules.

Savings are estimates from the resource's own last-30-day cost, so they are in
the billing currency and need no price list. Thresholds are deliberately
conservative and configurable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from .data import CostIndex, Resource


@dataclass
class Thresholds:
    idle_avg_cpu: float = 5.0
    idle_max_cpu: float = 15.0
    rightsize_avg_cpu: float = 20.0
    rightsize_max_cpu: float = 35.0   # peak on half the vCPUs stays <= ~70%
    rightsize_max_mem: float = 50.0
    nonprod_envs: tuple[str, ...] = ("dev", "test", "qa", "sandbox")
    # weekdays 08:00-20:00 = 60 of 168 hours running
    schedule_runtime_fraction: float = 60 / 168


@dataclass
class Finding:
    kind: str
    resource_id: str
    name: str
    monthly_cost: float
    est_monthly_savings: float
    action: str
    detail: str
    risk: str = "low"
    change: dict[str, Any] = field(default_factory=dict)


# Halving vCPUs inside the same VM series roughly halves the compute rate.
_SIZE = re.compile(r"^(Standard_[A-Z]+)(\d+)([a-z]*_v\d+)$")


def smaller_size(sku: str) -> str | None:
    m = _SIZE.match(sku)
    if not m:
        return None
    vcpus = int(m.group(2))
    return f"{m.group(1)}{vcpus // 2}{m.group(3)}" if vcpus >= 4 else None


def evaluate(inventory: dict[str, Resource], costs: CostIndex, t: Thresholds | None = None) -> list[Finding]:
    t = t or Thresholds()
    findings: list[Finding] = []
    for res in inventory.values():
        monthly = costs.last_n_days(res.resource_id, 30)
        if monthly <= 0:
            continue
        f = _check(res, monthly, t)
        if f:
            findings.append(f)
    return sorted(findings, key=lambda f: -f.est_monthly_savings)


def _check(res: Resource, monthly: float, t: Thresholds) -> Finding | None:
    base = {"resource_id": res.resource_id, "name": res.name, "monthly_cost": monthly}

    if res.type == "microsoft.compute/disks" and res.attached is False:
        return Finding(kind="orphaned_disk", est_monthly_savings=monthly, risk="medium",
                       action="Snapshot, then delete the unattached disk",
                       detail=f"{res.sku} disk is not attached to any VM.",
                       change={"type": "delete"}, **base)

    if res.type == "microsoft.network/publicipaddresses" and res.attached is False:
        return Finding(kind="orphaned_public_ip", est_monthly_savings=monthly,
                       action="Release the unassociated public IP",
                       detail="Static public IP is not associated with any NIC, load balancer or gateway.",
                       change={"type": "delete"}, **base)

    if not res.is_vm:
        return None

    if res.state == "stopped":
        return Finding(kind="stopped_not_deallocated", est_monthly_savings=monthly,
                       action="Deallocate the VM (or delete it if unused)",
                       detail="VM is stopped from inside the OS but not deallocated, so compute is still billed.",
                       change={"type": "deallocate"}, **base)

    if res.avg_cpu is None or res.max_cpu is None:
        return None

    if res.avg_cpu < t.idle_avg_cpu and res.max_cpu < t.idle_max_cpu:
        return Finding(kind="idle_vm", est_monthly_savings=monthly, risk="medium",
                       action="Confirm with the owner, then deallocate or delete",
                       detail=f"30-day CPU avg {res.avg_cpu}% / max {res.max_cpu}%. "
                              f"Owner tag: {res.tags.get('owner', 'none')}.",
                       change={"type": "deallocate"}, **base)

    if res.tags.get("env") in t.nonprod_envs and res.state == "running":
        saving = monthly * (1 - t.schedule_runtime_fraction)
        return Finding(kind="nonprod_schedule", est_monthly_savings=saving,
                       action="Nightly auto-shutdown at 20:00, start on demand",
                       detail=f"env={res.tags['env']} VM runs 24x7. With nightly shutdown and a weekday start "
                              "(on demand or Start/Stop VMs v2) runtime drops to ~60 of 168 hours.",
                       change={"type": "schedule", "stop": "2000", "timezone": "Arabian Standard Time"}, **base)

    target = smaller_size(res.sku)
    mem_ok = res.avg_mem is None or res.avg_mem < t.rightsize_max_mem
    if target and res.avg_cpu < t.rightsize_avg_cpu and res.max_cpu < t.rightsize_max_cpu and mem_ok:
        mem = (f"memory avg {res.avg_mem}%" if res.avg_mem is not None
               else "memory not measured – check VM insights before resizing")
        return Finding(kind="rightsize_vm", est_monthly_savings=monthly * 0.5,
                       action=f"Resize {res.sku} -> {target}",
                       detail=f"30-day CPU avg {res.avg_cpu}% / max {res.max_cpu}%, {mem}; "
                              f"projected peak on half the vCPUs ~{res.max_cpu * 2:.0f}%.",
                       risk="medium",
                       change={"type": "resize", "from": res.sku, "to": target}, **base)
    return None
