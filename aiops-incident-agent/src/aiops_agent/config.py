"""Runtime configuration, read from environment variables (12-factor)."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class Settings:
    # LLM: "azure" uses Azure OpenAI; "offline" uses the deterministic rule-based planner
    llm_provider: str = field(default_factory=lambda: os.getenv("LLM_PROVIDER", "offline"))
    azure_openai_endpoint: str | None = field(default_factory=lambda: os.getenv("AZURE_OPENAI_ENDPOINT"))
    azure_openai_deployment: str = field(default_factory=lambda: os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"))
    azure_openai_api_version: str = field(
        default_factory=lambda: os.getenv("AZURE_OPENAI_API_VERSION", "2024-10-21")
    )

    # Data sources
    demo_mode: bool = field(default_factory=lambda: _bool("AIOPS_DEMO", True))
    demo_scenario: str = field(default_factory=lambda: os.getenv("AIOPS_DEMO_SCENARIO", "auto"))
    prometheus_url: str = field(default_factory=lambda: os.getenv("PROMETHEUS_URL", "http://prometheus:9090"))

    # Notifications (Slack or Teams incoming webhook); empty = log only
    notify_webhook_url: str | None = field(default_factory=lambda: os.getenv("NOTIFY_WEBHOOK_URL"))
    public_base_url: str = field(default_factory=lambda: os.getenv("PUBLIC_BASE_URL", ""))

    # Shared token for the approve/reject endpoints. Put the service behind an
    # OIDC-authenticating ingress in production; this is defence in depth.
    approval_token: str | None = field(default_factory=lambda: os.getenv("APPROVAL_TOKEN"))

    # Guardrails
    max_agent_steps: int = field(default_factory=lambda: int(os.getenv("MAX_AGENT_STEPS", "8")))
    max_scale_replicas: int = field(default_factory=lambda: int(os.getenv("MAX_SCALE_REPLICAS", "10")))
    allowed_namespaces: tuple[str, ...] = field(
        default_factory=lambda: tuple(
            n.strip() for n in os.getenv("ALLOWED_NAMESPACES", "").split(",") if n.strip()
        )
    )


def get_settings() -> Settings:
    return Settings()
