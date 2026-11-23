"""Generate the synthetic sample data in examples/ (deterministic, seed 42).

Shapes follow an Azure Cost Management "Actual cost" daily export and an
inventory built from Azure Resource Graph + Azure Monitor (see kql/).
Prices are illustrative, not quotes.

    python examples/generate_sample.py
"""

from __future__ import annotations

import csv
import random
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).parent
END = date(2026, 11, 20)
DAYS = 60
SUB = "sub-platform-prod"
BASE = "/subscriptions/00000000-0000-0000-0000-000000000000/resourceGroups/{rg}/providers/{rp}/{name}"

# name, rg, provider path, service (MeterCategory), daily cost, sku, state, avgcpu, maxcpu, avgmem, attached, tags
RESOURCES = [
    ("vm-app-prod-01", "rg-app-prod", "Microsoft.Compute/virtualMachines", "Virtual Machines", 18.4,
     "Standard_D16s_v5", "running", 9.1, 31.0, 28.0, "", "env=prod;owner=app-team"),
    ("vm-app-prod-02", "rg-app-prod", "Microsoft.Compute/virtualMachines", "Virtual Machines", 9.2,
     "Standard_D8s_v5", "running", 55.3, 88.0, 61.0, "", "env=prod;owner=app-team"),
    ("vm-build-dev-01", "rg-build-dev", "Microsoft.Compute/virtualMachines", "Virtual Machines", 4.6,
     "Standard_D4s_v5", "running", 12.4, 70.2, 35.0, "", "env=dev;owner=platform"),
    ("vm-legacy-test", "rg-legacy-test", "Microsoft.Compute/virtualMachines", "Virtual Machines", 2.3,
     "Standard_D2s_v5", "running", 1.2, 3.1, 9.0, "", "env=test;owner=unknown"),
    ("vm-batch-old", "rg-batch", "Microsoft.Compute/virtualMachines", "Virtual Machines", 12.1,
     "Standard_E8s_v5", "stopped", 0.0, 0.0, 0.0, "", "env=prod;owner=data"),
    ("disk-orphan-01", "rg-app-prod", "Microsoft.Compute/disks", "Storage", 4.5,
     "Premium_LRS P30", "unattached", "", "", "", "false", "env=prod"),
    ("pip-unused-01", "rg-network", "Microsoft.Network/publicIPAddresses", "Virtual Network", 0.12,
     "Standard", "unassociated", "", "", "", "false", "env=prod"),
    ("aks-prod-nodepool", "rg-aks-prod", "Microsoft.Compute/virtualMachineScaleSets", "Virtual Machines", 55.0,
     "Standard_D8s_v5", "running", 48.0, 81.0, 66.0, "", "env=prod;owner=platform"),
    ("law-platform-prod", "rg-observability", "Microsoft.OperationalInsights/workspaces", "Log Analytics", 40.0,
     "PerGB2018", "running", "", "", "", "", "env=prod;owner=platform"),
    ("stplatformlogs", "rg-observability", "Microsoft.Storage/storageAccounts", "Storage", 6.0,
     "Standard_GRS", "running", "", "", "", "", "env=prod;owner=platform"),
]


def main() -> None:
    rng = random.Random(42)
    start = END - timedelta(days=DAYS - 1)
    with open(HERE / "costs.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["Date", "SubscriptionName", "ResourceGroup", "ResourceId", "ResourceName",
                    "MeterCategory", "CostInBillingCurrency", "BillingCurrency"])
        for i in range(DAYS):
            day = start + timedelta(days=i)
            for name, rg, rp, svc, daily, *_ in RESOURCES:
                cost = daily * rng.uniform(0.94, 1.06)
                # Debug logging left on after a release: Log Analytics ingestion x4 for the last 3 days
                if name == "law-platform-prod" and day > END - timedelta(days=3):
                    cost = daily * rng.uniform(3.8, 4.2)
                w.writerow([day.isoformat(), SUB, rg, BASE.format(rg=rg, rp=rp, name=name), name,
                            svc, f"{cost:.4f}", "USD"])

    with open(HERE / "inventory.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["ResourceId", "Name", "Type", "Sku", "Location", "State",
                    "AvgCpuPct30d", "MaxCpuPct30d", "AvgMemPct30d", "Attached", "Tags"])
        for name, rg, rp, _svc, _daily, sku, state, avg, mx, mem, attached, tags in RESOURCES:
            w.writerow([BASE.format(rg=rg, rp=rp, name=name), name, rp.lower(), sku, "uaenorth", state,
                        avg, mx, mem, attached, tags])


if __name__ == "__main__":
    main()
