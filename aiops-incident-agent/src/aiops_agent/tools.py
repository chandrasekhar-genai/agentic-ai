"""Read-only investigation tools exposed to the LLM.

Every tool is read-only. Anything that changes the cluster lives in
remediation.py and only runs after a human approves it (see ADR 0001).
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Any

from .backends import ClusterBackend, MetricsBackend

MAX_TOOL_OUTPUT_CHARS = 4000

# Strip obvious secrets before anything is sent to the LLM or a chat channel.
_SECRET_PATTERNS = [
    (re.compile(r"(?i)\bbearer\s+[a-z0-9._\-]+"), "Bearer [REDACTED]"),
    (re.compile(r"(?i)\b(password|passwd|secret|token|api[_-]?key)(\s*[:=]\s*)\S+"), r"\1\2[REDACTED]"),
    (re.compile(r"AccountKey=[^;\s]+"), "AccountKey=[REDACTED]"),
]


def redact(text: str) -> str:
    for pat, repl in _SECRET_PATTERNS:
        text = pat.sub(repl, text)
    return text


def _truncate(text: str) -> str:
    if len(text) <= MAX_TOOL_OUTPUT_CHARS:
        return text
    return text[:MAX_TOOL_OUTPUT_CHARS] + f"\n...[truncated {len(text) - MAX_TOOL_OUTPUT_CHARS} chars]"


TOOL_SCHEMAS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "get_pod_status",
            "description": "List pods matching a label selector with phase, restarts and termination reasons.",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "label_selector": {"type": "string", "description": "e.g. app=checkout-api"},
                },
                "required": ["namespace", "label_selector"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_recent_events",
            "description": "Most recent Kubernetes events in a namespace (warnings, back-offs, scheduling).",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}, "limit": {"type": "integer", "default": 20}},
                "required": ["namespace"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_pod_logs",
            "description": "Tail container logs for a pod. Use previous=true to read the crashed container.",
            "parameters": {
                "type": "object",
                "properties": {
                    "namespace": {"type": "string"},
                    "pod": {"type": "string"},
                    "tail_lines": {"type": "integer", "default": 100},
                    "previous": {"type": "boolean", "default": False},
                },
                "required": ["namespace", "pod"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "query_prometheus",
            "description": "Run an instant PromQL query (memory, CPU, latency, error rate).",
            "parameters": {
                "type": "object",
                "properties": {"promql": {"type": "string"}},
                "required": ["promql"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_deployment_replicas",
            "description": "Current desired replica count for a deployment.",
            "parameters": {
                "type": "object",
                "properties": {"namespace": {"type": "string"}, "deployment": {"type": "string"}},
                "required": ["namespace", "deployment"],
            },
        },
    },
]


class ToolBox:
    def __init__(self, cluster: ClusterBackend, metrics: MetricsBackend) -> None:
        self.cluster = cluster
        self.metrics = metrics
        self._dispatch: dict[str, Callable[..., Any]] = {
            "get_pod_status": cluster.get_pod_status,
            "get_recent_events": cluster.get_recent_events,
            "get_pod_logs": cluster.get_pod_logs,
            "query_prometheus": metrics.query,
            "get_deployment_replicas": cluster.get_deployment_replicas,
        }

    @property
    def schemas(self) -> list[dict[str, Any]]:
        return TOOL_SCHEMAS

    def call(self, name: str, arguments: dict[str, Any]) -> str:
        fn = self._dispatch.get(name)
        if fn is None:
            return f"error: unknown tool '{name}'"
        try:
            result = fn(**arguments)
        except TypeError as exc:  # bad arguments from the model
            return f"error: invalid arguments for {name}: {exc}"
        except Exception as exc:  # backend failure must not kill the investigation
            return f"error: {name} failed: {type(exc).__name__}: {exc}"
        text = result if isinstance(result, str) else json.dumps(result, default=str, indent=1)
        return _truncate(redact(text))
