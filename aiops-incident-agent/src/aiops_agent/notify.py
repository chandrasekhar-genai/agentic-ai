"""Post incident summaries to Slack or Microsoft Teams (incoming webhook)."""

from __future__ import annotations

import logging

import httpx

from .models import ActionStatus, Incident

log = logging.getLogger(__name__)


def render(incident: Incident, base_url: str = "") -> str:
    inv = incident.investigation
    if inv is None:
        return f"Incident {incident.id}: {incident.alert.name} – {incident.status}"
    lines = [
        f"*{incident.alert.name}* in `{incident.alert.namespace}` – confidence: {inv.confidence}",
        f"*Summary:* {inv.summary}",
        f"*Root cause:* {inv.root_cause}",
    ]
    for i, a in enumerate(inv.actions):
        if a.status == ActionStatus.PROPOSED:
            lines.append(
                f"• [{i}] `{a.action}` on `{a.target}` {a.params or ''} – {a.reason}\n"
                f"   approve: `POST {base_url}/incidents/{incident.id}/actions/{i}/approve`"
            )
        else:
            lines.append(f"• `{a.action}` on `{a.target}` (needs PR) – {a.reason}")
    lines.append(f"_Evidence: {len(inv.evidence)} tool calls, {inv.steps} reasoning steps_")
    return "\n".join(lines)


def send(text: str, webhook_url: str | None) -> None:
    if not webhook_url:
        log.info("notification (no webhook configured):\n%s", text)
        return
    try:
        httpx.post(webhook_url, json={"text": text}, timeout=10).raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("failed to send notification: %s", exc)
