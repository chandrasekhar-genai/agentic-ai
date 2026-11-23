import json
from pathlib import Path

import httpx
import pytest

from tfreview import comment, guardrails
from tfreview.cli import main
from tfreview.plan import load_plan
from tfreview.reviewer import changed_attributes
from tfreview.scanners import load_checkov, load_infracost

EX = Path(__file__).parent.parent / "examples"


@pytest.fixture(scope="module")
def plan():
    return load_plan(EX / "plan.json")


def rules(findings):
    return {(f.rule, f.address) for f in findings}


def test_plan_counts_ignore_noop(plan):
    assert plan.counts() == {"create": 3, "update": 1, "replace": 1, "delete": 0}
    assert all(c.kind != "no-op" for c in plan.effective)


def test_guardrails_on_fixture(plan):
    found = rules(guardrails.evaluate(plan, guardrails.Config()))
    assert ("destructive-change", "azurerm_postgresql_flexible_server.orders") in found
    assert ("public-network-access", "azurerm_storage_account.exports") in found
    assert ("nsg-open-admin-port", "azurerm_network_security_rule.ssh") in found
    assert ("allowed-locations", "module.batch.azurerm_linux_virtual_machine.worker") in found
    assert ("keyvault-purge-protection", "azurerm_key_vault.batch") in found
    # resource group is a no-op and fully tagged: nothing reported
    assert not any(addr == "azurerm_resource_group.app" for _, addr in found)


def test_config_from_toml_and_ignores(tmp_path, plan):
    cfg_file = tmp_path / ".tfreview.toml"
    cfg_file.write_text(
        '[tfreview]\nallowed_locations = ["uaenorth", "westeurope"]\nrequired_tags = ["owner"]\n'
        'ignore = ["nsg-open-admin-port:azurerm_network_security_rule.ssh"]\n', encoding="utf-8")
    found = rules(guardrails.evaluate(plan, guardrails.Config.load(cfg_file)))
    assert not any(r == "allowed-locations" for r, _ in found)
    assert not any(r == "required-tags" for r, _ in found)
    assert ("nsg-open-admin-port", "azurerm_network_security_rule.ssh") not in found


def test_blocking_levels(plan):
    findings = guardrails.evaluate(plan, guardrails.Config())
    assert len(guardrails.blocking(findings, "high")) == 4
    assert len(guardrails.blocking(findings, "low")) == len(findings)
    assert guardrails.blocking(findings, "never") == []


def test_nsg_rule_from_trusted_range_is_fine():
    rule = {"direction": "Inbound", "access": "Allow", "destination_port_range": "22",
            "source_address_prefix": "10.0.0.0/8"}
    assert guardrails._open_admin(rule) is False
    assert guardrails._open_admin({**rule, "source_address_prefix": "Internet"}) is True
    wide = {**rule, "source_address_prefix": "*", "destination_port_range": "0-65535"}
    assert guardrails._open_admin(wide) is True
    assert guardrails._open_admin({**wide, "destination_port_range": "443"}) is False


def test_changed_attributes_for_replace(plan):
    pg = next(c for c in plan.changes if c.address.endswith("orders"))
    diff = changed_attributes(pg)
    assert diff["version"] == {"from": "15", "to": "16"}
    assert diff["zone"] == {"from": "1", "to": "2"}


def test_scanners():
    assert len(load_checkov(EX / "checkov.json")) == 3
    cost = load_infracost(EX / "infracost.json")
    assert cost.diff == pytest.approx(349.16) and cost.top[0][0].endswith("worker")
    assert load_checkov(None) == [] and load_infracost("missing.json") is None


def test_cli_fails_on_high_and_passes_with_never(tmp_path):
    args = ["--plan", str(EX / "plan.json"), "--checkov", str(EX / "checkov.json"),
            "--infracost", str(EX / "infracost.json"), "--config", str(tmp_path / "none.toml")]
    assert main(args + ["--out", str(tmp_path / "a.md")]) == 1
    body = (tmp_path / "a.md").read_text(encoding="utf-8")
    assert comment.MARKER in body and "Blocking findings" in body and "+USD 349.16" in body
    assert main(args + ["--fail-on", "never", "--out", str(tmp_path / "b.md")]) == 0


def test_model_failure_still_produces_comment(tmp_path, monkeypatch):
    class Broken:
        def complete(self, system, user):
            raise TimeoutError("model down")

    monkeypatch.setattr("tfreview.cli.OfflineReviewer", Broken)
    main(["--plan", str(EX / "plan.json"), "--fail-on", "never", "--out", str(tmp_path / "c.md"),
          "--config", str(tmp_path / "none.toml")])
    body = (tmp_path / "c.md").read_text(encoding="utf-8")
    assert "AI review unavailable" in body and "Policy findings" in body


def test_upsert_updates_existing_comment():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append((request.method, request.url.path))
        if request.method == "GET":
            return httpx.Response(200, json=[{"id": 7, "body": "hello"}, {"id": 9, "body": f"{comment.MARKER} old"}])
        return httpx.Response(200, json={})

    transport = httpx.MockTransport(handler)
    original = httpx.Client.__init__

    def patched(self, *a, **kw):
        kw["transport"] = transport
        original(self, *a, **kw)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(httpx.Client, "__init__", patched)
        assert comment.upsert("new body", "org/repo", 12, "t", api="https://api.github.test") == "updated"
    assert ("PATCH", "/repos/org/repo/issues/comments/9") in calls


def test_pr_number_from_event(tmp_path, monkeypatch):
    event = tmp_path / "event.json"
    event.write_text(json.dumps({"pull_request": {"number": 42}}), encoding="utf-8")
    monkeypatch.setenv("GITHUB_EVENT_PATH", str(event))
    assert comment.pr_number() == 42
