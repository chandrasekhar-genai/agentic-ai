"""FinOps analyst agent.

The deterministic engines (anomalies.py, rules.py) produce the numbers. The
agent's job is the analyst's job: drill into what matters, explain it, and
prioritise. It reads the data only through tools, so every figure in its
summary is traceable to the engines, never invented.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass, field
from datetime import timedelta
from typing import Any, Protocol

from .anomalies import Anomaly
from .data import CostIndex
from .rules import Finding

SYSTEM_PROMPT = """You are a FinOps analyst for an Azure estate.
Use the tools to review cost anomalies and optimisation findings. For each anomaly,
look at the service trend before explaining it. Then write a short markdown summary:

## Executive summary  (3 sentences max, lead with the total monthly saving)
## Investigate now     (anomalies, with likely cause and owner to contact)
## Quick wins          (low-risk findings)
## Needs owner sign-off (medium-risk findings)

Only use numbers returned by the tools. Currency: {currency}."""

TOOLS = [
    {"type": "function", "function": {
        "name": "list_findings", "description": "Optimisation findings with estimated monthly savings.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "list_anomalies", "description": "Daily cost anomalies by service with top contributing resources.",
        "parameters": {"type": "object", "properties": {}}}},
    {"type": "function", "function": {
        "name": "get_service_trend", "description": "Daily cost for one service over the last N days.",
        "parameters": {"type": "object", "properties": {
            "service": {"type": "string"}, "days": {"type": "integer", "default": 21}}, "required": ["service"]}}},
]


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


class AzureOpenAILLM:
    def __init__(self) -> None:
        from openai import AzureOpenAI

        endpoint = os.environ["AZURE_OPENAI_ENDPOINT"]
        version = os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
        if os.getenv("AZURE_OPENAI_API_KEY"):
            self.client = AzureOpenAI(azure_endpoint=endpoint, api_key=os.environ["AZURE_OPENAI_API_KEY"],
                                      api_version=version)
        else:
            from azure.identity import DefaultAzureCredential, get_bearer_token_provider

            provider = get_bearer_token_provider(DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default")
            self.client = AzureOpenAI(azure_endpoint=endpoint, azure_ad_token_provider=provider, api_version=version)
        self.deployment = os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o")

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        msg = self.client.chat.completions.create(
            model=self.deployment, messages=messages, tools=tools, temperature=0
        ).choices[0].message
        calls = [ToolCall(tc.id, tc.function.name, json.loads(tc.function.arguments or "{}"))
                 for tc in (msg.tool_calls or [])]
        return LLMResponse(msg.content, calls)


class OfflineLLM:
    """Deterministic analyst: same tool protocol, template-written summary."""

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]]) -> LLMResponse:
        tool_out = {m["tool_call_id"]: m["content"] for m in messages if m["role"] == "tool"}
        if not tool_out:
            return LLMResponse(tool_calls=[ToolCall("f", "list_findings", {}), ToolCall("a", "list_anomalies", {})])
        anomalies = json.loads(tool_out["a"])
        if anomalies and not any(k.startswith("t") for k in tool_out):
            services = sorted({a["service"] for a in anomalies})
            return LLMResponse(tool_calls=[ToolCall(f"t{i}", "get_service_trend", {"service": s, "days": 21})
                                           for i, s in enumerate(services)])
        return LLMResponse(content=_template(json.loads(tool_out["f"]), anomalies, messages[0]["content"]))


def _template(findings: list[dict], anomalies: list[dict], system: str) -> str:
    cur = system.rsplit("Currency: ", 1)[-1].rstrip(".")
    total = sum(f["est_monthly_savings"] for f in findings)
    low = [f for f in findings if f["risk"] == "low"]
    med = [f for f in findings if f["risk"] != "low"]
    lines = ["## Executive summary",
             f"{len(findings)} optimisations worth about **{cur} {total:,.0f}/month** were found"
             + (f", and {len({a['service'] for a in anomalies})} service(s) show a cost anomaly "
                "that needs attention now." if anomalies else ".")
             + f" {len(low)} are low-risk and can go straight into a change; {len(med)} need owner sign-off.", ""]
    if anomalies:
        lines.append("## Investigate now")
        by_service: dict[str, list[dict]] = {}
        for a in anomalies:
            by_service.setdefault(a["service"], []).append(a)
        for service, items in by_service.items():
            excess = sum(a["actual"] - a["expected"] for a in items)
            avg_actual = sum(a["actual"] for a in items) / len(items)
            avg_expected = sum(a["expected"] for a in items) / len(items)
            tops = [a["top_resources"][0][0].rsplit("/", 1)[-1] for a in items if a["top_resources"]]
            who = f", driven by `{max(set(tops), key=tops.count)}`" if tops else ""
            lines.append(f"- **{service}** since {items[0]['day']} ({len(items)} day(s)): ~{cur} {avg_actual:,.0f}/day "
                         f"vs ~{cur} {avg_expected:,.0f} expected, {cur} {excess:,.0f} over baseline so far{who}. "
                         + _likely_cause(service))
        lines.append("")
    for title, group in (("## Quick wins", low), ("## Needs owner sign-off", med)):
        if group:
            lines.append(title)
            lines += [f"- `{f['name']}`: {f['action']} (~{cur} {f['est_monthly_savings']:,.0f}/month)" for f in group]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _likely_cause(service: str) -> str:
    return {
        "Log Analytics": "Typical causes: debug/verbose logging after a release, a new diagnostic setting, "
                         "or a noisy container; check ingestion by table (`Usage | summarize by DataType`).",
        "Bandwidth": "Check egress by resource; cross-region replication or a public download are common causes.",
        "Virtual Machines": "Check for new or resized VMs and scale-set scale-outs on that day.",
    }.get(service, "Compare resources and meters with the previous week.")


class FinOpsAgent:
    def __init__(self, llm: LLM, index: CostIndex, findings: list[Finding], anomalies: list[Anomaly],
                 max_steps: int = 6) -> None:
        self.llm, self.index, self.findings, self.anomalies, self.max_steps = (
            llm, index, findings, anomalies, max_steps)

    def _call(self, name: str, args: dict[str, Any]) -> str:
        if name == "list_findings":
            return json.dumps([asdict(f) for f in self.findings], default=str)
        if name == "list_anomalies":
            return json.dumps([asdict(a) for a in self.anomalies], default=str)
        if name == "get_service_trend":
            days = int(args.get("days", 21))
            start = self.index.last_day - timedelta(days=days - 1)
            series = [(d.isoformat(), round(c, 2)) for d, c in self.index.service_series(args["service"]) if d >= start]
            return json.dumps(series)
        return f"error: unknown tool {name}"

    def summarise(self) -> str:
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": SYSTEM_PROMPT.format(currency=self.index.currency)},
            {"role": "user", "content": "Review this period's Azure costs and write the summary."},
        ]
        for _ in range(self.max_steps):
            resp = self.llm.chat(messages, TOOLS)
            if not resp.tool_calls:
                return resp.content or ""
            messages.append({"role": "assistant", "content": resp.content, "tool_calls": [
                {"id": c.id, "type": "function", "function": {"name": c.name, "arguments": json.dumps(c.arguments)}}
                for c in resp.tool_calls]})
            for c in resp.tool_calls:
                messages.append({"role": "tool", "tool_call_id": c.id, "content": self._call(c.name, c.arguments)})
        return "## Executive summary\nThe analyst agent hit its step limit; see the tables below.\n"
