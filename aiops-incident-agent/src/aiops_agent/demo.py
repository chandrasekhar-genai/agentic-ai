"""Run one investigation end to end from the command line.

    python -m aiops_agent.demo examples/alert-oom.json
    LLM_PROVIDER=azure AZURE_OPENAI_ENDPOINT=... python -m aiops_agent.demo examples/alert-latency.json
"""

from __future__ import annotations

import json
import sys

from .agent import IncidentAgent
from .app import default_backends, default_llm
from .config import get_settings
from .models import AlertmanagerWebhook, Incident
from .notify import render
from .tools import ToolBox


def main(path: str) -> None:
    settings = get_settings()
    with open(path, encoding="utf-8") as f:
        payload = AlertmanagerWebhook.model_validate(json.load(f))
    backends, llm = default_backends(settings), default_llm(settings)
    for alert in payload.alerts:
        cluster, metrics = backends(alert)
        incident = Incident(alert=alert)
        incident.investigation = IncidentAgent(llm, ToolBox(cluster, metrics), settings).investigate(alert)
        print(render(incident))
        print("\n--- evidence ---")
        for ev in incident.investigation.evidence:
            print(f"> {ev.tool}({json.dumps(ev.arguments)})\n{ev.output}\n")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "examples/alert-oom.json")
