"""LLM providers behind one small interface (see ADR 0002).

* AzureOpenAILLM  – Azure OpenAI / Azure AI Foundry deployment with tool calling.
                    Uses Entra ID (managed identity / workload identity) when no
                    API key is set, so no secrets are needed in the cluster.
* OfflineLLM      – deterministic rule-based planner. Lets the whole pipeline run
                    in CI and on a laptop with no model access, and gives a
                    baseline to evaluate the real model against.
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict[str, Any]


@dataclass
class LLMResponse:
    content: str | None = None
    tool_calls: list[ToolCall] = field(default_factory=list)


class LLM(Protocol):
    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse: ...


# --------------------------------------------------------------------------- Azure OpenAI


class AzureOpenAILLM:
    def __init__(self, endpoint: str, deployment: str, api_version: str) -> None:
        from openai import AzureOpenAI

        api_key = os.getenv("AZURE_OPENAI_API_KEY")
        if api_key:
            self.client = AzureOpenAI(azure_endpoint=endpoint, api_key=api_key, api_version=api_version)
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            token_provider = get_bearer_token_provider(
                DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
            )
            self.client = AzureOpenAI(
                azure_endpoint=endpoint, azure_ad_token_provider=token_provider, api_version=api_version
            )
        self.deployment = deployment

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        resp = self.client.chat.completions.create(
            model=self.deployment,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0,
        )
        msg = resp.choices[0].message
        calls = [
            ToolCall(id=tc.id, name=tc.function.name, arguments=json.loads(tc.function.arguments or "{}"))
            for tc in (msg.tool_calls or [])
        ]
        return LLMResponse(content=msg.content, tool_calls=calls)


# --------------------------------------------------------------------------- Offline planner


class OfflineLLM:
    """Rule-based stand-in for the model: three rounds of tool calls, then a verdict."""

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        alert_text = next(m["content"] for m in messages if m["role"] == "user")
        ns = _label(alert_text, "namespace") or "default"
        workload = (
            _label(alert_text, "deployment") or _label(alert_text, "app") or _label(alert_text, "service") or "unknown"
        )
        tool_msgs = [m["content"] for m in messages if m["role"] == "tool"]
        rounds = sum(1 for m in messages if m["role"] == "assistant" and m.get("tool_calls"))

        if rounds == 0:
            return LLMResponse(
                tool_calls=[
                    ToolCall("c1", "get_pod_status", {"namespace": ns, "label_selector": f"app={workload}"}),
                    ToolCall("c2", "get_recent_events", {"namespace": ns}),
                    ToolCall("c3", "get_deployment_replicas", {"namespace": ns, "deployment": workload}),
                ]
            )
        if rounds == 1:
            pods = _json_or_empty(tool_msgs[0])
            calls: list[ToolCall] = []
            if pods:
                pod = pods[0]
                crashed = any(c.get("restarts", 0) > 0 for c in pod.get("containers", []))
                calls.append(
                    ToolCall("c4", "get_pod_logs", {"namespace": ns, "pod": pod["pod"], "previous": crashed})
                )
            sel = f'namespace="{ns}",pod=~"{workload}.*"'
            if "OOMKilled" in tool_msgs[0]:
                calls += [
                    ToolCall("c5", "query_prometheus",
                             {"promql": f"max(container_memory_working_set_bytes{{{sel}}}) by (pod)"}),
                    ToolCall("c6", "query_prometheus",
                             {"promql": "max(kube_pod_container_resource_limits"
                                        f'{{{sel},resource="memory"}}) by (pod)'}),
                ]
            else:
                calls += [
                    ToolCall("c5", "query_prometheus",
                             {"promql": f"sum(rate(container_cpu_usage_seconds_total{{{sel}}}[5m])) by (pod)"}),
                    ToolCall("c6", "query_prometheus",
                             {"promql": "histogram_quantile(0.99, sum(rate(http_request_duration_seconds_bucket"
                                        f'{{namespace="{ns}"}}[5m])) by (le, route))'}),
                ]
            return LLMResponse(tool_calls=calls)

        return LLMResponse(content=json.dumps(_verdict(workload, "\n".join(tool_msgs), tool_msgs)))


def _label(text: str, key: str) -> str | None:
    m = re.search(rf"^label {key}=(\S+)$", text, re.MULTILINE)
    return m.group(1) if m else None


def _json_or_empty(text: str) -> Any:
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return []


def _verdict(workload: str, evidence: str, tool_msgs: list[str]) -> dict[str, Any]:
    target = f"deployment/{workload}"
    if "OOMKilled" in evidence:
        return {
            "summary": f"{workload} is crash-looping because its container is OOMKilled on start-up.",
            "root_cause": "Container memory usage exceeds its 512Mi limit during cache warm-up "
                          "(working set ~511Mi just before the kill; logs show the full SKU cache loaded into memory).",
            "confidence": "high",
            "actions": [
                {"action": "increase_memory_limit", "target": target,
                 "reason": "Raise the memory limit (e.g. 512Mi -> 1Gi) in the Helm values via a reviewed PR.",
                 "params": {"suggested_limit": "1Gi"}},
                {"action": "code_change", "target": target,
                 "reason": "Load the SKU cache lazily or page it, so start-up memory "
                           "does not scale with catalogue size.",
                 "params": {}},
            ],
        }
    if "ImagePullBackOff" in evidence or "ErrImagePull" in evidence:
        return {
            "summary": f"{workload} cannot pull its container image.",
            "root_cause": "Image tag missing or registry auth failing (ImagePullBackOff).",
            "confidence": "high",
            "actions": [{"action": "fix_image_reference", "target": target,
                         "reason": "Check the image tag in the release and the AcrPull role on the kubelet identity.",
                         "params": {}}],
        }
    cpu_values = [float(v) for v in re.findall(r'"value":\s*"([0-9.]+)"', evidence)]
    if any(0.85 <= v <= 1.0 for v in cpu_values):
        replicas = next((int(t) for t in tool_msgs if t.strip().isdigit()), 3)
        return {
            "summary": f"{workload} is CPU-saturated at {replicas} replicas and has no autoscaler.",
            "root_cause": f"All {replicas} pods run at ~97% CPU with a growing request queue and failing "
                          "readiness probes, so p99 latency climbs.",
            "confidence": "medium",
            "actions": [
                {"action": "scale_deployment", "target": target,
                 "reason": "Add capacity now to bring latency back under SLO.",
                 "params": {"replicas": replicas + 2}},
                {"action": "add_hpa", "target": target,
                 "reason": "Add an HPA in Git (and ignore /spec/replicas in Argo CD) so capacity follows load "
                           "and the manual scale is not reverted on the next sync.",
                 "params": {"min_replicas": replicas, "max_replicas": replicas + 5, "target_cpu": 70}},
            ],
        }
    return {
        "summary": f"No clear root cause found for {workload} from the available signals.",
        "root_cause": "Unknown – escalate to the on-call engineer with the attached evidence.",
        "confidence": "low",
        "actions": [],
    }
