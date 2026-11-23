"""Domain models shared by the API, the agent and the remediation layer."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


def _now() -> datetime:
    return datetime.now(UTC)


class Alert(BaseModel):
    """A single alert as delivered in an Alertmanager webhook payload."""

    status: str = "firing"
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    startsAt: str | None = None
    fingerprint: str | None = None

    @property
    def name(self) -> str:
        return self.labels.get("alertname", "UnknownAlert")

    @property
    def namespace(self) -> str:
        return self.labels.get("namespace", "default")

    @property
    def workload(self) -> str | None:
        return self.labels.get("deployment") or self.labels.get("app") or self.labels.get("service")

    def describe(self) -> str:
        lines = [f"Alert: {self.name} ({self.status})"]
        lines += [f"label {k}={v}" for k, v in sorted(self.labels.items())]
        lines += [f"annotation {k}: {v}" for k, v in sorted(self.annotations.items())]
        return "\n".join(lines)


class AlertmanagerWebhook(BaseModel):
    """Alertmanager webhook payload (version 4)."""

    version: str = "4"
    status: str = "firing"
    receiver: str | None = None
    alerts: list[Alert] = Field(default_factory=list)


class ActionStatus(StrEnum):
    PROPOSED = "proposed"          # executable, waiting for a human
    RECOMMENDATION = "recommendation"  # needs a code/IaC change, never executed by the agent
    APPROVED = "approved"
    EXECUTED = "executed"
    FAILED = "failed"
    REJECTED = "rejected"


class RemediationAction(BaseModel):
    action: str
    target: str
    reason: str
    params: dict[str, Any] = Field(default_factory=dict)
    status: ActionStatus = ActionStatus.PROPOSED
    approved_by: str | None = None
    result: str | None = None


class Evidence(BaseModel):
    tool: str
    arguments: dict[str, Any]
    output: str


class Investigation(BaseModel):
    summary: str
    root_cause: str
    confidence: str = "medium"
    evidence: list[Evidence] = Field(default_factory=list)
    actions: list[RemediationAction] = Field(default_factory=list)
    steps: int = 0


class Incident(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:12])
    alert: Alert
    created_at: datetime = Field(default_factory=_now)
    status: str = "investigating"
    investigation: Investigation | None = None
    error: str | None = None
