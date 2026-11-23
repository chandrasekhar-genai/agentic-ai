from datetime import date, timedelta
from pathlib import Path

import pytest

from finops_agent import anomalies
from finops_agent.agent import FinOpsAgent, OfflineLLM
from finops_agent.cli import main
from finops_agent.data import CostIndex, CostRow, Resource, load_costs, load_inventory
from finops_agent.rules import evaluate, smaller_size
from finops_agent.terraform import build_patch

EX = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def sample():
    index = CostIndex(load_costs(EX / "costs.csv"))
    inventory = load_inventory(EX / "inventory.csv")
    return index, inventory, evaluate(inventory, index), anomalies.detect(index)


def test_expected_findings_on_sample(sample):
    _, _, findings, _ = sample
    kinds = {f.name: f.kind for f in findings}
    assert kinds == {
        "vm-batch-old": "stopped_not_deallocated",
        "vm-app-prod-01": "rightsize_vm",
        "disk-orphan-01": "orphaned_disk",
        "vm-build-dev-01": "nonprod_schedule",
        "vm-legacy-test": "idle_vm",
        "pip-unused-01": "orphaned_public_ip",
    }
    # busy VMs and the AKS node pool are left alone
    assert "vm-app-prod-02" not in kinds and "aks-prod-nodepool" not in kinds


def test_log_analytics_spike_is_the_only_anomaly(sample):
    _, _, _, found = sample
    assert {a.service for a in found} == {"Log Analytics"}
    assert len(found) == 3
    assert found[0].top_resources[0][0].endswith("law-platform-prod")


def test_no_anomaly_on_flat_series():
    start = date(2026, 1, 1)
    rows = [CostRow(start + timedelta(days=i), "s", "rg", "/x/vm", "vm", "Virtual Machines", 100.0, "USD")
            for i in range(30)]
    assert anomalies.detect(CostIndex(rows)) == []


@pytest.mark.parametrize("sku,expected", [
    ("Standard_D16s_v5", "Standard_D8s_v5"),
    ("Standard_E8ads_v5", "Standard_E4ads_v5"),
    ("Standard_D2s_v5", None),        # already minimum for the rule
    ("Standard_B2ms", None),          # not a versioned series, skip
])
def test_smaller_size(sku, expected):
    assert smaller_size(sku) == expected


def test_memory_bound_vm_is_not_rightsized():
    index = CostIndex([CostRow(date(2026, 1, 1), "s", "rg", "/x/vm1", "vm1", "Virtual Machines", 10.0, "USD")])
    vm = Resource("/x/vm1", "vm1", "microsoft.compute/virtualmachines", "Standard_D16s_v5", "uaenorth",
                  "running", 8.0, 20.0, 85.0, None, {"env": "prod"})
    assert evaluate({"/x/vm1": vm}, index) == []


def test_terraform_patch_resizes_and_schedules(sample):
    _, _, findings, _ = sample
    patch, notes = build_patch(findings, EX / "terraform")
    assert '-  size                  = "Standard_D16s_v5"' in patch
    assert '+  size                  = "Standard_D8s_v5"' in patch
    assert "azurerm_dev_test_global_vm_shutdown_schedule" in patch
    assert not any("vm-app-prod-01" in n for n in notes)


def test_offline_agent_summary_uses_engine_numbers(sample):
    index, _, findings, found = sample
    text = FinOpsAgent(OfflineLLM(), index, findings, found).summarise()
    total = sum(f.est_monthly_savings for f in findings)
    assert f"USD {total:,.0f}/month" in text
    assert "Log Analytics" in text and "## Quick wins" in text


def test_cli_writes_outputs_and_fails_on_anomaly(tmp_path):
    code = main(["analyze", "--costs", str(EX / "costs.csv"), "--inventory", str(EX / "inventory.csv"),
                 "--tf-dir", str(EX / "terraform"), "--out", str(tmp_path), "--fail-on-anomaly"])
    assert code == 2
    assert {p.name for p in tmp_path.iterdir()} == {"report.md", "report.json", "finops.patch"}


def test_loader_accepts_newer_export_schema(tmp_path):
    csv_path = tmp_path / "export.csv"
    csv_path.write_text(
        "date,subscriptionName,resourceGroupName,ResourceId,meterCategory,costInBillingCurrency,billingCurrency\n"
        "11/20/2026,sub,rg,/SUBSCRIPTIONS/X/vm1,Virtual Machines,12.5,AED\n",
        encoding="utf-8",
    )
    (row,) = load_costs(csv_path)
    assert row.day == date(2026, 11, 20) and row.currency == "AED" and row.cost == 12.5
    assert row.resource_id == "/subscriptions/x/vm1" and row.resource_group == "rg"
