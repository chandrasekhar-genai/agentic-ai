"""FastAPI service: Alertmanager webhook in, investigations and approvals out."""

from __future__ import annotations

import hmac
import logging
from collections.abc import Callable

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException

from . import __version__, notify
from .agent import IncidentAgent
from .backends import (
    ClusterBackend,
    DemoClusterBackend,
    DemoMetricsBackend,
    KubernetesBackend,
    MetricsBackend,
    PrometheusBackend,
    pick_scenario,
)
from .config import Settings, get_settings
from .llm import LLM, AzureOpenAILLM, OfflineLLM
from .models import ActionStatus, Alert, AlertmanagerWebhook, Incident
from .remediation import execute
from .tools import ToolBox

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("aiops_agent")

BackendFactory = Callable[[Alert], tuple[ClusterBackend, MetricsBackend]]


def default_backends(settings: Settings) -> BackendFactory:
    if settings.demo_mode:
        def demo(alert: Alert) -> tuple[ClusterBackend, MetricsBackend]:
            scenario = pick_scenario(alert.name, settings.demo_scenario)
            return DemoClusterBackend(scenario), DemoMetricsBackend(scenario)
        return demo

    cluster, metrics = KubernetesBackend(), PrometheusBackend(settings.prometheus_url)
    return lambda _alert: (cluster, metrics)


def default_llm(settings: Settings) -> LLM:
    if settings.llm_provider == "azure":
        if not settings.azure_openai_endpoint:
            raise RuntimeError("LLM_PROVIDER=azure requires AZURE_OPENAI_ENDPOINT")
        return AzureOpenAILLM(
            settings.azure_openai_endpoint, settings.azure_openai_deployment, settings.azure_openai_api_version
        )
    return OfflineLLM()


def create_app(
    settings: Settings | None = None,
    backends: BackendFactory | None = None,
    llm: LLM | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    backends = backends or default_backends(settings)
    llm = llm or default_llm(settings)

    app = FastAPI(title="AIOps Incident Agent", version=__version__)
    incidents: dict[str, Incident] = {}
    clusters: dict[str, ClusterBackend] = {}

    def run_investigation(incident: Incident) -> None:
        cluster, metrics = backends(incident.alert)
        clusters[incident.id] = cluster
        agent = IncidentAgent(llm, ToolBox(cluster, metrics), settings)
        try:
            incident.investigation = agent.investigate(incident.alert)
            incident.status = "awaiting_approval" if any(
                a.status == ActionStatus.PROPOSED for a in incident.investigation.actions
            ) else "investigated"
        except Exception as exc:
            log.exception("investigation failed for %s", incident.id)
            incident.status, incident.error = "failed", f"{type(exc).__name__}: {exc}"
        notify.send(notify.render(incident, settings.public_base_url), settings.notify_webhook_url)

    def check_token(token: str | None) -> None:
        if settings.approval_token and not hmac.compare_digest(token or "", settings.approval_token):
            raise HTTPException(status_code=401, detail="invalid approval token")

    def get_action(incident_id: str, index: int):
        incident = incidents.get(incident_id)
        if incident is None or incident.investigation is None:
            raise HTTPException(status_code=404, detail="incident not found or still investigating")
        if not 0 <= index < len(incident.investigation.actions):
            raise HTTPException(status_code=404, detail="action not found")
        return incident, incident.investigation.actions[index]

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok", "version": __version__, "llm": settings.llm_provider,
                "mode": "demo" if settings.demo_mode else "cluster"}

    @app.post("/alerts", status_code=202)
    def receive_alerts(payload: AlertmanagerWebhook, background: BackgroundTasks) -> dict[str, list[str]]:
        created = []
        for alert in payload.alerts:
            if alert.status != "firing":
                continue
            incident = Incident(alert=alert)
            incidents[incident.id] = incident
            background.add_task(run_investigation, incident)
            created.append(incident.id)
        return {"incidents": created}

    @app.get("/incidents")
    def list_incidents() -> list[Incident]:
        return sorted(incidents.values(), key=lambda i: i.created_at, reverse=True)

    @app.get("/incidents/{incident_id}")
    def get_incident(incident_id: str) -> Incident:
        if incident_id not in incidents:
            raise HTTPException(status_code=404, detail="incident not found")
        return incidents[incident_id]

    @app.post("/incidents/{incident_id}/actions/{index}/approve")
    def approve(
        incident_id: str,
        index: int,
        x_approver: str = Header(..., description="Name or UPN of the approving engineer"),
        x_approval_token: str | None = Header(None),
    ):
        check_token(x_approval_token)
        incident, action = get_action(incident_id, index)
        if action.status != ActionStatus.PROPOSED:
            raise HTTPException(status_code=409, detail=f"action is {action.status.value}")
        execute(action, clusters[incident_id], incident.alert.namespace, x_approver)
        log.info("action %s on %s approved by %s -> %s", action.action, action.target, x_approver, action.status)
        if not any(a.status == ActionStatus.PROPOSED for a in incident.investigation.actions):
            incident.status = "remediated" if action.status == ActionStatus.EXECUTED else "remediation_failed"
        return action

    @app.post("/incidents/{incident_id}/actions/{index}/reject")
    def reject(
        incident_id: str,
        index: int,
        x_approver: str = Header(...),
        x_approval_token: str | None = Header(None),
    ):
        check_token(x_approval_token)
        _, action = get_action(incident_id, index)
        if action.status != ActionStatus.PROPOSED:
            raise HTTPException(status_code=409, detail=f"action is {action.status.value}")
        action.status, action.approved_by = ActionStatus.REJECTED, x_approver
        return action

    return app

