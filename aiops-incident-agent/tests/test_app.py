import json
from pathlib import Path

from fastapi.testclient import TestClient

from aiops_agent.app import create_app
from aiops_agent.config import Settings

EXAMPLES = Path(__file__).parent.parent / "examples"


def client(**overrides) -> TestClient:
    return TestClient(create_app(Settings(demo_mode=True, llm_provider="offline", **overrides)))


def post_alert(c: TestClient, name: str) -> str:
    r = c.post("/alerts", json=json.loads((EXAMPLES / name).read_text()))
    assert r.status_code == 202
    return r.json()["incidents"][0]


def test_healthz():
    assert client().get("/healthz").json()["status"] == "ok"


def test_alert_to_approved_remediation():
    c = client()
    incident_id = post_alert(c, "alert-latency.json")

    incident = c.get(f"/incidents/{incident_id}").json()
    assert incident["status"] == "awaiting_approval"

    r = c.post(f"/incidents/{incident_id}/actions/0/approve", headers={"X-Approver": "sre@example.com"})
    assert r.status_code == 200
    assert r.json()["status"] == "executed"
    assert c.get(f"/incidents/{incident_id}").json()["status"] == "remediated"

    # approving twice is refused
    again = c.post(f"/incidents/{incident_id}/actions/0/approve", headers={"X-Approver": "sre@example.com"})
    assert again.status_code == 409


def test_recommendations_cannot_be_approved():
    c = client()
    incident_id = post_alert(c, "alert-oom.json")
    assert c.get(f"/incidents/{incident_id}").json()["status"] == "investigated"
    r = c.post(f"/incidents/{incident_id}/actions/0/approve", headers={"X-Approver": "sre@example.com"})
    assert r.status_code == 409


def test_approval_token_is_enforced():
    c = client(approval_token="s3cret")
    incident_id = post_alert(c, "alert-latency.json")
    url = f"/incidents/{incident_id}/actions/0/approve"
    assert c.post(url, headers={"X-Approver": "a"}).status_code == 401
    ok = c.post(url, headers={"X-Approver": "a", "X-Approval-Token": "s3cret"})
    assert ok.status_code == 200


def test_resolved_alerts_are_ignored():
    payload = json.loads((EXAMPLES / "alert-oom.json").read_text())
    payload["alerts"][0]["status"] = "resolved"
    assert client().post("/alerts", json=payload).json() == {"incidents": []}
