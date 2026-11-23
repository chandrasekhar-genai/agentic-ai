"""Data-source backends: Kubernetes, Prometheus, and offline demo fixtures.

The agent only ever talks to these through `ToolBox` (see tools.py), so real
clusters and the demo fixtures are interchangeable — which is also what makes
the agent unit-testable without a cluster or an LLM key.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Protocol

import httpx


class ClusterBackend(Protocol):
    def get_pod_status(self, namespace: str, label_selector: str) -> list[dict[str, Any]]: ...
    def get_recent_events(self, namespace: str, limit: int = 20) -> list[dict[str, Any]]: ...
    def get_pod_logs(self, namespace: str, pod: str, tail_lines: int = 100, previous: bool = False) -> str: ...
    def get_deployment_replicas(self, namespace: str, deployment: str) -> int: ...
    def rollout_restart(self, namespace: str, deployment: str) -> str: ...
    def scale_deployment(self, namespace: str, deployment: str, replicas: int) -> str: ...


class MetricsBackend(Protocol):
    def query(self, promql: str) -> list[dict[str, Any]]: ...


# --------------------------------------------------------------------------- real


class KubernetesBackend:
    """Thin wrapper over the official Kubernetes client (in-cluster or kubeconfig)."""

    def __init__(self) -> None:
        from kubernetes import client, config

        try:
            config.load_incluster_config()
        except config.ConfigException:
            config.load_kube_config()
        self.core = client.CoreV1Api()
        self.apps = client.AppsV1Api()

    def get_pod_status(self, namespace: str, label_selector: str) -> list[dict[str, Any]]:
        pods = self.core.list_namespaced_pod(namespace, label_selector=label_selector).items
        out = []
        for p in pods:
            statuses = p.status.container_statuses or []
            out.append(
                {
                    "pod": p.metadata.name,
                    "phase": p.status.phase,
                    "node": p.spec.node_name,
                    "containers": [
                        {
                            "name": c.name,
                            "ready": c.ready,
                            "restarts": c.restart_count,
                            "waiting_reason": c.state.waiting.reason if c.state and c.state.waiting else None,
                            "last_termination_reason": (
                                c.last_state.terminated.reason
                                if c.last_state and c.last_state.terminated
                                else None
                            ),
                        }
                        for c in statuses
                    ],
                }
            )
        return out

    def get_recent_events(self, namespace: str, limit: int = 20) -> list[dict[str, Any]]:
        events = self.core.list_namespaced_event(namespace).items
        epoch = datetime.min.replace(tzinfo=UTC)
        events.sort(key=lambda e: e.last_timestamp or e.event_time or epoch, reverse=True)
        return [
            {
                "type": e.type,
                "reason": e.reason,
                "object": f"{e.involved_object.kind}/{e.involved_object.name}",
                "message": e.message,
                "count": e.count,
            }
            for e in events[:limit]
        ]

    def get_pod_logs(self, namespace: str, pod: str, tail_lines: int = 100, previous: bool = False) -> str:
        return self.core.read_namespaced_pod_log(pod, namespace, tail_lines=tail_lines, previous=previous)

    def get_deployment_replicas(self, namespace: str, deployment: str) -> int:
        return self.apps.read_namespaced_deployment_scale(deployment, namespace).spec.replicas

    def rollout_restart(self, namespace: str, deployment: str) -> str:
        now = datetime.now(UTC).isoformat()
        body = {"spec": {"template": {"metadata": {"annotations": {"kubectl.kubernetes.io/restartedAt": now}}}}}
        self.apps.patch_namespaced_deployment(deployment, namespace, body)
        return f"rollout restart triggered for deployment/{deployment} at {now}"

    def scale_deployment(self, namespace: str, deployment: str, replicas: int) -> str:
        self.apps.patch_namespaced_deployment_scale(deployment, namespace, {"spec": {"replicas": replicas}})
        return f"deployment/{deployment} scaled to {replicas} replicas"


class PrometheusBackend:
    def __init__(self, base_url: str, timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def query(self, promql: str) -> list[dict[str, Any]]:
        r = httpx.get(f"{self.base_url}/api/v1/query", params={"query": promql}, timeout=self.timeout)
        r.raise_for_status()
        data = r.json()
        if data.get("status") != "success":
            raise RuntimeError(f"Prometheus query failed: {data}")
        return [{"metric": s["metric"], "value": s["value"][1]} for s in data["data"]["result"]]


# --------------------------------------------------------------------------- demo

_SCENARIOS: dict[str, dict[str, Any]] = {
    "oom": {
        "pods": [
            {
                "pod": "checkout-api-7d9f8b6c5-x2k4p",
                "phase": "Running",
                "node": "aks-user-12345678-vmss000002",
                "containers": [
                    {
                        "name": "checkout-api",
                        "ready": False,
                        "restarts": 14,
                        "waiting_reason": "CrashLoopBackOff",
                        "last_termination_reason": "OOMKilled",
                    }
                ],
            }
        ],
        "events": [
            {"type": "Warning", "reason": "BackOff", "object": "Pod/checkout-api-7d9f8b6c5-x2k4p",
             "message": "Back-off restarting failed container checkout-api", "count": 37},
            {"type": "Normal", "reason": "ScalingReplicaSet", "object": "Deployment/checkout-api",
             "message": "Scaled up replica set checkout-api-7d9f8b6c5 to 1", "count": 1},
        ],
        "logs": (
            "INFO  starting checkout-api v2.8.0\n"
            "INFO  warming product cache: loading 1,200,000 SKUs into memory\n"
            "WARN  heap usage 480Mi / limit 512Mi\n"
        ),
        "metrics": {
            "memory": [{"metric": {"pod": "checkout-api-7d9f8b6c5-x2k4p"}, "value": "535822336"}],
            "limit": [{"metric": {"pod": "checkout-api-7d9f8b6c5-x2k4p"}, "value": "536870912"}],
        },
        "replicas": 1,
    },
    "saturation": {
        "pods": [
            {"pod": f"payments-api-5c4d9-{s}", "phase": "Running", "node": "aks-user-vmss00000" + str(i),
             "containers": [{"name": "payments-api", "ready": True, "restarts": 0,
                             "waiting_reason": None, "last_termination_reason": None}]}
            for i, s in enumerate(["a1b2c", "d3e4f", "g5h6i"])
        ],
        "events": [
            {"type": "Warning", "reason": "Unhealthy", "object": "Pod/payments-api-5c4d9-d3e4f",
             "message": "Readiness probe failed: Get \"http://10.244.1.17:8080/ready\": context deadline exceeded",
             "count": 9},
        ],
        "logs": "WARN  request queue depth 412 (threshold 100)\nWARN  p99 latency 2.4s on POST /v1/charge\n",
        "metrics": {
            "cpu": [
                {"metric": {"pod": f"payments-api-5c4d9-{s}"}, "value": "0.97"} for s in ["a1b2c", "d3e4f", "g5h6i"]
            ],
            "latency": [{"metric": {"route": "/v1/charge"}, "value": "2.41"}],
        },
        "replicas": 3,
    },
}


def pick_scenario(alert_name: str, configured: str = "auto") -> str:
    if configured in _SCENARIOS:
        return configured
    name = alert_name.lower()
    if any(k in name for k in ("latency", "cpu", "saturation", "throttl")):
        return "saturation"
    return "oom"


class DemoClusterBackend:
    """Canned cluster state so the full flow runs on a laptop with no cluster."""

    def __init__(self, scenario: str = "oom") -> None:
        self.s = _SCENARIOS[scenario]
        self.actions: list[str] = []

    def get_pod_status(self, namespace: str, label_selector: str) -> list[dict[str, Any]]:
        return self.s["pods"]

    def get_recent_events(self, namespace: str, limit: int = 20) -> list[dict[str, Any]]:
        return self.s["events"][:limit]

    def get_pod_logs(self, namespace: str, pod: str, tail_lines: int = 100, previous: bool = False) -> str:
        return self.s["logs"]

    def get_deployment_replicas(self, namespace: str, deployment: str) -> int:
        return self.s["replicas"]

    def rollout_restart(self, namespace: str, deployment: str) -> str:
        msg = f"[demo] rollout restart deployment/{deployment} in {namespace}"
        self.actions.append(msg)
        return msg

    def scale_deployment(self, namespace: str, deployment: str, replicas: int) -> str:
        msg = f"[demo] scaled deployment/{deployment} in {namespace} to {replicas}"
        self.actions.append(msg)
        return msg


class DemoMetricsBackend:
    def __init__(self, scenario: str = "oom") -> None:
        self.s = _SCENARIOS[scenario]

    # checked in order: "limit" before "memory" because limit queries mention memory too
    _KEYWORDS = (
        ("limit", ("limit",)),
        ("memory", ("memory", "working_set")),
        ("cpu", ("cpu",)),
        ("latency", ("latency", "duration")),
    )

    def query(self, promql: str) -> list[dict[str, Any]]:
        q = promql.lower()
        for key, words in self._KEYWORDS:
            if key in self.s["metrics"] and any(w in q for w in words):
                return self.s["metrics"][key]
        return []
