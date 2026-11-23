"""Guardrails for remediation.

The model may *propose* anything, but only actions on the allowlist below can be
executed, only against a Deployment, only within configured namespaces and
bounds, and only after a named human approves (ADR 0001). Everything else is
kept as a recommendation for a Git/IaC change.
"""

from __future__ import annotations

from typing import Any

from .backends import ClusterBackend
from .config import Settings
from .models import ActionStatus, RemediationAction

EXECUTABLE_ACTIONS = {"rollout_restart", "scale_deployment"}


def validate_action(raw: dict[str, Any], namespace: str, settings: Settings) -> RemediationAction | None:
    action = str(raw.get("action", "")).strip()
    target = str(raw.get("target", "")).strip()
    reason = str(raw.get("reason", "")).strip()
    params = raw.get("params") or {}
    if not action or not target:
        return None

    proposed = RemediationAction(action=action, target=target, reason=reason, params=params)
    if action not in EXECUTABLE_ACTIONS:
        proposed.status = ActionStatus.RECOMMENDATION
        return proposed

    if not target.startswith("deployment/"):
        return _as_recommendation(proposed, "only Deployments can be changed automatically")
    if settings.allowed_namespaces and namespace not in settings.allowed_namespaces:
        return _as_recommendation(proposed, f"namespace '{namespace}' is not in ALLOWED_NAMESPACES")
    if action == "scale_deployment":
        replicas = params.get("replicas")
        if not isinstance(replicas, int) or not 1 <= replicas <= settings.max_scale_replicas:
            return _as_recommendation(
                proposed, f"replicas must be an integer between 1 and {settings.max_scale_replicas}"
            )
    return proposed


def _as_recommendation(action: RemediationAction, why: str) -> RemediationAction:
    action.status = ActionStatus.RECOMMENDATION
    action.result = f"not executable: {why}"
    return action


def execute(action: RemediationAction, cluster: ClusterBackend, namespace: str, approver: str) -> RemediationAction:
    if action.status != ActionStatus.PROPOSED:
        raise ValueError(f"action is '{action.status.value}', only 'proposed' actions can be approved")
    action.status = ActionStatus.APPROVED
    action.approved_by = approver
    deployment = action.target.split("/", 1)[1]
    try:
        if action.action == "rollout_restart":
            action.result = cluster.rollout_restart(namespace, deployment)
        elif action.action == "scale_deployment":
            action.result = cluster.scale_deployment(namespace, deployment, int(action.params["replicas"]))
        action.status = ActionStatus.EXECUTED
    except Exception as exc:  # report, never raise into the API
        action.status = ActionStatus.FAILED
        action.result = f"{type(exc).__name__}: {exc}"
    return action
