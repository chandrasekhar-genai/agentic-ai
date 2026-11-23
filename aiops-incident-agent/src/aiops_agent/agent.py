"""The investigation loop: model plans → read-only tools run → model concludes."""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from .config import Settings
from .llm import LLM
from .models import Alert, Evidence, Investigation
from .remediation import validate_action
from .tools import ToolBox

log = logging.getLogger(__name__)

SYSTEM_PROMPT = """You are a senior SRE investigating a production alert on Kubernetes.

Work like an on-call engineer:
1. Check pod status and recent events for the affected workload.
2. Read logs (use previous=true for crashed containers) and query Prometheus to confirm.
3. Stop as soon as the evidence supports a root cause. Do not guess beyond the evidence.

When you are done, reply with ONLY a JSON object:
{
  "summary": "one sentence for the incident channel",
  "root_cause": "what is wrong and the evidence for it",
  "confidence": "high | medium | low",
  "actions": [
    {"action": "<name>", "target": "deployment/<name>", "reason": "<why>", "params": {}}
  ]
}
Executable actions are limited to rollout_restart and scale_deployment (params.replicas).
Anything else (limits, HPA, config, code) is a recommendation for a pull request.
Never include secrets from logs in your answer."""


class IncidentAgent:
    def __init__(self, llm: LLM, tools: ToolBox, settings: Settings) -> None:
        self.llm = llm
        self.tools = tools
        self.settings = settings

    def investigate(self, alert: Alert) -> Investigation:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": alert.describe()},
        ]
        evidence: list[Evidence] = []

        for step in range(1, self.settings.max_agent_steps + 1):
            resp = self.llm.chat(messages, self.tools.schemas)

            if not resp.tool_calls:
                result = self._parse_verdict(resp.content or "", alert)
                result.evidence = evidence
                result.steps = step
                return result

            messages.append(
                {
                    "role": "assistant",
                    "content": resp.content,
                    "tool_calls": [
                        {"id": tc.id, "type": "function",
                         "function": {"name": tc.name, "arguments": json.dumps(tc.arguments)}}
                        for tc in resp.tool_calls
                    ],
                }
            )
            for tc in resp.tool_calls:
                output = self.tools.call(tc.name, tc.arguments)
                log.info("step=%s tool=%s args=%s", step, tc.name, tc.arguments)
                evidence.append(Evidence(tool=tc.name, arguments=tc.arguments, output=output))
                messages.append({"role": "tool", "tool_call_id": tc.id, "content": output})

        return Investigation(
            summary=f"Investigation of {alert.name} hit the {self.settings.max_agent_steps}-step limit.",
            root_cause="Undetermined – escalate with the collected evidence.",
            confidence="low",
            evidence=evidence,
            steps=self.settings.max_agent_steps,
        )

    def _parse_verdict(self, content: str, alert: Alert) -> Investigation:
        data = _extract_json(content)
        if data is None:
            return Investigation(
                summary=f"Model returned an unstructured answer for {alert.name}.",
                root_cause=content.strip()[:2000] or "No answer.",
                confidence="low",
            )
        actions = [
            a for a in (validate_action(raw, alert.namespace, self.settings) for raw in data.get("actions", []))
            if a is not None
        ]
        return Investigation(
            summary=str(data.get("summary", "")),
            root_cause=str(data.get("root_cause", "")),
            confidence=str(data.get("confidence", "medium")).lower(),
            actions=actions,
        )


def _extract_json(text: str) -> dict[str, Any] | None:
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    candidate = fenced.group(1) if fenced else text[text.find("{"): text.rfind("}") + 1]
    try:
        data = json.loads(candidate)
    except (json.JSONDecodeError, ValueError):
        return None
    return data if isinstance(data, dict) else None
