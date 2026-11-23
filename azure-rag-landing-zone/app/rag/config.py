from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default)


@dataclass(frozen=True)
class Settings:
    # "azure" = Azure OpenAI via APIM + Azure AI Search; "local" = offline, in-memory, deterministic
    mode: str = field(default_factory=lambda: _env("RAG_MODE", "local"))
    openai_endpoint: str = field(default_factory=lambda: _env("OPENAI_ENDPOINT"))  # APIM gateway URL
    openai_api_version: str = field(default_factory=lambda: _env("OPENAI_API_VERSION", "2024-10-21"))
    chat_deployment: str = field(default_factory=lambda: _env("CHAT_DEPLOYMENT", "chat"))
    embedding_deployment: str = field(default_factory=lambda: _env("EMBEDDING_DEPLOYMENT", "embeddings"))
    embedding_dimensions: int = field(default_factory=lambda: int(_env("EMBEDDING_DIMENSIONS", "1024")))
    search_endpoint: str = field(default_factory=lambda: _env("SEARCH_ENDPOINT"))
    search_index: str = field(default_factory=lambda: _env("SEARCH_INDEX", "docs"))
    top_k: int = field(default_factory=lambda: int(_env("TOP_K", "4")))
    min_relevance: float = field(default_factory=lambda: float(_env("MIN_RELEVANCE", "0.12")))
    docs_dir: Path = field(default_factory=lambda: Path(_env("DOCS_DIR", str(ROOT / "data" / "docs"))))
    max_question_chars: int = 1000
