import json
from pathlib import Path

from aiops_agent.agent import IncidentAgent, _extract_json
from aiops_agent.backends import DemoClusterBackend, DemoMetricsBackend
from aiops_agent.config import Settings
from aiops_agent.llm import LLMResponse, OfflineLLM, ToolCall
from aiops_agent.models import ActionStatus, AlertmanagerWebhook
from aiops_agent.remediation import execute, validate_action
from aiops_agent.tools import ToolBox, redact

EXAMPLES = Path(__file__).parent.parent / "examples"


def load_alert(name: str):
    return AlertmanagerWebhook.model_validate(json.loads((EXAMPLES / name).read_text())).alerts[0]


def run(scenario: str, alert_file: str, settings: Settings | None = None):
    settings = settings or Settings()
    tools = ToolBox(DemoClusterBackend(scenario), DemoMetricsBackend(scenario))
    return IncidentAgent(OfflineLLM(), tools, settings).investigate(load_alert(alert_file))


def test_oom_is_diagnosed_and_only_recommendations_are_made():
    inv = run("oom", "alert-oom.json")
    assert inv.confidence == "high"
    assert "512Mi" in inv.root_cause
    assert {e.tool for e in inv.evidence} >= {"get_pod_status", "get_pod_logs", "query_prometheus"}
    assert inv.actions and all(a.status == ActionStatus.RECOMMENDATION for a in inv.actions)


def test_saturation_proposes_bounded_scale_up():
    inv = run("saturation", "alert-latency.json")
    scale = next(a for a in inv.actions if a.action == "scale_deployment")
    assert scale.status == ActionStatus.PROPOSED
    assert scale.params["replicas"] == 5


def test_scale_beyond_limit_is_downgraded_to_recommendation():
    action = validate_action(
        {"action": "scale_deployment", "target": "deployment/x", "params": {"replicas": 50}},
        "payments",
        Settings(max_scale_replicas=10),
    )
    assert action.status == ActionStatus.RECOMMENDATION


def test_namespace_allowlist_is_enforced():
    action = validate_action(
        {"action": "rollout_restart", "target": "deployment/x"}, "kube-system", Settings(allowed_namespaces=("shop",))
    )
    assert action.status == ActionStatus.RECOMMENDATION
    assert "ALLOWED_NAMESPACES" in action.result


def test_execute_requires_proposed_state_and_records_approver():
    cluster = DemoClusterBackend("saturation")
    action = validate_action(
        {"action": "scale_deployment", "target": "deployment/payments-api", "params": {"replicas": 5}},
        "payments",
        Settings(),
    )
    execute(action, cluster, "payments", "oncall@example.com")
    assert action.status == ActionStatus.EXECUTED
    assert action.approved_by == "oncall@example.com"
    assert cluster.actions == ["[demo] scaled deployment/payments-api in payments to 5"]


def test_step_limit_stops_a_looping_model():
    class LoopingLLM:
        def chat(self, messages, tools):
            return LLMResponse(tool_calls=[ToolCall("x", "get_recent_events", {"namespace": "shop"})])

    tools = ToolBox(DemoClusterBackend("oom"), DemoMetricsBackend("oom"))
    inv = IncidentAgent(LoopingLLM(), tools, Settings(max_agent_steps=3)).investigate(load_alert("alert-oom.json"))
    assert inv.confidence == "low" and inv.steps == 3 and len(inv.evidence) == 3


def test_unknown_tool_and_bad_arguments_do_not_crash():
    tools = ToolBox(DemoClusterBackend("oom"), DemoMetricsBackend("oom"))
    assert tools.call("delete_namespace", {}).startswith("error: unknown tool")
    assert tools.call("get_pod_logs", {"nope": 1}).startswith("error: invalid arguments")


def test_secrets_are_redacted_from_tool_output():
    text = "connecting with password=hunter2 and Authorization: Bearer abc.def.ghi"
    out = redact(text)
    assert "hunter2" not in out and "abc.def.ghi" not in out


def test_json_is_extracted_from_fenced_model_output():
    assert _extract_json('Here you go:\n```json\n{"summary": "x"}\n```') == {"summary": "x"}
    assert _extract_json("no json here") is None
